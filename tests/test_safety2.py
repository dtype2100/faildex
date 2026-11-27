"""Regression tests for the final agy review of the hook index (2026-11-27, 2nd round).

P1-a an index trusted although its store was deleted, P1-b a rebuild that keyed the
index to the cache copy instead of the store the hook named, P2 the rebuild lock, entries
that only fail when put into words, Windows recovery over an empty folder, the console
note that reached stderr before the hook's guard, P3 symlinks and ~/.faildex as cwd.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import faildex
from faildex import hook, index
from faildex.cli import main
from faildex.store import STORE_PARTS, open_store

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
CODEX = str(FIXTURES / "codex" / "trajectories.sample.jsonl")
ENTRY = "from faildex.cli import main; raise SystemExit(main())"
REAL_START_REBUILD = index.start_rebuild


def _bash(line: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": line}})


def _mark_as(folder: Path, store: Path, token: str) -> None:
    mark = {"pid": 1, "store": str(store.resolve()), "token": token, "time": time.time()}
    (folder / ".faildex-swap.json").write_text(json.dumps(mark), encoding="utf-8")


def _mid_swap(store: Path, token: str = "5ca1ab1e5ca1ab1e") -> None:
    """Between the two renames of a swap: both marked folders, one token."""
    target = store.resolve()
    aside = target.parent / f".{target.name}.old-{token}"
    target.rename(aside)
    _mark_as(aside, target, token)
    work = target.parent / f".{target.name}.writing-{token}"
    shutil.copytree(aside, work)
    _mark_as(work, target, token)


def _git_push_store(store: Path, logs: Path) -> None:
    from test_index import _claude_session

    logs.mkdir(parents=True, exist_ok=True)
    for session in ("sess-p-a", "sess-p-b"):
        _claude_session(
            logs / f"{session}.jsonl",
            session,
            [("git push", "fatal: the current branch has no upstream branch"), ("ls", None)],
        )
    assert main(["ingest", "--store", str(store), "--claude", str(logs)]) == 0


def _run_hook(monkeypatch, capsys, argv, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(argv) == 0
    return capsys.readouterr().out


# P1-a ----------------------------------------------------------------------------------


def test_p1a_a_deleted_store_whose_index_remains_gives_no_warning(tmp_path):
    store = tmp_path / "s"
    _git_push_store(store, tmp_path / "logs")
    assert "git push" in hook.respond(_bash("git push"), store)
    shutil.rmtree(store)
    assert index.beside(store).is_file()  # its index is still there
    assert hook.respond(_bash("git push"), store) == ""


def test_p1a_a_real_swap_gap_still_warns_from_the_index(tmp_path):
    store = tmp_path / "s"
    _git_push_store(store, tmp_path / "logs")
    expected = hook.respond(_bash("git push"), store)
    _mid_swap(store)
    assert hook.respond(_bash("git push"), store) == expected


def test_p1a_half_the_evidence_is_not_a_swap(tmp_path):
    """A set-aside store alone (no marked copy beside it) is not a swap under way."""
    store = tmp_path / "s"
    _git_push_store(store, tmp_path / "logs")
    token = "0123456789abcdef"  # gitleaks:allow (test swap token)
    aside = tmp_path / f".s.old-{token}"
    store.rename(aside)
    _mark_as(aside, store, token)
    assert hook.respond(_bash("git push"), store) == ""


def test_p1a_a_deleted_private_store_sends_the_hook_back_to_the_public_one(
    tmp_path, monkeypatch, capsys, _isolated_home, public_copy
):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)  # no ./store here
    private = _isolated_home / ".faildex" / "store"
    _git_push_store(private, tmp_path / "logs")
    capsys.readouterr()
    public = _run_hook(
        monkeypatch, capsys, ["hook", "--store", str(public_copy)], _bash("git status")
    )
    assert "git status" in public  # the public store warns before `git status`
    assert _run_hook(monkeypatch, capsys, ["hook"], _bash("git status")) == ""  # private
    shutil.rmtree(private)
    assert _run_hook(monkeypatch, capsys, ["hook"], _bash("git status")) == public


# P1-b ----------------------------------------------------------------------------------


def _fresh_clone(root: Path) -> Path:
    """A checkout just cloned: the package being tested, and a store with only its
    committed files (no per-machine files, so a read-only open is refused)."""
    package = Path(faildex.__file__).resolve().parent
    shutil.copytree(package, root / "src" / "faildex", ignore=shutil.ignore_patterns("_store"))
    (root / "store").mkdir()
    for part in STORE_PARTS:
        src = ROOT / "store" / part
        if src.is_dir():
            shutil.copytree(src, root / "store" / part)
        elif src.is_file():
            shutil.copy2(src, root / "store" / part)
    return root


def _clone_hook(clone: Path, cwd: Path, home: Path, extra=(), probe: bool = False) -> str:
    """The hook's stdout, run as a fresh process; with `probe`, then a last line that says
    whether it loaded Relate (it does not on the index path)."""
    env = {
        **os.environ,
        "PYTHONPATH": str(clone / "src"),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CACHE_HOME": str(home / "cache"),
    }
    env.pop("FAILDEX_STORE", None)
    code = ENTRY
    if probe:
        code = (
            "import sys; from faildex.cli import main; main(sys.argv[1:]); "
            "print('RELATE' if 'relate' in sys.modules else 'NO-RELATE')"
        )
    done = subprocess.run(
        [sys.executable, "-c", code, "hook", *extra],
        input=_bash("git status"),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=True,
    )
    assert done.stderr == ""
    return done.stdout


@pytest.mark.parametrize("how", ["./store of a fresh clone", "--store <shipped store>"])
def test_p1b_after_one_fallback_the_next_hook_answers_from_the_rebuilt_index(tmp_path, how):
    """End to end, with the real background rebuild (no conftest stub in a subprocess)."""
    clone = _fresh_clone(tmp_path / "clone")
    home = tmp_path / "home"
    home.mkdir()
    if how.startswith("./store"):
        cwd, extra = clone, ()
    else:
        cwd, extra = tmp_path, ("--store", str(clone / "store"))
    # Unreadable as it is: the hook answers from the public store's cache copy (since the
    # 4th fix, as `main` did, from the first call), and a rebuild starts.
    first = _clone_hook(clone, cwd, home, extra)
    assert "git status" in first
    deadline = time.monotonic() + 90
    out = ""
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if any((home / "cache" / "faildex" / "index").glob("*.json")):
            out = _clone_hook(clone, cwd, home, extra)
            if out:
                break
    assert out == first
    # And that answer came from the index: the hook did not load Relate for it.
    probed = _clone_hook(clone, cwd, home, extra, probe=True)
    assert probed.rstrip().endswith("NO-RELATE") and probed.startswith(first.rstrip())


# P2: the rebuild lock -----------------------------------------------------------------


def test_p2_a_rebuild_started_by_the_hook_leaves_no_lock_behind(tmp_path, monkeypatch):
    """The child may finish before the parent would have written its pid: the lock it
    was handed is the one it removes, and nothing is written after it."""
    from faildex import refresh

    monkeypatch.setattr(index, "start_rebuild", REAL_START_REBUILD)
    store = tmp_path / "store"
    shutil.copytree(ROOT / "store", store)
    open_store(store).close()

    import threading

    children = []

    def child_runs_at_once(argv, log):
        # The detached `faildex hook ... --write-index`, as a thread; it is given every
        # chance to finish before the hook goes on, as a fast child would.
        child = threading.Thread(target=main, args=(argv[3:],))
        child.start()
        child.join(3)
        children.append(child)
        return os.getpid()

    monkeypatch.setattr(refresh, "spawn", child_runs_at_once)
    index.start_rebuild(store)
    for child in children:
        child.join(60)
    assert index.load(store) is not None
    lock = index.cached(store.resolve()).with_suffix(".lock")
    assert not lock.exists()


def test_p2_a_stale_rebuild_lock_is_broken_and_taken_under_the_guard(tmp_path, monkeypatch):
    from faildex import refresh
    from faildex.locks import held

    monkeypatch.setattr(index, "start_rebuild", REAL_START_REBUILD)
    store = (tmp_path / "store").resolve()
    shutil.copytree(ROOT / "store", store)
    open_store(store).close()  # a store faildex has opened, so the rebuild below can read it
    started = []
    monkeypatch.setattr(refresh, "spawn", lambda argv, log: started.append(argv) or 1)
    target = index.cached(store)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock, guard = target.with_suffix(".lock"), target.with_suffix(".guard")
    lock.write_text(f"oldtoken {time.time() - 3600:.0f}\n")
    with held(guard):  # another hook is in the middle of it
        index.start_rebuild(store)
    assert started == []
    index.start_rebuild(store)
    assert len(started) == 1
    token = lock.read_text().split()[0]
    assert token != "oldtoken" and started[0][-1] == token  # handed to the child
    index.rebuild(store, "someone-else")  # a rebuild with another token keeps it
    assert lock.read_text().split()[0] == token


# P2: entries that fail only when put into words -------------------------------------


@pytest.mark.parametrize(
    "damage",
    [
        lambda entry: [f.update(commands=[], tools=[]) for f in entry["failures"]],
        "null",
    ],
)
def test_p2_entries_without_a_name_or_null_fall_back_to_the_store(tmp_path, damage, monkeypatch):
    store = tmp_path / "s"
    _git_push_store(store, tmp_path / "logs")
    payload = _bash("git push")
    expected = hook.respond(payload, store)
    path = index.beside(store)
    data = json.loads(path.read_text(encoding="utf-8"))
    if damage == "null":
        data["commands"]["git push"] = None
    else:
        damage(data["commands"]["git push"])
    path.write_text(json.dumps(data), encoding="utf-8")
    opened = []
    real = hook._open_read_only
    monkeypatch.setattr(hook, "_open_read_only", lambda s: opened.append(s) or real(s))
    assert hook.respond(payload, store) == expected
    assert opened == [store]


def test_p2_a_failure_while_writing_the_warning_falls_back_to_the_store(tmp_path, monkeypatch):
    store = tmp_path / "s"
    _git_push_store(store, tmp_path / "logs")
    payload = _bash("git push")
    expected = hook.respond(payload, store)
    real = hook.notice_for
    calls = []

    def fails_once(found):
        calls.append(1)
        if len(calls) == 1:
            raise IndexError("an entry that cannot be put into words")
        return real(found)

    monkeypatch.setattr(hook, "notice_for", fails_once)
    assert hook.respond(payload, store) == expected


# P2: Windows recovery ------------------------------------------------------------------


def _windows_renames(monkeypatch, refuse=None):
    """Rename as Windows does: never onto an existing folder, even an empty one."""
    real_rename, real_replace, real_path_rename = os.rename, os.replace, Path.rename

    def check(src, dst):
        if Path(dst).exists() or (refuse and Path(src).name.startswith(refuse)):
            raise PermissionError(f"cannot rename {src} onto {dst}")

    def rename(src, dst, *a, **k):
        check(src, dst)
        return real_rename(src, dst, *a, **k)

    def replace(src, dst, *a, **k):
        check(src, dst)
        return real_replace(src, dst, *a, **k)

    def path_rename(self, target):
        check(self, target)
        return real_path_rename(self, target)

    monkeypatch.setattr(os, "rename", rename)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(Path, "rename", path_rename)


def _killed_with_empty_folder_left(store: Path) -> Path:
    token = "0123456789abcdef"  # gitleaks:allow (test swap token)
    aside = store.parent / f".{store.name}.old-{token}"
    store.rename(aside)
    _mark_as(aside, store, token)
    store.mkdir()
    return aside


def test_p2_windows_an_empty_folder_left_in_place_is_removed_and_the_store_put_back(
    tmp_path, monkeypatch, capsys
):
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    _killed_with_empty_folder_left(store)
    _windows_renames(monkeypatch)
    assert main(["ingest", "--codex", CODEX, "--store", str(store)]) == 0
    assert "calls 13" in capsys.readouterr().out  # the 6 set aside and the 7 new


def test_p2_a_store_that_cannot_be_put_back_stops_the_ingest(tmp_path, monkeypatch, capsys):
    store = tmp_path / "s"
    assert main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(store)]) == 0
    aside = _killed_with_empty_folder_left(store)
    capsys.readouterr()
    _windows_renames(monkeypatch, refuse=".s.old-")
    assert main(["ingest", "--codex", CODEX, "--store", str(store)]) == 1
    assert "could not be put back" in capsys.readouterr().out
    assert (aside / "manifest.json").is_file()
    assert not (store / "manifest.json").is_file()  # no new, empty store hides it


# P2: the console note -------------------------------------------------------------------


def test_p2_korean_on_an_ascii_console_puts_nothing_on_stderr(tmp_path, public_copy):
    home = tmp_path / "home"
    (home / ".faildex").mkdir(parents=True)
    (home / ".faildex" / "config.json").write_text(json.dumps({"lang": "ko"}))
    env = {
        **os.environ,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "PYTHONIOENCODING": "ascii",
    }
    env.pop("FAILDEX_LANG", None)
    done = subprocess.run(
        [sys.executable, "-c", ENTRY, "hook", "--store", str(public_copy)],
        input=_bash("git status"),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert (done.returncode, done.stderr) == (0, "")
    assert "git status" in done.stdout


# P3 ------------------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_p3_a_symlinked_private_store_mid_swap_is_still_the_private_store(
    tmp_path, monkeypatch, capsys, _isolated_home
):
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path)
    real = tmp_path / "elsewhere" / "store"
    _git_push_store(real, tmp_path / "logs")
    (_isolated_home / ".faildex").mkdir()
    (_isolated_home / ".faildex" / "store").symlink_to(real, target_is_directory=True)
    capsys.readouterr()
    expected = _run_hook(monkeypatch, capsys, ["hook"], _bash("git push"))
    assert "git push" in expected
    _mid_swap(real)
    assert _run_hook(monkeypatch, capsys, ["hook"], _bash("git push")) == expected


def test_p3_run_from_inside_dot_faildex_the_store_is_still_refreshed(
    tmp_path, monkeypatch, capsys, _isolated_home
):
    from faildex import refresh

    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    private = _isolated_home / ".faildex" / "store"
    _git_push_store(private, tmp_path / "logs")
    monkeypatch.chdir(private.parent)
    noted = []
    monkeypatch.setattr(refresh, "note", lambda store, every: noted.append(store))
    _run_hook(monkeypatch, capsys, ["hook", "--refresh-every", "1"], _bash("git push"))
    assert [Path(p).resolve() for p in noted] == [private.resolve()]
