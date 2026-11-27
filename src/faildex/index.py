"""The hook's index: what the hook needs from a store after a failure, in one JSON file.

Opening a Relate store costs most of a hook call (about half a second on a large
private store), and a hook that opens the store can trip over an ingest writing
it. So `faildex ingest` writes, next to the store, `<store>-index.json` with the
same lookups the hook would run, and the hook reads that file instead.

The index holds data, never sentences: for each command template that has failed,
its run count and its failures (the fields `insight.Failure` is made of, with the
failed calls of each session, Counter order kept so ties break the same way). Every
failure is kept, whatever its session count, so any
`--min-sessions` gives the answer the store would. The hook builds its text from
it with the same functions as from the store.

The header names the store manifest's SHA-256. A store changes its manifest on
every write, so an index whose fingerprint differs is stale, and the hook falls
back to the store (read-only) and has the index rebuilt in the background. An
index for a store whose folder faildex should not write next to (the public demo
store, a checkout's `store/`) lives in the cache folder instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

# 2: each failure's sessions carry their failed-call counts and recoveries
# (`Failure.session_calls`, `Failure.session_fixes`), and
# the failures pooled for the warning before a command (gone) are no longer kept.
INDEX_VERSION = 2
# A failed background rebuild is not retried sooner than this.
REBUILD_PAUSE = 10 * 60


def fingerprint(store: Path) -> str | None:
    """SHA-256 of the store's manifest, or None when there is no store."""
    try:
        return hashlib.sha256((Path(store) / "manifest.json").read_bytes()).hexdigest()
    except OSError:
        return None


def beside(store: Path) -> Path:
    """Where `faildex ingest` writes the index of the store it wrote (symlinks resolved)."""
    store = Path(store).resolve()
    return store.parent / f"{store.name}-index.json"


def _cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "faildex" / "index"


def cached(store: Path) -> Path:
    """Where the hook has the index of any other store rebuilt."""
    key = hashlib.sha256(str(Path(store).resolve()).encode("utf-8")).hexdigest()[:16]
    return _cache_dir() / f"{key}.json"


def _encode(item) -> dict:
    return {
        "sig": item.sig,
        "kind": item.kind,
        "calls": item.calls,
        "sessions": sorted(
            ([session, item.session_calls[session]] for session in item.sessions),
            key=lambda pair: str(pair[0]),
        ),
        "agents": sorted(item.agents, key=str),
        "commands": list(item.commands.items()),
        "tools": list(item.tools.items()),
        "fixes": list(item.fixes.items()),
        "recovered": item.recovered,
        "evidence": item.evidence,
        "session_fixes": sorted(
            (
                [session, fix, n]
                for session, fixes in item.session_fixes.items()
                for fix, n in fixes.items()
            ),
            key=lambda row: (str(row[0]), str(row[1])),
        ),
    }


def _pairs(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(pair, list) and len(pair) == 2 and type(pair[1]) is int for pair in value
    )


def _decode(row: dict):
    """One failure back from the file; ValueError when the entry is not what `build` wrote."""
    from faildex.insight import Failure

    if not (
        isinstance(row, dict)
        and isinstance(row.get("sig"), str)
        and isinstance(row.get("kind"), str)
        and type(row.get("calls")) is int
        and type(row.get("recovered")) is int
        and isinstance(row.get("agents"), list)
        and all(_pairs(row.get(key)) for key in ("sessions", "commands", "tools", "fixes"))
        and all(isinstance(session, str) for session, _ in row["sessions"])
        and isinstance(row.get("session_fixes"), list)
        and all(
            isinstance(entry, list) and len(entry) == 3 and type(entry[2]) is int
            for entry in row["session_fixes"]
        )
        and (row["commands"] or row["tools"])  # the rule names one of them
        and isinstance(row.get("evidence"), list)
        and all(isinstance(pointer, str) for pointer in row["evidence"])
    ):
        raise ValueError("damaged index entry")
    return Failure(
        sig=row["sig"],
        kind=row["kind"],
        calls=row["calls"],
        sessions={session for session, _ in row["sessions"]},
        agents=set(row["agents"]),
        commands=Counter(dict(row["commands"])),
        tools=Counter(dict(row["tools"])),
        fixes=Counter(dict(row["fixes"])),
        recovered=row["recovered"],
        evidence=list(row["evidence"]),
        session_calls=Counter(dict(row["sessions"])),
        session_fixes=_session_fixes(row["session_fixes"]),
    )


def _session_fixes(rows: list) -> dict:
    out: dict = {}
    for session, fix, n in rows:
        out.setdefault(session, Counter())[fix] = n
    return out


_FAILED_COMMANDS = """
MATCH (k:Command)<-[:RAN]-(:Call)-[:FAILED_WITH]->(:ErrorSig)
RETURN DISTINCT k.template AS template
"""


def build(db) -> dict:
    """The index body for the store `db` is connected to, from the hook's own queries."""
    from faildex.insight import failures, runs_of

    commands = {}
    for row in db.execute(_FAILED_COMMANDS):
        template = row["template"]
        commands[template] = {
            "runs": runs_of(db, template),
            "failures": [_encode(item) for item in failures(db, template).values()],
        }
    return {"commands": dict(sorted(commands.items()))}


def write(path: Path, store_fingerprint: str, body: dict) -> None:
    """Write the index so that a reader sees the old file or the new one, never half of one."""
    from datetime import datetime, timezone

    from faildex import __version__

    data = {
        "version": INDEX_VERSION,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "faildex": __version__,
        "manifest_sha256": store_fingerprint,
        **body,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _replace(tmp: str, path: Path, tries: int = 20) -> None:
    """os.replace, retried briefly: on Windows it fails while a hook has the index open."""
    import time

    for attempt in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05)


