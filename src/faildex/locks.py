"""An exclusive lock between processes, on macOS, Linux and Windows.

The operating system drops the lock when its holder exits, however it exits, so a
crashed writer never leaves a lock behind for someone to judge stale.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def held(path: Path, wait: bool = True) -> Iterator[bool]:
    """Hold the lock on `path` (created if missing) for the `with` block.

    Yields True while held. With `wait=False` it yields False at once when another
    process holds it, and the block should then do nothing.
    """
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        got = _lock(fd, wait)
        try:
            yield got
        finally:
            if got:
                _unlock(fd)
    finally:
        os.close(fd)


def _lock(fd: int, wait: bool) -> bool:
    if os.name == "nt":
        import msvcrt

        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                if not wait:
                    return False
                # LK_LOCK gives up after about ten seconds; keep waiting.
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)
