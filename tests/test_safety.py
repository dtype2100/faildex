"""Regression tests for the Codex review of the hook index (2026-11-27).

One test (or a few) per finding, each making the reviewer's failing condition happen
on purpose, plus the test gaps the review named. Findings: P0-1 first writable open vs
a swap, P0-2 store names read as glob patterns, P1-3 index published with another
generation's fingerprint, P1-4 the instant a swap has the store set aside, P1-5 a
damaged index entry, P1-6 calls erased by the counter reset, P1-7 the hook raising or
writing the public store copy.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from faildex import hook, index, refresh
from faildex.build import counts
from faildex.cli import main
from faildex.store import STORE_PARTS, open_store

REAL_START_REBUILD = index.start_rebuild  # before conftest stubs it for each test
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = str(FIXTURES / "claude_code")
CODEX = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
ENTRY = "from faildex.cli import main; raise SystemExit(main())"


def _bash(line: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": line}})


def _fresh_copy(dest: Path) -> Path:
    """The committed files of the public store only, as in a fresh clone."""
    dest.mkdir(parents=True)
    for part in STORE_PARTS:
        src = ROOT / "store" / part
        if src.is_dir():
            shutil.copytree(src, dest / part)
        elif src.is_file():
            shutil.copy2(src, dest / part)
    return dest


def _ingest(store: Path, *sources: str) -> None:
    argv = ["ingest", "--store", str(store)]
    for source in sources:
        argv += ["--codex" if source.endswith(".jsonl") else "--claude", source]
    assert main(argv) == 0


def _mark_as(folder: Path, store: Path, token: str) -> None:
    """The mark a writer leaves inside its set-aside store, written out by hand."""
    mark = {"pid": 1, "store": str(store.resolve()), "token": token, "time": time.time()}
    (folder / ".faildex-swap.json").write_text(json.dumps(mark), encoding="utf-8")


def _mid_swap(store: Path, token: str = "5ca1ab1e5ca1ab1e") -> None:
    """The state between the two renames of a swap: the old store set aside and the new
    copy not yet in place, both marked with this store and one token."""
    aside = store.parent / f".{store.name}.old-{token}"
    store.rename(aside)
    _mark_as(aside, store.parent / store.name, token)
    work = store.parent / f".{store.name}.writing-{token}"
    shutil.copytree(aside, work)
    _mark_as(work, store.parent / store.name, token)


def _git_push_logs(folder: Path) -> Path:
    """Two sessions where `git push` fails the same way, so the hook warns before it."""
    from test_index import _claude_session

    folder.mkdir(parents=True, exist_ok=True)
    for session in ("sess-p-a", "sess-p-b"):
        _claude_session(
            folder / f"{session}.jsonl",
            session,
            [("git push", "fatal: the current branch has no upstream branch"), ("ls", None)],
        )
    return folder


# P0-1 ----------------------------------------------------------------------------------


def test_p0_1_the_first_writable_open_always_holds_the_write_lock(tmp_path, monkeypatch):
    """Even with no lock file yet: the reviewer's race starts exactly there."""
    import relate

    from faildex.locks import held

    store = _fresh_copy(tmp_path / "s")
    lock = tmp_path / ".s.write-lock"
    assert not lock.exists()
    real = relate.connect
    seen = []

    def connect(path, *args, **kwargs):
        if not kwargs.get("read_only"):
            with held(lock, wait=False) as free:
                seen.append(not free)  # True: someone (the opener) holds the lock
        return real(path, *args, **kwargs)

    monkeypatch.setattr(relate, "connect", connect)
    open_store(store).close()
    assert seen == [True]


def test_p0_1_a_first_open_during_a_swap_waits_and_creates_nothing_where_the_store_went(
    tmp_path,
):
    """A writer holds the lock and moves the store aside; the first open of a fresh copy
    must wait for it, and must not create an empty store at the vacated path."""
    from faildex.locks import held

    store = _fresh_copy(tmp_path / "s")
    lock = tmp_path / ".s.write-lock"
    outcome = {}

    def reader():
        try:
            open_store(store).close()
            outcome["result"] = "opened"
        except Exception as err:  # noqa: BLE001 - recorded for the assertions
            outcome["result"] = type(err).__name__

    with held(lock):
        thread = threading.Thread(target=reader)
        thread.start()
        thread.join(0.5)
        assert thread.is_alive(), "the first open did not wait for the writer"
        store.rename(tmp_path / ".s.old-aside")  # the writer's first rename
    thread.join(10)
    assert outcome["result"] == "OperationalError"
    assert not store.exists()  # no empty store was created in its place


