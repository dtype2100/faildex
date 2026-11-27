"""Regression tests for the third Codex review of the hook index (2026-11-27).

P1-1 an index of another generation trusted in a swap gap, P1-2 the default ./store
given up for another store in a swap gap, P2 the rebuild pause not checked again under
the guard.
"""

import contextlib
import json
import shutil
import time
from pathlib import Path

from faildex import hook, index, locks
from faildex.cli import main

ROOT = Path(__file__).resolve().parents[1]
REAL_START_REBUILD = index.start_rebuild
TOKEN = "5ca1ab1e5ca1ab1e"


def _bash(line: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": line}})


def _session(logs: Path, name: str) -> None:
    from test_index import _claude_session

    logs.mkdir(parents=True, exist_ok=True)
    _claude_session(
        logs / f"{name}.jsonl",
        name,
        [("git push", "fatal: the current branch has no upstream branch"), ("ls", None)],
    )


def _ingest(store: Path, logs: Path) -> None:
    assert main(["ingest", "--store", str(store), "--claude", str(logs)]) == 0


def _mark_as(folder: Path, store: Path, token: str) -> None:
    mark = {"pid": 1, "store": str(store.resolve()), "token": token, "time": time.time()}
    (folder / ".faildex-swap.json").write_text(json.dumps(mark), encoding="utf-8")


def _mid_swap(store: Path, token: str = TOKEN) -> Path:
    """Between the two renames of a swap: both marked folders, one token. Returns the
    store set aside."""
    target = store.resolve()
    aside = target.parent / f".{target.name}.old-{token}"
    target.rename(aside)
    _mark_as(aside, target, token)
    work = target.parent / f".{target.name}.writing-{token}"
    shutil.copytree(aside, work)
    _mark_as(work, target, token)
    return aside


def _two_generations(tmp_path: Path) -> tuple[Path, str]:
    """Store generation B (git push in two sessions: a warning) whose index beside it is
    still generation A's (git push in one session: silence), as when publishing B's index
    failed; B's own index is only in the cache."""
    store, logs = tmp_path / "s", tmp_path / "logs"
    _session(logs, "sess-a")
    _ingest(store, logs)
    generation_a = index.beside(store).read_text(encoding="utf-8")
    assert hook.respond(_bash("git push"), store) == ""
    _session(logs, "sess-b")
    _ingest(store, logs)
    index.write(index.cached(store), index.fingerprint(store), _body(store))
    index.beside(store).write_text(generation_a, encoding="utf-8")
    expected = hook.respond(_bash("git push"), store)
    assert "git push" in expected  # from the cached B index; A's is stale and skipped
    return store, expected


def _body(store: Path) -> dict:
    from faildex.hook import _open_read_only

    db = _open_read_only(store)
    try:
        return index.build(db)
    finally:
        db.close()


# P1-1 ----------------------------------------------------------------------------------


def test_p1_1_in_a_swap_gap_only_the_index_of_the_store_set_aside_is_used(tmp_path):
    store, expected = _two_generations(tmp_path)
    _mid_swap(store)
    assert hook.respond(_bash("git push"), store) == expected  # B's index, not A's


def test_p1_1_a_set_aside_folder_without_a_manifest_is_no_evidence(tmp_path):
    store, logs = tmp_path / "s", tmp_path / "logs"
    _session(logs, "sess-a")
    _session(logs, "sess-b")
    _ingest(store, logs)
    assert "git push" in hook.respond(_bash("git push"), store)
    aside = _mid_swap(store)
    (aside / "manifest.json").unlink()
    assert index.candidates(store) == []
    assert hook.respond(_bash("git push"), store) == ""


# P1-2 ----------------------------------------------------------------------------------


def _run_hook(monkeypatch, capsys, argv, payload):
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(argv) == 0
    return capsys.readouterr().out


def test_p1_2_the_default_local_store_in_a_swap_gap_is_still_the_one_used(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)  # ./store here, no private store in the home folder
    local = tmp_path / "store"
    _session(tmp_path / "logs", "sess-a")
    _session(tmp_path / "logs", "sess-b")
    _ingest(local, tmp_path / "logs")
    capsys.readouterr()
    expected = _run_hook(monkeypatch, capsys, ["hook"], _bash("git push"))
    assert "git push" in expected
    _mid_swap(local)
    assert _run_hook(monkeypatch, capsys, ["hook"], _bash("git push")) == expected


def test_p1_2_a_local_store_gone_without_evidence_still_falls_back(
    tmp_path, monkeypatch, capsys, public_copy
):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "store"
    _session(tmp_path / "logs", "sess-a")
    _session(tmp_path / "logs", "sess-b")
    _ingest(local, tmp_path / "logs")
    capsys.readouterr()
    public = _run_hook(
        monkeypatch, capsys, ["hook", "--store", str(public_copy)], _bash("git status")
    )
    assert "git status" in public  # the public store warns before `git status`
    assert _run_hook(monkeypatch, capsys, ["hook"], _bash("git status")) == ""  # ./store
    shutil.rmtree(local)
    assert _run_hook(monkeypatch, capsys, ["hook"], _bash("git status")) == public


# P2 ------------------------------------------------------------------------------------


def test_p2_a_rebuild_finished_while_waiting_for_the_guard_is_not_started_again(
    tmp_path, monkeypatch
):
    """Codex's order: hook B passes the time check; hook A starts the rebuild, which
    finishes and drops its lock; only then does B get the guard. One spawn, not two."""
    from faildex import refresh

    store = (tmp_path / "store").resolve()
    shutil.copytree(ROOT / "store", store)
    lock, guard, _ = index._rebuild_files(store)
    started = []

    def spawn(argv, log):
        started.append(argv)
        lock.unlink()  # the rebuild ran and removed its lock
        return 1

    monkeypatch.setattr(refresh, "spawn", spawn)
    real_held = locks.held
    a_first = [True]

    @contextlib.contextmanager
    def held(path, wait=True):
        if a_first and Path(path) == guard:
            a_first.clear()
            REAL_START_REBUILD(store)  # hook A, all the way through
        with real_held(path, wait) as got:
            yield got

    monkeypatch.setattr(locks, "held", held)
    REAL_START_REBUILD(store)  # hook B
    assert len(started) == 1
