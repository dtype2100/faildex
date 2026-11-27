"""`faildex hook --refresh-every N`: when a hook call starts a background ingest, and
`faildex ingest` writing on a copy so readers keep the old store meanwhile."""

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from payloads import git_status

from faildex import refresh
from faildex import store as store_module
from faildex.build import counts
from faildex.cli import main
from faildex.store import open_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
GIT_STATUS = git_status()  # a failure the public demo store has seen


def _fake_store(tmp_path, age=0.0):
    """Only what the trigger looks at: a manifest with a chosen age."""
    store = tmp_path / "store"
    store.mkdir()
    manifest = store / "manifest.json"
    manifest.write_text("{}")
    when = time.time() - age
    os.utime(manifest, (when, when))
    return store


@pytest.fixture
def spawned(monkeypatch):
    """Record each refresh instead of starting one; the 'child' is this live process."""
    started = []

    def fake(store, log):
        started.append(store)
        return os.getpid()

    monkeypatch.setattr(refresh, "_spawn", fake)
    return started


def _finish(store):
    """What the background ingest does when it ends: free the lock."""
    state, _ = refresh.paths(store.resolve())
    refresh._release(state, os.getpid())


def _age(path, seconds):
    when = time.time() - seconds
    os.utime(path, (when, when))


def test_the_nth_call_starts_one_refresh(tmp_path, spawned):
    store = _fake_store(tmp_path)
    state, log = refresh.paths(store)
    for _ in range(4):
        refresh.note(store, 5)
    assert spawned == []
    refresh.note(store, 5)
    assert spawned == [store.resolve()]
    assert (state / "count").stat().st_size == 5  # kept: the counter is never erased
    assert refresh._since(state, 5) == 0  # none since the refresh started
    for _ in range(10):
        refresh.note(store, 5)
    assert spawned == [store.resolve()]
    assert "start pid=" in log.read_text() and "calls=5 reason=calls" in log.read_text()


def test_no_second_refresh_within_the_cooldown(tmp_path, spawned):
    store = _fake_store(tmp_path)
    state, _ = refresh.paths(store)
    for _ in range(3):
        refresh.note(store, 3)
    _finish(store)
    for _ in range(9):
        refresh.note(store, 3)
    assert len(spawned) == 1
    _age(state / "started", refresh.COOLDOWN + 60)
    refresh.note(store, 3)
    assert len(spawned) == 2


def test_a_store_older_than_a_day_refreshes_without_the_count(tmp_path, spawned):
    store = _fake_store(tmp_path, age=refresh.MAX_AGE - 3600)
    refresh.note(store, 1000)
    assert spawned == []
    _age(store / "manifest.json", refresh.MAX_AGE + 60)
    refresh.note(store, 1000)
    assert spawned == [store.resolve()]
    _, log = refresh.paths(store)
    assert "reason=age" in log.read_text()


def test_a_missing_store_counts_as_old(tmp_path, spawned):
    store = tmp_path / "not-yet"
    refresh.note(store, 1000)
    assert spawned == [store.resolve()]


def _dead_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


@pytest.mark.parametrize(
    ("content", "mtime_age", "broken"),
    [
        (lambda: f"{_dead_pid()} {time.time():.0f}", 0, True),  # holder gone
        (lambda: f"{os.getpid()} {time.time() - refresh.STALE_LOCK - 60:.0f}", 0, True),
        (lambda: f"{os.getpid()} {time.time():.0f}", 0, False),  # live and recent
        (lambda: "", 0, False),  # being written right now
        (lambda: "", refresh.UNREADABLE_LOCK + 60, True),
    ],
)
def test_a_stale_lock_is_broken_and_a_live_one_kept(tmp_path, spawned, content, mtime_age, broken):
    store = _fake_store(tmp_path)
    state, _ = refresh.paths(store)
    state.mkdir()
    lock = state / "lock"
    lock.write_text(content())
    _age(lock, mtime_age)
    refresh.note(store, 1)
    assert len(spawned) == (1 if broken else 0)


def _hook(argv, monkeypatch, capsys, payload=GIT_STATUS):
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["hook", *argv]) == 0
    return capsys.readouterr().out


def _public_copy(tmp_path, prepared):
    """A copy of the public store as faildex has used it: copied from the run's prepared
    cache copy (`public_copy`), so it reads without preparing anything."""
    store = tmp_path / "store"
    shutil.copytree(prepared, store)
    return store