# P0-2 ----------------------------------------------------------------------------------


def test_p0_2_a_store_named_like_a_glob_touches_no_other_folder(tmp_path):
    store = tmp_path / "s[12]"
    other = tmp_path / ".s1.old-backup"
    other.mkdir()
    (other / "keep.txt").write_text("someone else's")
    _ingest(store, CLAUDE)
    _ingest(store, CODEX)
    assert (other / "keep.txt").read_text() == "someone else's"


def test_p0_2_another_stores_set_aside_copy_is_never_taken_for_ours(tmp_path):
    """Store `a` and store `a.old-zz` live side by side; `.a.old-zz.old-<token>` belongs
    to the second even though its name starts with the first one's prefix."""
    _ingest(tmp_path / "a.old-zz", CLAUDE)
    theirs = tmp_path / ".a.old-zz.old-feedfacefeedface"
    shutil.copytree(tmp_path / "a.old-zz", theirs)
    _mark_as(theirs, tmp_path / "a.old-zz", "feedfacefeedface")
    _ingest(tmp_path / "a", CLAUDE)
    _ingest(tmp_path / "a", CODEX)
    assert (theirs / "manifest.json").is_file()


def test_p0_2_recovery_deletes_nothing_it_did_not_make(tmp_path):
    """A set-aside store of a killed writer, while a store is in place: kept, not deleted."""
    store = tmp_path / "s"
    _ingest(store, CLAUDE)
    leftover = tmp_path / ".s.old-0000000000000000"
    shutil.copytree(store, leftover)
    _mark_as(leftover, store, "0000000000000000")
    _ingest(store, CODEX)
    assert (leftover / "manifest.json").is_file()
    mine = [p.name for p in tmp_path.iterdir() if p.name.startswith((".s.old-", ".s.writing-"))]
    assert mine == [leftover.name]  # this writer removed its own folders, and only those


# P1-3 ----------------------------------------------------------------------------------


def _index_is_of_the_store(store: Path) -> None:
    data = json.loads(index.beside(store).read_text(encoding="utf-8"))
    assert data["manifest_sha256"] == index.fingerprint(store)
    db = open_store(store)
    try:
        body = index.build(db)
    finally:
        db.close()
    assert data["commands"] == json.loads(json.dumps(body["commands"]))
    assert data["pooled"] == json.loads(json.dumps(body["pooled"]))


def test_p1_3_an_ingest_in_between_cannot_pair_its_fingerprint_with_our_data(tmp_path, monkeypatch):
    """Ingest A has swapped its store in; ingest B runs before A reads the fingerprint.
    The index must still describe the store it names."""
    store = tmp_path / "s"
    _ingest(store, CLAUDE)
    real = index.fingerprint
    other = {}

    def fingerprint(path):
        if "proc" not in other:  # A, about to publish: B tries to run to the end now
            other["proc"] = subprocess.Popen(
                [sys.executable, "-c", ENTRY, "ingest", "--store", str(store), "--codex", CODEX]
            )
            try:
                other["proc"].wait(timeout=8)  # held off by A's write lock, if A holds it
            except subprocess.TimeoutExpired:
                pass
        return real(path)

    monkeypatch.setattr(index, "fingerprint", fingerprint)
    _ingest(store, str(FIXTURES / "zsh_glob"))
    monkeypatch.setattr(index, "fingerprint", real)
    assert other["proc"].wait(timeout=60) == 0
    _index_is_of_the_store(store)


