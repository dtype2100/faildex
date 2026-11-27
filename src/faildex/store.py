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

PRIVATE_STORE = Path("~/.faildex/store")
# The committed files of a store; lock files and the write-ahead log are per machine.
STORE_PARTS = ("manifest.json", "nodes", "relationships", ".cypherlite")
_HERE = Path(__file__).resolve().parent


def open_store(path: str | Path, read_only: bool = True, *, wait: bool = True):
    """Connect to the store at `path`. Raises FileNotFoundError when there is none.

    A fresh copy is prepared first (`_prepare`); with `wait=False`, a copy whose write
    lock someone else holds raises instead of waiting.
    """
    path = Path(path)
    if not (path / "manifest.json").is_file():
        from faildex.i18n import t

        raise FileNotFoundError(t("err.no_store", path=path))
    import relate  # here, not at the top: the hook reads its index without Relate

    if not read_only:
        return relate.connect(str(path))
    try:
        return relate.connect(str(path), read_only=True)
    except relate.OperationalError:
        _prepare(path, wait)
        return relate.connect(str(path), read_only=True)


def _prepare(path: Path, wait: bool = True) -> None:
    """The one writable open that creates the per-machine files of a fresh copy.

    Always under the write lock (created if missing), so it can never run while
    `write_store` has the store set aside: a writable open of the missing folder would
    create an empty store there. Once the lock is held, the store must still be there.
    """
    import relate

    from faildex.locks import held

    with held(_write_lock(path), wait=wait) as got:
        if not got:
            raise relate.OperationalError(f"{path} is being written")
        if not _has_store(Path(path)):
            raise relate.OperationalError(f"{path} is being replaced")
        relate.connect(str(path)).close()


def _write_lock(path: Path) -> Path:
    """The write lock of a store: a fixed name next to it, outside the folder a swap moves."""
    path = Path(path).resolve()
    return path.parent / f".{path.name}.write-lock"


# How often to retry moving the store aside, and how long to wait between tries.
SWAP_TRIES = 3
SWAP_WAIT = 0.5
# Inside every work folder and set-aside store: who made it, for which store, and its token.
SWAP_MARK = ".faildex-swap.json"


def write_store(out: Path, write, after=None) -> bool:
    """Run `write(db)` on a copy of the store at `out`, then put the copy in its place.

    Readers keep seeing the untouched store while the copy is written, the way
    `build_store` swaps in a rebuilt store. A failed write leaves the store as it was.
    Returns False when the copy could not be swapped in (Windows refuses to rename a
    folder that a reader holds open): the old store is then kept and the copy dropped.

    Everything happens under the store's write lock, `after(out)` included, so writers
    take turns and whatever `after` publishes about the store (the hook's index) belongs
    to the store this writer put in place. A store reached through a symlink is written
    where the link points.

    Only folders proven ours are ever deleted: the work folder and set-aside store of
    this writer, named with its own random token and marked inside with that token and
    this store's path. A writer that is killed leaves them behind; the next writer puts
    a set-aside store back but deletes nothing of another writer's.
    """
    import secrets

    import relate

    from faildex.locks import held

    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with held(_write_lock(out)):
        refuse_non_store(out)
        _recover(out)
        token = secrets.token_hex(8)
        work = out.parent / f".{out.name}.writing-{token}"
        old = out.parent / f".{out.name}.old-{token}"
        try:
            if _has_store(out):
                shutil.copytree(out, work)  # lock files included: they mark each folder's role
                _mark(work, out, token)
            db = relate.connect(str(work))  # a new store: Relate makes the folder first
            try:
                _mark(work, out, token)
                write(db)
            finally:
                db.close()
            if not _swap(work, out, old, token):
                return False
            if after is not None:
                after(out)
            return True
        finally:
            if _is_ours(work, out, token):
                shutil.rmtree(work, ignore_errors=True)


class NotAStore(Exception):
    """The folder named as a store holds other files and no store."""


def refuse_non_store(path: Path) -> None:
    """Raise NotAStore when `path` is a file, or a folder with files but no store: a swap
    would set those files aside and delete them. A missing or empty folder is fine."""
    path = Path(path)
    if not path.exists() or _has_store(path):
        return
    if not path.is_dir() or any(path.iterdir()):
        raise NotAStore(path)


