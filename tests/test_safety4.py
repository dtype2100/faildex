"""Regression tests for the two issues found when the PM checked the branch for merging
(2026-11-27).

A  On Windows the refresh log's lines overwrote each other: the child ingest wrote at
   the position of the handle it was given, over the hook's `start` line.
B  In a fresh clone the hook said nothing on its first call: the public store had
   never been opened, so a read-only open failed, where `main` warned at once.

None of these depend on the state of the repository's `store/`.
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from payloads import git_status

from faildex import refresh, store
from faildex.hook import quiet, respond

ROOT = Path(__file__).resolve().parents[1]

# A ---------------------------------------------------------------------------------------


def test_a_lines_of_the_hook_and_of_its_child_never_overwrite_each_other(tmp_path):
    log = tmp_path / "s-refresh.log"
    n = 200
    child = (
        "import time\n"
        f"for i in range({n}):\n"
        "    print(f'child {i}', flush=True)\n"
        "    time.sleep(0.002)\n"
    )
    refresh.spawn([sys.executable, "-c", child], log)
    for i in range(n):
        refresh._log(log, f"parent {i}")
        time.sleep(0.002)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        lines = log.read_text(encoding="utf-8").splitlines()
        if f"child {n - 1}" in lines:
            break
        time.sleep(0.1)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert sorted(x for x in lines if x.startswith("child ")) == sorted(
        f"child {i}" for i in range(n)
    )
    assert sorted(x.split(" ", 1)[1] for x in lines if " parent " in x) == sorted(
        f"parent {i}" for i in range(n)
    )
    assert len(lines) == 2 * n  # nothing half-written, nothing merged


# B ---------------------------------------------------------------------------------------


def _fresh_clone_store(folder: Path) -> Path:
    """The store as `git clone` gives it: only its committed parts, never opened. (The
    parts, not `git ls-files`, so that a copy without `.git` runs this too.)"""
    folder.mkdir(parents=True)
    for part in store.STORE_PARTS:
        src = ROOT / "store" / part
        if src.is_dir():
            shutil.copytree(src, folder / part)
        elif src.is_file():
            shutil.copy2(src, folder / part)
    return folder


def _files(folder: Path) -> dict:
    return {p.relative_to(folder): p.stat().st_size for p in folder.rglob("*")}


# The hook speaks only to Claude Code, right after a failure (git status outside a
# repository: a failure the public demo store has seen in many sessions).
PAYLOADS = {"claude": json.loads(git_status())}


@pytest.fixture
def shipped(tmp_path, monkeypatch):
    """A fresh clone's store as the public store this faildex ships, with an empty cache."""
    clone = _fresh_clone_store(tmp_path / "clone" / "store")
    monkeypatch.setattr(store, "_shipped_store", lambda: clone)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return clone


@pytest.mark.parametrize("agent", sorted(PAYLOADS))
def test_b_a_fresh_clone_warns_on_the_first_call(shipped, agent):
    before = _files(shipped)
    out = json.loads(respond(json.dumps(PAYLOADS[agent]), shipped, agent=agent))
    assert "git status" in out["hookSpecificOutput"]["additionalContext"]
    assert "faildex" in out["systemMessage"]
    assert _files(shipped) == before  # the shipped store itself is never written


def test_b_the_first_call_does_not_wait_for_a_busy_cache_copy(shipped):
    from faildex.locks import held

    cache = store.public_store()  # copied, not opened yet
    payload = json.dumps(PAYLOADS["claude"])
    with held(store._write_lock(cache)):  # someone else is preparing it
        started = time.monotonic()
        assert respond(payload, shipped) == ""
        assert time.monotonic() - started < 3
    assert "git status" in respond(payload, shipped)  # and once free, it answers


@pytest.mark.parametrize("agent", sorted(PAYLOADS))
def test_b_a_never_opened_store_that_is_not_public_is_prepared_and_warns(shipped, tmp_path, agent):
    """Since the 5th fix (as `main` does): prepared where it is, then read."""
    copied = _fresh_clone_store(tmp_path / "copied" / "store")  # e.g. from another machine
    shipped_before = _files(shipped)
    out = respond(json.dumps(PAYLOADS[agent]), copied, agent=agent)
    assert out != quiet(agent) and "git status" in out
    assert (copied / "wal").is_dir()  # its per-machine files, made in place
    assert _files(shipped) == shipped_before