def test_p1_3_two_concurrent_ingests_leave_an_index_of_the_final_store(tmp_path):
    store = tmp_path / "s"
    command = [sys.executable, "-c", ENTRY, "ingest", "--store", str(store)]
    procs = [
        subprocess.Popen([*command, "--claude", CLAUDE]),
        subprocess.Popen([*command, "--codex", CODEX]),
    ]
    assert [p.wait(timeout=120) for p in procs] == [0, 0]
    db = open_store(store)
    try:
        assert counts(db)["Call"] == 13
    finally:
        db.close()
    _index_is_of_the_store(store)


# P1-4 ----------------------------------------------------------------------------------


def test_p1_4_while_the_store_is_set_aside_the_hook_answers_from_its_index(tmp_path):
    store = tmp_path / "s"
    _ingest(store, str(_git_push_logs(tmp_path / "logs")))
    payload = _bash("git push")
    expected = hook.respond(payload, store)
    assert "git push" in expected
    _mid_swap(store)
    assert hook.respond(payload, store) == expected


def test_p1_4_mid_swap_the_hook_does_not_switch_to_the_public_store(
    tmp_path, monkeypatch, capsys, _isolated_home
):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)  # no ./store
    private = _isolated_home / ".faildex" / "store"
    _ingest(private, str(_git_push_logs(tmp_path / "logs")))
    capsys.readouterr()

    def run():
        monkeypatch.setattr(sys, "stdin", io.StringIO(_bash("git push")))
        assert main(["hook"]) == 0
        return capsys.readouterr().out

    expected = run()
    assert "git push" in expected
    _mid_swap(private)
    assert run() == expected


# P1-5 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "damage",
    [
        lambda data, t: data["commands"].__setitem__(t, {}),
        lambda data, t: data["commands"][t].__setitem__("runs", "many"),
        lambda data, t: data["commands"][t].__setitem__("failures", [{}]),
        lambda data, t: data["commands"][t]["failures"][0].__setitem__("calls", "2"),
        lambda data, t: data["commands"][t]["failures"][0].__setitem__("sessions", "abc"),
        lambda data, t: data["commands"][t]["failures"][0].__setitem__("fixes", [["x"]]),
        lambda data, t: data["commands"][t]["failures"][0].__setitem__("evidence", [1]),
        lambda data, t: data["commands"][t]["failures"].append(None),
    ],
)
def test_p1_5_a_damaged_entry_falls_back_to_the_store(tmp_path, damage, monkeypatch):
    store = tmp_path / "s"
    _ingest(store, str(_git_push_logs(tmp_path / "logs")))
    payload = _bash("git push")
    expected = hook.respond(payload, store)
    assert "git push" in expected
    path = index.beside(store)
    data = json.loads(path.read_text(encoding="utf-8"))
    damage(data, "git push")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert index.load(store) is not None  # the header still looks right
    opened = []
    real = hook._open_read_only
    monkeypatch.setattr(hook, "_open_read_only", lambda s: opened.append(s) or real(s))
    assert hook.respond(payload, store) == expected
    assert opened == [store]  # answered by the store itself, not by the damaged index


# P1-6 ----------------------------------------------------------------------------------


def test_p1_6_calls_made_while_a_refresh_starts_count_for_the_next_one(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    (store / "manifest.json").write_text("{}")
    state, _ = refresh.paths(store)
    started = []

    def spawn(store, log):
        started.append(store)
        refresh._count(state)  # another session's hook call lands right now
        return os.getpid()

    monkeypatch.setattr(refresh, "_spawn", spawn)
    refresh.note(store, 2)
    refresh.note(store, 2)
    assert len(started) == 1
    refresh._release(state, os.getpid())
    when = time.time() - refresh.COOLDOWN - 60
    os.utime(state / "started", (when, when))
    refresh.note(store, 2)  # with the call made during the start, that is two
    assert len(started) == 2


def test_p1_6_the_counter_is_only_ever_appended_to(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    (store / "manifest.json").write_text("{}")
    state, _ = refresh.paths(store)
    monkeypatch.setattr(refresh, "_spawn", lambda store, log: os.getpid())
    sizes = []
    for _ in range(7):
        refresh.note(store, 3)
        sizes.append((state / "count").stat().st_size)
    assert sizes == [1, 2, 3, 4, 5, 6, 7]


# P1-7 ----------------------------------------------------------------------------------


def _bare_hook(monkeypatch, capsys, argv=("hook",), payload=None):
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload or _bash("git status")))
    code = main(list(argv))
    return code, capsys.readouterr()