class Index:
    """A loaded index: one command's failures, as `insight.failures` gives them."""

    def __init__(self, data: dict):
        self._commands = data["commands"]

    def command_failures(self, template: str) -> tuple[int, list]:
        if template not in self._commands:
            return 0, []
        entry = self._commands[template]
        if not (
            isinstance(entry, dict)
            and type(entry.get("runs")) is int
            and isinstance(entry.get("failures"), list)
        ):
            raise ValueError("damaged index entry")
        return entry["runs"], [_decode(row) for row in entry["failures"]]


def candidates(store: Path) -> list[Index]:
    """The index the hook may answer from, as a list of at most one: the first that
    qualifies, the one next to the store before the cached one; never raising.

    An index qualifies when its format is right and its fingerprint is the store's
    manifest. While the manifest is missing because an ingest is between the two
    renames of a swap (`store.swapping`), the fingerprint must be that of the store
    just set aside, so an index of an older generation is never taken for it. A store
    that is simply gone has no index.
    """
    want = fingerprint(store)
    if want is None:
        from faildex.store import swapping

        aside = swapping(store)
        want = fingerprint(aside) if aside else None
        if want is None:
            return []  # not mid-swap: the store is gone, and so is what its index said
    found = []
    for path in (beside(store), cached(store)):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(data, dict)
            and data.get("version") == INDEX_VERSION
            and isinstance(data.get("manifest_sha256"), str)
            and isinstance(data.get("commands"), dict)
            and data["manifest_sha256"] == want
        ):
            found.append(Index(data))
            break  # the first that matches is the answer; the other file is not read
    return found


def load(store: Path) -> Index | None:
    """The best index of `store` (see `candidates`), or None."""
    found = candidates(store)
    return found[0] if found else None


# A rebuild lock older than this belongs to a rebuild that died; a live one takes seconds.
REBUILD_STALE = 10 * 60


def _rebuild_files(store: Path) -> tuple[Path, Path, Path]:
    """(lock, guard, tried) of the cached index of `store`."""
    target = cached(store)
    return target.with_suffix(".lock"), target.with_suffix(".guard"), target.with_suffix(".tried")


def _lock_token(lock: Path) -> tuple[str | None, float]:
    try:
        token, since = lock.read_text(encoding="utf-8").split()
        return token, float(since)
    except (OSError, ValueError):
        return None, 0.0


def rebuild(store: Path, token: str | None = None) -> int:
    """Write the cached index of `store` (run in the background by a hook that found none).

    The index is keyed to the store as the hook named it, so the hook finds it next
    time. The store is read as the hook reads it (`hook._open_source`): read-only, and
    a store never opened on this machine is first prepared, here waiting for the write
    lock: faildex's own public demo store through its cache copy (then the data comes
    from that copy, and the index is keyed to the store and to the copy, each with its
    own fingerprint), any other folder that looks like a Relate store where it is, and
    anything else not at all.

    `token` is the one the starting hook wrote into the lock; the lock is removed, under
    the guard, only if it still holds that token.
    """
    from faildex.hook import _open_read_only, _to_prepare
    from faildex.store import open_store

    store = Path(store)
    try:
        # Fingerprints first, then the open: a swap in between shows up in the check below.
        before = {store: fingerprint(store)}
        try:
            db = _open_read_only(store)
        except Exception:
            source = _to_prepare(store)
            if source is None:
                raise
            before[source] = fingerprint(source)
            db = open_store(source)
        try:
            body = build(db)
        finally:
            db.close()
        if None in before.values() or any(fingerprint(k) != v for k, v in before.items()):
            return 1  # a store moved meanwhile: the next hook tries again
        for key, value in before.items():
            write(cached(key), value, body)
        return 0
    finally:
        if token:
            from faildex.locks import held

            lock, guard, _ = _rebuild_files(store)
            with held(guard):
                if _lock_token(lock)[0] == token:
                    lock.unlink()


def start_rebuild(store: Path) -> None:
    """Have the cached index rebuilt by a detached process, at most one at a time and not
    again within REBUILD_PAUSE of the last try. Never raises.

    As in a refresh, checking, breaking and taking the lock happen under a guard. The
    hook writes its own random token into the lock before it starts the rebuild and
    hands the token over; only that rebuild removes the lock. No pid is involved.
    """
    import secrets
    import time

    try:
        from faildex import refresh
        from faildex.locks import held

        store = Path(store).resolve()
        lock, guard, tried = _rebuild_files(store)
        lock.parent.mkdir(parents=True, exist_ok=True)
        if time.time() - refresh._mtime(tried) < REBUILD_PAUSE:
            return
        with held(guard, wait=False) as got:
            if not got:
                return  # another hook is starting it right now
            now = time.time()
            if now - refresh._mtime(tried) < REBUILD_PAUSE:
                return  # another hook started one since the check above
            if lock.exists():
                if now - _lock_token(lock)[1] < REBUILD_STALE:
                    return
                lock.unlink()
            token = secrets.token_hex(8)
            lock.write_text(f"{token} {now:.0f}\n", encoding="utf-8")
            tried.write_text("", encoding="utf-8")
            try:
                refresh.spawn(
                    [
                        *refresh.faildex_command(),
                        "hook",
                        "--store",
                        str(store),
                        "--write-index",
                        token,
                    ],
                    cached(store).with_suffix(".log"),
                )
            except BaseException:
                lock.unlink()
                raise
    except Exception:  # noqa: BLE001, S110 - the hook has answered; a rebuild is a bonus
        pass