def test_without_the_option_the_hook_is_unchanged(tmp_path, monkeypatch, capsys, public_copy):
    store = _public_copy(tmp_path, public_copy)
    out = _hook(["--store", str(store)], monkeypatch, capsys)
    assert "git status" in json.loads(out)["systemMessage"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["store"]


def test_an_unwritable_refresh_folder_still_gives_the_warning(
    tmp_path, monkeypatch, capsys, public_copy
):
    store = _public_copy(tmp_path, public_copy)
    plain = _hook(["--store", str(store)], monkeypatch, capsys)
    assert "git status" in plain  # a warning to compare, not two silences
    state, _ = refresh.paths(store)
    state.write_text("a file where the folder should be")
    assert _hook(["--store", str(store), "--refresh-every", "1"], monkeypatch, capsys) == plain


def test_a_refresh_that_cannot_start_still_gives_the_warning(
    tmp_path, monkeypatch, capsys, public_copy
):
    store = _public_copy(tmp_path, public_copy)
    plain = _hook(["--store", str(store)], monkeypatch, capsys)
    assert "git status" in plain  # a warning to compare, not two silences
    monkeypatch.setattr(refresh, "command", lambda store: [str(tmp_path / "no-such-program")])
    assert _hook(["--store", str(store), "--refresh-every", "1"], monkeypatch, capsys) == plain
    state, _ = refresh.paths(store)
    assert not (state / "lock").exists()  # freed, so a later call can try again


def test_a_failed_start_keeps_the_count_and_the_next_call_retries(tmp_path, monkeypatch):
    store = _fake_store(tmp_path)
    state, _ = refresh.paths(store)
    tries = []

    def broken(store, log):
        tries.append(store)
        raise OSError("cannot start")

    monkeypatch.setattr(refresh, "_spawn", broken)
    refresh.note(store, 2)
    refresh.note(store, 2)
    refresh.note(store, 2)
    assert len(tries) == 2
    assert (state / "count").stat().st_size == 3
    assert not (state / "started").exists()


def test_a_caller_that_finds_the_guard_taken_starts_nothing(tmp_path, spawned):
    from faildex.locks import held

    store = _fake_store(tmp_path)
    state, _ = refresh.paths(store)
    state.mkdir()
    with held(state / "guard"):
        refresh.note(store, 1)
    assert spawned == []
    refresh.note(store, 1)
    assert spawned == [store.resolve()]


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_a_store_behind_a_symlink_uses_one_set_of_paths(tmp_path, spawned, capsys):
    real = tmp_path / "real" / "store"
    alias = tmp_path / "alias"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(real)]) == 0
    alias.symlink_to(real, target_is_directory=True)
    refresh.note(alias, 1)
    assert spawned == [real.resolve()]
    assert refresh.paths(real.resolve())[0].is_dir()
    codex = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
    assert main(["ingest", "--codex", codex, "--store", str(alias)]) == 0
    assert alias.is_symlink() and "calls 13" in capsys.readouterr().out


def test_a_checkouts_store_is_never_refreshed(tmp_path, monkeypatch, capsys, spawned, public_copy):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)
    _public_copy(tmp_path, public_copy)  # ./store, as inside a checkout of faildex
    _hook(["--refresh-every", "1"], monkeypatch, capsys)
    assert spawned == []
    _hook(["--store", "store", "--refresh-every", "1"], monkeypatch, capsys)
    assert spawned == [(tmp_path / "store").resolve()]  # named on purpose


def test_without_a_store_the_private_one_is_refreshed(
    tmp_path, monkeypatch, capsys, spawned, _isolated_home
):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)  # no ./store here: the hook reads the public demo store
    _hook(["--refresh-every", "1"], monkeypatch, capsys)
    assert spawned == [(_isolated_home / ".faildex" / "store").resolve()]
    monkeypatch.setenv("FAILDEX_STORE", str(tmp_path / "mine"))
    _finish(spawned[0])
    _hook(["--refresh-every", "1"], monkeypatch, capsys)
    assert spawned[1] == (tmp_path / "mine").resolve()


def _left(folder):
    """What a writer leaves in the store's folder, apart from its lock file."""
    return sorted(p.name for p in folder.iterdir() if not p.name.endswith(".write-lock"))


def test_ingest_keeps_what_the_store_had(tmp_path, capsys):
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    codex = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
    assert main(["ingest", "--codex", codex, "--store", str(store)]) == 0
    assert "calls 13" in capsys.readouterr().out
    assert _left(tmp_path) == ["s", "s-index.json"]  # no work folders left


def test_a_store_that_cannot_be_swapped_is_kept(tmp_path, capsys, monkeypatch):
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    capsys.readouterr()
    real = Path.rename

    def busy(self, target):
        if self == store:
            raise PermissionError("in use")  # what Windows says while a reader has it open
        return real(self, target)

    monkeypatch.setattr(Path, "rename", busy)
    monkeypatch.setattr(store_module, "SWAP_WAIT", 0)
    codex = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
    assert main(["ingest", "--codex", codex, "--store", str(store)]) == 1
    assert "old store is kept" in capsys.readouterr().out
    db = open_store(store)
    try:
        assert counts(db)["Call"] == 6
    finally:
        db.close()
    assert _left(tmp_path) == ["s", "s-index.json"]  # the first ingest's index


