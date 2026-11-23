"""Opening the store.

A store directory in a fresh clone has only the committed files (manifest,
parquet parts, schema). Relate refuses a read-only open until its per-machine
files (lock file and write-ahead log) exist, and those are not committed. So a
first open on a new machine goes through one writable open, which creates them
without touching the data, and then reopens read-only.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import relate

PRIVATE_STORE = Path("~/.faildex/store")
# The committed files of a store; lock files and the write-ahead log are per machine.
STORE_PARTS = ("manifest.json", "nodes", "relationships", ".cypherlite")
_HERE = Path(__file__).resolve().parent


def open_store(path: str | Path, read_only: bool = True):
    """Connect to the store at `path`. Raises FileNotFoundError when there is none."""
    path = Path(path)
    if not (path / "manifest.json").is_file():
        raise FileNotFoundError(
            f"no store at {path}; `faildex ingest --store {path}` creates one from your logs"
        )
    if not read_only:
        return relate.connect(str(path))
    try:
        return relate.connect(str(path), read_only=True)
    except relate.OperationalError:
        relate.connect(str(path)).close()
        return relate.connect(str(path), read_only=True)


def _shipped_store() -> Path | None:
    """The public store that came with this copy of faildex, wherever it is installed.

    A wheel carries it as package data (`faildex/_store`); a checkout or an editable
    install finds the repository's `store/` next to `src/`.
    """
    for candidate in (_HERE / "_store", _HERE.parents[1] / "store"):
        if (candidate / "manifest.json").is_file():
            return candidate
    return None


def public_store() -> Path:
    """A ready-to-open copy of the public demo store.

    The shipped files are copied once into a cache folder named after their
    manifest, so opening never writes inside the installed package.
    """
    shipped = _shipped_store()
    if shipped is None:
        raise FileNotFoundError("this copy of faildex has no public store; reinstall it")
    digest = hashlib.sha256((shipped / "manifest.json").read_bytes()).hexdigest()[:12]
    cache = (
        Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser()
        / "faildex"
        / f"store-{digest}"
    )
    if not (cache / "manifest.json").is_file():
        # A private temporary folder per process, so two first runs cannot trip each other.
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=cache.name + ".tmp-", dir=cache.parent))
        try:
            for part in STORE_PARTS:
                src = shipped / part
                if src.is_dir():
                    shutil.copytree(src, tmp / part)
                elif src.is_file():
                    shutil.copy2(src, tmp / part)
            try:
                tmp.rename(cache)
            except OSError:
                # Another process finished first (keep its copy), or an old partial folder
                # without a manifest is in the way (replace it once).
                if not (cache / "manifest.json").is_file():
                    shutil.rmtree(cache, ignore_errors=True)
                    tmp.rename(cache)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return cache


def default_store() -> Path:
    """Where commands look when no store is named.

    `FAILDEX_STORE` if set; otherwise the store of the current directory (the
    committed public one, inside this repository); otherwise the private store
    in the home directory that `faildex ingest` writes, once it exists;
    otherwise the public demo store that ships with faildex.
    """
    named = os.environ.get("FAILDEX_STORE")
    if named:
        return Path(named).expanduser()
    local = Path("store")
    if (local / "manifest.json").is_file():
        return local
    private = PRIVATE_STORE.expanduser()
    if (private / "manifest.json").is_file():
        return private
    try:
        return public_store()
    except FileNotFoundError:
        return private
