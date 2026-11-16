"""Opening the store.

A store directory in a fresh clone has only the committed files (manifest,
parquet parts, schema). Relate refuses a read-only open until its per-machine
files (lock file and write-ahead log) exist, and those are not committed. So a
first open on a new machine goes through one writable open, which creates them
without touching the data, and then reopens read-only.
"""

from __future__ import annotations

import os
from pathlib import Path

import relate

PRIVATE_STORE = Path("~/.faildex/store")


def open_store(path: str | Path, read_only: bool = True):
    """Connect to the store at `path`. Raises FileNotFoundError when there is none."""
    path = Path(path)
    if not (path / "manifest.json").is_file():
        raise FileNotFoundError(f"no store at {path}; run `make build-store` first")
    if not read_only:
        return relate.connect(str(path))
    try:
        return relate.connect(str(path), read_only=True)
    except relate.OperationalError:
        relate.connect(str(path)).close()
        return relate.connect(str(path), read_only=True)


def default_store() -> Path:
    """Where commands look when no store is named.

    `FAILDEX_STORE` if set; otherwise the store of the current directory (the
    committed public one, inside this repository); otherwise the private store
    in the home directory that `faildex ingest` writes.
    """
    named = os.environ.get("FAILDEX_STORE")
    if named:
        return Path(named).expanduser()
    local = Path("store")
    return local if (local / "manifest.json").is_file() else PRIVATE_STORE.expanduser()