def test_a_refresh_logs_its_end_and_frees_the_lock(tmp_path, capsys):
    store = tmp_path / "s"
    state, log = refresh.paths(store)
    state.mkdir()
    (state / "lock").write_text(f"{os.getpid()} {time.time():.0f}\n")
    argv = ["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]
    assert main([*argv, "--refreshing"]) == 0
    assert "end exit=0 sessions=2 calls=6" in log.read_text()
    assert not (state / "lock").exists()


def test_concurrent_hooks_start_at_most_two_refreshes(tmp_path, _isolated_home):
    """2N real hook processes at once, then the real background ingest they start."""
    shutil.copytree(FIXTURES / "claude_code", _isolated_home / ".claude" / "projects")
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    every = 4
    hook = [sys.executable, "-c", refresh._ENTRY, "hook", "--store", str(store)]
    hooks = [
        subprocess.Popen(
            [*hook, "--refresh-every", str(every)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2 * every)
    ]
    for proc in hooks:
        _out, err = proc.communicate(GIT_STATUS.encode(), timeout=60)
        assert proc.returncode == 0 and not err
    state, log = refresh.paths(store)
    deadline = time.monotonic() + 90
    while (state / "lock").exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    time.sleep(0.5)  # the ingest exits right after freeing the lock
    text = log.read_text(encoding="utf-8")
    assert text.count(" start pid=") == 1  # one start within the cooldown, however many hooks
    if os.name == "nt" and "end exit=1" in text:
        # A hook still had the store open, so Windows refused the swap: old store kept.
        assert "old store is kept" in text
    else:
        assert "end exit=0 sessions=2 calls=6" in text
    db = open_store(store)
    try:
        assert counts(db)["Call"] == 6
    finally:
        db.close()


def test_writers_take_turns(tmp_path):
    """Two ingests of different logs at once: the store ends with both."""
    store = tmp_path / "s"
    ingest = [sys.executable, "-c", refresh._ENTRY, "ingest", "--store", str(store)]
    codex = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
    procs = [
        subprocess.Popen([*ingest, "--claude", str(FIXTURES / "claude_code")]),
        subprocess.Popen([*ingest, "--codex", codex]),
    ]
    assert [proc.wait(timeout=120) for proc in procs] == [0, 0]
    db = open_store(store)
    try:
        assert counts(db)["Call"] == 13
    finally:
        db.close()


def test_the_write_lock_is_held_while_the_copy_is_written(tmp_path):
    from faildex.locks import held

    store = tmp_path / "s"
    seen = []

    def write(db):
        with held(tmp_path / ".s.write-lock", wait=False) as got:
            seen.append(got)

    assert store_module.write_store(store, write)
    assert seen == [False]


def test_concurrent_counting_loses_no_call(tmp_path):
    """The counter is exact without a lock, Windows included (append-only handle there)."""
    code = (
        "import sys; from pathlib import Path; from faildex import refresh\n"
        "for _ in range(50): refresh._count(Path(sys.argv[1]))"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, str(tmp_path)]) for _ in range(8)]
    assert [proc.wait(timeout=60) for proc in procs] == [0] * 8
    assert (tmp_path / "count").stat().st_size == 400


def _killed_mid_swap(store, token="0123456789abcdef"):  # gitleaks:allow (test swap token)
    """What a writer killed between its two renames leaves: its marked set-aside store."""
    aside = store.parent / f".{store.name}.old-{token}"
    store.rename(aside)
    store_module._mark(aside, store.resolve(), token)
    return aside


def test_a_store_left_aside_by_a_killed_writer_is_put_back(tmp_path, capsys):
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    _killed_mid_swap(store)
    (tmp_path / ".s.writing-abc").mkdir()  # its copy, with no mark: not provably ours
    codex = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
    assert main(["ingest", "--codex", codex, "--store", str(store)]) == 0
    assert "calls 13" in capsys.readouterr().out  # the old store's calls are still there
    # Put back, not deleted; the unmarked folder is left as it was.
    assert _left(tmp_path) == [".s.writing-abc", "s", "s-index.json"]


def test_ingest_refuses_a_folder_that_is_not_a_store(tmp_path, capsys):
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    store.rename(tmp_path / ".s.old-12345")
    store.mkdir()
    (store / "note.txt").write_text("not a store")
    codex = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
    assert main(["ingest", "--codex", codex, "--store", str(store)]) == 1
    assert "no store in it" in capsys.readouterr().out
    assert (store / "note.txt").read_text() == "not a store"
    assert (tmp_path / ".s.old-12345" / "manifest.json").is_file()  # nothing deleted
    other = tmp_path / "file"
    other.write_text("x")
    assert main(["ingest", "--codex", codex, "--store", str(other)]) == 1
    assert other.read_text() == "x"
    with pytest.raises(store_module.NotAStore):
        store_module.write_store(store, lambda db: None)


def test_an_empty_folder_left_in_place_of_a_set_aside_store_is_replaced(tmp_path, capsys):
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    _killed_mid_swap(store)
    store.mkdir()
    codex = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
    assert main(["ingest", "--codex", codex, "--store", str(store)]) == 0
    assert "calls 13" in capsys.readouterr().out