def test_p1_7_an_unwritable_cache_never_makes_the_hook_raise(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)  # no ./store and, in this home, no private store
    blocked = tmp_path / "cache-is-a-file"
    blocked.write_text("")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocked))
    for agent in ("claude", "cursor"):
        code, out = _bare_hook(monkeypatch, capsys, ("hook", "--agent", agent))
        assert (code, out.err) == (0, "")
        assert out.out == "" or isinstance(json.loads(out.out), dict)  # an answer or quiet
    assert blocked.is_file() and blocked.read_text() == ""  # nothing written there


def test_p1_7_choosing_the_store_does_not_copy_the_public_store(tmp_path, monkeypatch):
    from faildex.store import _shipped_store, hook_store

    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)  # no ./store and, in this home, no private store
    cache = tmp_path / "empty-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    assert hook_store() == _shipped_store()
    assert not cache.exists()


def _files(folder: Path) -> dict:
    return {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*")}


@pytest.mark.parametrize("found", ["an index", "a readable store, no index"])
def test_p1_7_with_an_index_or_a_readable_store_the_hook_writes_nothing(
    tmp_path, monkeypatch, capsys, found
):
    """Nothing in or next to the store. Without an index the hook starts a rebuild, which
    leaves its guard, its lock, its `.tried` mark and its log in the cache folder, as
    documented."""
    store = tmp_path / "s"
    _ingest(store, str(_git_push_logs(tmp_path / "logs")))
    if found != "an index":
        index.beside(store).unlink()
    cache = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setattr(index, "start_rebuild", REAL_START_REBUILD)
    monkeypatch.setattr(refresh, "spawn", lambda argv, log: refresh.open_append(log).close() or 1)
    before = {p: v for p, v in _files(tmp_path).items() if cache not in p.parents and p != cache}
    code, out = _bare_hook(monkeypatch, capsys, ("hook", "--store", str(store)), _bash("git push"))
    assert code == 0 and "git push" in out.out
    after = {p: v for p, v in _files(tmp_path).items() if cache not in p.parents and p != cache}
    assert after == before
    left = sorted(p.suffix for p in cache.rglob("*") if p.is_file()) if cache.exists() else []
    assert left == ([] if found == "an index" else [".guard", ".lock", ".log", ".tried"])


@pytest.mark.parametrize(
    ("agent", "event", "quiet"),
    [
        ("claude", "pre-shell", ""),
        ("cursor", "pre-shell", '{"permission": "allow"}'),
        ("cursor", "session-start", "{}"),
    ],
)
def test_p1_7_any_error_in_the_hook_gives_the_quiet_answer(
    tmp_path, monkeypatch, capsys, agent, event, quiet
):
    def broken(*args, **kwargs):
        raise RuntimeError("anything at all")

    monkeypatch.setattr(hook, "respond", broken)
    argv = ("hook", "--store", str(tmp_path), "--agent", agent, "--event", event)
    code, out = _bare_hook(monkeypatch, capsys, argv)
    assert (code, out.out.strip(), out.err) == (0, quiet, "")


# Gap: a second refresh start within the cooldown ------------------------------------


def test_a_caller_that_passed_the_first_cooldown_check_starts_nothing_once_another_did(
    tmp_path, monkeypatch
):
    """B finds the store due, then A starts a refresh before B takes the guard."""
    from faildex import locks

    store = tmp_path / "store"
    store.mkdir()
    (store / "manifest.json").write_text("{}")
    started = []
    monkeypatch.setattr(refresh, "_spawn", lambda store, log: started.append(store) or os.getpid())
    real = locks.held
    interleaved = []

    def held(path, wait=True):
        if Path(path).name == "guard" and not interleaved:
            interleaved.append(True)
            refresh._note(store.resolve(), 1)  # A, start to finish, before B's guard
        return real(path, wait)

    monkeypatch.setattr(locks, "held", held)
    refresh.note(store, 1)  # B
    assert len(started) == 1