def _has_store(path: Path) -> bool:
    return (path / "manifest.json").is_file()


def _valid_store(path: Path) -> bool:
    """A store whose manifest reads as a JSON object."""
    import json

    try:
        return isinstance(json.loads((path / "manifest.json").read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def looks_like_store(path: Path) -> bool:
    """Whether `path` holds a Relate store: a `manifest.json` that reads as Relate's
    (an object with a whole `format_version` and lists `node_parts` and `rel_parts`)
    and the `nodes/` and `relationships/` folders. A folder that only happens to be
    called `store` and to hold some other `manifest.json` (a web app's) is not one.
    """
    import json

    try:
        manifest = json.loads((Path(path) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(manifest, dict)
        and isinstance(manifest.get("format_version"), int)
        and isinstance(manifest.get("node_parts"), list)
        and isinstance(manifest.get("rel_parts"), list)
        and (Path(path) / "nodes").is_dir()
        and (Path(path) / "relationships").is_dir()
    )


def _mark(folder: Path, out: Path, token: str) -> None:
    import json
    import time

    mark = {"pid": os.getpid(), "store": str(out), "token": token, "time": time.time()}
    (folder / SWAP_MARK).write_text(json.dumps(mark), encoding="utf-8")


def _unmark(folder: Path) -> None:
    try:
        (folder / SWAP_MARK).unlink()
    except FileNotFoundError:
        pass


def _mark_of(folder: Path) -> dict | None:
    import json

    try:
        mark = json.loads((folder / SWAP_MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return mark if isinstance(mark, dict) else None


def _is_ours(folder: Path, out: Path, token: str) -> bool:
    """Whether `folder` is the work folder or set-aside store this writer made for `out`."""
    mark = _mark_of(folder)
    return (
        folder.is_dir()
        and mark is not None
        and mark.get("store") == str(out)
        and mark.get("token") == token
        and folder.name.endswith(f"-{token}")
    )


def _set_aside(out: Path) -> list[Path]:
    """Stores a swap set aside for `out` and never put back, newest first.

    The folder is listed and names compared as plain text (a store may be called
    `s[12]`, which a glob would read as a pattern), and each one must say inside that
    it was set aside from this very store.
    """
    prefix = f".{out.name}.old-"
    found = []
    for entry in os.scandir(out.parent):
        if not entry.name.startswith(prefix):
            continue
        folder = Path(entry.path)
        mark = _mark_of(folder)
        if (
            mark is not None
            and mark.get("store") == str(out)
            and folder.name == prefix + str(mark.get("token"))
            and _has_store(folder)
        ):
            found.append((mark.get("time", 0), folder))
    return [folder for _, folder in sorted(found, key=lambda pair: pair[0], reverse=True)]


class RecoveryFailed(Exception):
    """A store set aside by an interrupted swap could not be put back."""


def _recover(out: Path) -> None:
    """Put back a store that an interrupted swap set aside. Deletes no data.

    Runs under the write lock. When `out` holds no store, the newest store set aside
    from it takes its place again. An empty folder left in its place is removed first
    (Windows will not rename onto one), and only if it is truly empty. If the store
    cannot be put back, RecoveryFailed stops the writer: writing a new, empty store in
    its place would hide the history kept aside.
    """
    if _has_store(out):
        return
    aside = _set_aside(out)
    if not aside:
        return
    try:
        if out.is_dir() and not any(out.iterdir()):
            out.rmdir()
        aside[0].rename(out)
    except OSError as err:
        raise RecoveryFailed(aside[0]) from err
    _unmark(out)


def swapping(path: Path) -> Path | None:
    """The store set aside by a writer that is between the two renames of a swap of the
    store at `path`, or None when there is no such writer.

    Then its set-aside store `.<store>.old-<token>` and its new copy
    `.<store>.writing-<token>` both exist, each marked with this store's path and the
    same token, and the set-aside one still holds a readable `manifest.json`. (A writer
    killed right there leaves them so until the next ingest puts the store back.) Reads
    only; names are compared as text.
    """
    path = Path(path).resolve()
    try:
        names = {entry.name for entry in os.scandir(path.parent)}
    except OSError:
        return None
    old_prefix = f".{path.name}.old-"
    found = []
    for name in names:
        if not name.startswith(old_prefix):
            continue
        token = name[len(old_prefix) :]
        writing = f".{path.name}.writing-{token}"
        marks = [_mark_of(path.parent / folder) for folder in (name, writing)]
        if writing not in names or not all(
            mark is not None and mark.get("store") == str(path) and mark.get("token") == token
            for mark in marks
        ):
            continue
        try:
            (path.parent / name / "manifest.json").read_bytes()
        except OSError:
            continue  # nothing there to answer from: no evidence
        stamp = marks[0].get("time")
        found.append((stamp if isinstance(stamp, (int, float)) else 0, name))
    return path.parent / max(found)[1] if found else None


def _swap(work: Path, out: Path, old: Path, token: str) -> bool:
    import time

    if out.exists():
        _mark(out, out, token)  # from here on it is our set-aside store
        for attempt in range(SWAP_TRIES):
            try:
                out.rename(old)
                break
            except OSError:
                if attempt == SWAP_TRIES - 1:
                    _unmark(out)
                    return False
                time.sleep(SWAP_WAIT)
    # The copy keeps its mark through the rename, so that between the two renames both
    # marked folders show a swap is under way (`swapping`).
    try:
        work.rename(out)
    except OSError:
        if old.exists() and not out.exists():
            old.rename(out)  # put the old store back
            _unmark(out)
        return False
    _unmark(out)  # it is the store now
    # The new store is in place: only now, and only our own set-aside store, is deleted.
    if old.exists() and _valid_store(out) and _is_ours(old, out, token):
        shutil.rmtree(old, ignore_errors=True)
    return True


def _shipped_store() -> Path | None:
    """The public store that came with this copy of faildex, wherever it is installed.

    A wheel carries it as package data (`faildex/_store`); a checkout or an editable
    install finds the repository's `store/` next to `src/`.
    """
    for candidate in (_HERE / "_store", _HERE.parents[1] / "store"):
        if (candidate / "manifest.json").is_file():
            return candidate
    return None


def _public_cache(shipped: Path) -> Path:
    """Where `public_store` keeps its copy of the shipped store."""
    digest = hashlib.sha256((shipped / "manifest.json").read_bytes()).hexdigest()[:12]
    return (
        Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser()
        / "faildex"
        / f"store-{digest}"
    )


def is_public(path: Path) -> bool:
    """Whether `path` is the shipped public store or the cache copy of it."""
    shipped = _shipped_store()
    if shipped is None:
        return False
    path = Path(path).resolve()
    return path in (shipped.resolve(), _public_cache(shipped).resolve())


def public_store() -> Path:
    """A ready-to-open copy of the public demo store.

    The shipped files are copied once into a cache folder named after their
    manifest, so opening never writes inside the installed package.
    """
    shipped = _shipped_store()
    if shipped is None:
        from faildex.i18n import t

        raise FileNotFoundError(t("err.no_public_store"))
    cache = _public_cache(shipped)
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


def hook_store() -> Path:
    """`default_store` for the hook, which must neither write nor fail.

    The same order, with two differences. `./store` and the private store count as
    there while an ingest is between the two renames of a swap (`swapping`), when the
    manifest is gone for an instant; a store that was deleted does not count, index or
    not. And
    the public store is never copied into the cache here: the cache copy if one exists,
    else the shipped store itself, which the hook reads through an index if one exists
    (and otherwise as `hook._open_source` says). Paths are resolved, so a symlinked store and its index agree.
    """
    named = os.environ.get("FAILDEX_STORE")
    if named:
        return Path(named).expanduser()
    private = PRIVATE_STORE.expanduser().resolve()
    local = Path("store")
    if (local / "manifest.json").is_file() or swapping(local):
        # Run from inside ~/.faildex, ./store is the private store: name it so.
        return private if local.resolve() == private else local
    if (private / "manifest.json").is_file() or swapping(private):
        return private
    shipped = _shipped_store()
    if shipped is None:
        return private
    cache = _public_cache(shipped)
    return cache if (cache / "manifest.json").is_file() else shipped
