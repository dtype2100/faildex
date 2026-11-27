"""Keep a private store current from the hook: `faildex hook --refresh-every N`.

The store only learns from new sessions when `faildex ingest` runs. With this
option, each hook call adds one byte to a counter file, and the call that finds
the store due starts `faildex ingest --store <the hook's store>` as a detached
background process and returns at once. The store is due when N hook calls have
gathered since the last refresh, or when it has not been written for MAX_AGE.
No refresh starts within COOLDOWN of the previous start, and only the caller
that takes the lock starts one.

The trigger counts calls rather than time because the store only falls behind
while agents are running commands: a quiet week needs no refresh, and a busy
afternoon needs several. The two clocks bound the cost. COOLDOWN keeps one
ingest (it re-reads every log, which takes a while on a long history) from being
followed by another while agents are busy; MAX_AGE picks up sessions run where
the hook was not called, once a day.

Everything lives next to the store: `<store>-refresh/` holds `count` (one byte
per hook call, appended and never erased: about 1 MB per million calls), `lock`
and `started` (when the last refresh started, and the counter's size then), and `<store>-refresh.log` gets one line when a refresh starts and
one when it ends. Any failure here is ignored, so the warning is still printed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

COOLDOWN = 30 * 60
MAX_AGE = 24 * 60 * 60
STALE_LOCK = 60 * 60
# A lock file without a readable pid yet is being written; give the writer this long.
UNREADABLE_LOCK = 10

# The faildex that is running now, whatever its launcher is called (`faildex.exe`,
# a uv tool shim, an editable checkout). There is no `faildex/__main__.py`.
_ENTRY = "from faildex.cli import main; raise SystemExit(main())"


def paths(store: Path) -> tuple[Path, Path]:
    """(state folder, log file) of the store at `store`."""
    store = Path(store)
    return store.parent / f"{store.name}-refresh", store.parent / f"{store.name}-refresh.log"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(log: Path, text: str) -> None:
    with log.open("a", encoding="utf-8") as out:
        out.write(f"{_stamp()} {text}\n")


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _count(state: Path) -> int:
    """Add this call to the counter and return the calls since the last refresh.

    An append-only write lands at the end even when several hooks write at once, so
    the size is the count without a lock. On Windows, O_APPEND is a seek and a write
    that two processes can interleave, so there the file is opened for appending only.
    """
    if os.name == "nt":
        return _count_windows(state / "count")
    fd = os.open(state / "count", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, b".")
        return os.fstat(fd).st_size
    finally:
        os.close(fd)


def _count_windows(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.WriteFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    kernel32.GetFileSizeEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    # FILE_APPEND_DATA without FILE_WRITE_DATA: every write goes to the end, atomically.
    access = 0x0004 | 0x0080  # FILE_APPEND_DATA | FILE_READ_ATTRIBUTES (for the size)
    share = 0x1 | 0x2 | 0x4  # read, write, delete
    handle = kernel32.CreateFileW(str(path), access, share, None, 4, 0x80, None)  # OPEN_ALWAYS
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        written = wintypes.DWORD()
        if not kernel32.WriteFile(handle, b".", 1, ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        size = ctypes.c_longlong()
        if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return size.value
    finally:
        kernel32.CloseHandle(handle)


def note(store: Path, every: int) -> None:
    """Count one hook call and start a refresh when the store is due. Never raises."""
    try:
        # One spelling for the hook and the ingest it starts, symlinks resolved.
        _note(Path(store).resolve(), every)
    except Exception:  # noqa: BLE001, S110 - a refresh problem must not touch the warning
        pass


def _since(state: Path, size: int) -> int:
    """Calls since the last refresh started: the counter's size now minus its size then.

    The counter is only ever appended to; `started` holds the time and the size the
    counter had when the last refresh started."""
    try:
        then = int((state / "started").read_text(encoding="utf-8").split()[1])
    except (OSError, ValueError, IndexError):
        then = 0
    return size - then if 0 <= then <= size else size


def _note(store: Path, every: int) -> None:
    state, log = paths(store)
    state.mkdir(parents=True, exist_ok=True)
    size = _count(state)
    calls = _since(state, size)
    now = time.time()
    if calls >= every:
        reason = "calls"
    elif now - _mtime(store / "manifest.json") > MAX_AGE:
        reason = "age"
    else:
        return
    if now - _mtime(state / "started") < COOLDOWN:
        return
    from faildex.locks import held

    # The guard makes checking, breaking and taking the lock one step: two callers
    # cannot both judge a lock stale and both take it. A busy guard means another
    # caller is starting a refresh right now.
    with held(state / "guard", wait=False) as got:
        if not got:
            return
        # Another caller may have started, finished and released while we checked.
        if time.time() - _mtime(state / "started") < COOLDOWN:
            return
        lock = state / "lock"
        if not _take(lock, now):
            return
        try:
            pid = _spawn(store, log)
        except BaseException:
            _drop(lock, os.getpid())  # nothing started: the next call tries again
            raise
        _write_lock(lock, pid)
        # Calls counted after the one that found the store due belong to the next
        # refresh, even those made while it was starting; nothing is erased.
        _write_started(state, size)
        _log(log, f"start pid={pid} calls={calls} reason={reason}")


def _write_started(state: Path, size: int) -> None:
    """Record a refresh start (time and counter size) so a reader sees all of it or none."""
    from faildex.index import _replace

    tmp = state / f".started.{os.getpid()}.tmp"
    tmp.write_text(f"{_stamp()} {size}\n", encoding="utf-8")
    _replace(str(tmp), state / "started")


def _write_lock(lock: Path, pid: int) -> None:
    lock.write_text(f"{pid} {time.time():.0f}\n", encoding="utf-8")


def _take(lock: Path, now: float) -> bool:
    """Create the lock file, breaking it first when its holder is gone or it is too old."""
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if not _stale(lock, now):
                return False
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
            continue
        try:
            os.write(fd, f"{os.getpid()} {now:.0f}\n".encode())
        finally:
            os.close(fd)
        return True
    return False


def _stale(lock: Path, now: float) -> bool:
    try:
        pid, since = lock.read_text(encoding="utf-8").split()
        pid, since = int(pid), float(since)
    except (OSError, ValueError):
        return now - _mtime(lock) > UNREADABLE_LOCK
    return now - since > STALE_LOCK or not _alive(pid)


def _release(state: Path, *pids: int) -> None:
    """Remove the lock if one of `pids` holds it, under the guard, so that a caller
    breaking a stale lock and taking it anew cannot lose its lock to us."""
    from faildex.locks import held

    with held(state / "guard"):
        for pid in pids:
            _drop(state / "lock", pid)


def _drop(lock: Path, pid: int) -> None:
    """Remove the lock if `pid` holds it. Only with the guard held."""
    try:
        if int(lock.read_text(encoding="utf-8").split()[0]) == pid:
            lock.unlink()
    except (OSError, ValueError, IndexError):
        pass


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def faildex_command() -> list[str]:
    """This same faildex, as a command line."""
    return [sys.executable, "-c", _ENTRY]


def command(store: Path) -> list[str]:
    """The ingest a refresh runs: this same faildex, into the hook's store."""
    return [*faildex_command(), "ingest", "--store", str(store), "--refreshing"]


def _spawn(store: Path, log: Path) -> int:
    return spawn(command(store.resolve()), log)


def spawn(argv: list[str], log: Path) -> int:
    """Start `argv` detached from this hook, output to `log`, so the hook can return now."""
    options: dict = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    with log.open("ab") as out:
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **options,
        )
    return child.pid


def run_logged(store: Path, ingest) -> int:
    """Run `ingest()` as a refresh: log its end with the store's totals, then free the lock."""
    state, log = paths(store)
    started = time.monotonic()
    code = 1
    try:
        code = ingest()
    finally:
        totals = "sessions=? calls=?"
        try:
            from faildex.build import counts
            from faildex.store import open_store

            db = open_store(store)
            try:
                found = counts(db)
            finally:
                db.close()
            totals = f"sessions={found['Session']} calls={found['Call']}"
        except Exception:  # noqa: BLE001, S110 - the end line is written either way
            pass
        try:
            _log(log, f"end exit={code} {totals} seconds={time.monotonic() - started:.0f}")
        finally:
            # The hook recorded the pid it started; on Windows a venv's python.exe is a
            # launcher whose child runs this, so the recorded pid is our parent's.
            _release(state, os.getpid(), os.getppid())
    return code
