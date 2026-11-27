"""Regression tests for the agy review of round 4 (2026-11-27), P1-1.

An installed faildex run inside a fresh clone said nothing, ever: the clone's ./store
is not the public store the package ships (`is_public` compares paths), so neither
the hook nor its background rebuild would open it. `main` prepared it where it was.
Now any never-opened store that looks like a faildex store is prepared where it is,
as `main` did, without waiting for a busy write lock, and never during a swap.
"""

import contextlib
import io
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from faildex import index, store
from faildex.cli import main
from faildex.hook import quiet, respond

ROOT = Path(__file__).resolve().parents[1]

PAYLOADS = {
    "claude": {"tool_name": "Bash", "tool_input": {"command": "git status"}},
    "codex": {"tool_name": "Bash", "tool_input": {"command": "git status"}},
    "cursor": {"command": "git status"},
}


def _parts(source: Path, folder: Path) -> Path:
    """Only the committed parts of a store (what a clone or a plain copy brings)."""
    folder.mkdir(parents=True)
    for part in store.STORE_PARTS:
        src = source / part
        if src.is_dir():
            shutil.copytree(src, folder / part)
        elif src.is_file():
            shutil.copy2(src, folder / part)
    return folder


def _files(folder: Path) -> dict:
    return {p.relative_to(folder): p.stat().st_size for p in folder.rglob("*")}


def _hook(monkeypatch, capsys, argv, payload) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert main(list(argv)) == 0
    out = capsys.readouterr()
    assert out.err == ""
    return out.out


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """An installed faildex (its public store in the package, never written) and a fresh
    clone of the repository as the current folder, with an empty cache."""
    package_store = _parts(ROOT / "store", tmp_path / "site-packages" / "faildex" / "_store")
    clone = tmp_path / "clone"
    _parts(ROOT / "store", clone / "store")
    monkeypatch.setattr(store, "_shipped_store", lambda: package_store)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(clone)
    return package_store, clone


@pytest.mark.parametrize("agent", sorted(PAYLOADS))
def test_an_installed_faildex_in_a_fresh_clone_warns_on_the_first_call(
    installed, monkeypatch, capsys, agent
):
    package_store, _clone = installed
    before = _files(package_store)
    assert store.hook_store() == Path("store")
    assert not store.is_public(store.hook_store())  # the case that went silent
    out = _hook(monkeypatch, capsys, ["hook", "--agent", agent], PAYLOADS[agent])
    if agent == "cursor":
        answer = json.loads(out)
        assert "git status" in answer["agent_message"] and "faildex" in answer["user_message"]
    else:
        assert "git status" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert _files(package_store) == before  # nothing written inside the package


def test_the_next_calls_answer_from_the_rebuilt_index_with_the_same_words(
    installed, monkeypatch, capsys
):
    package_store, _clone = installed
    before = _files(package_store)
    first = _hook(monkeypatch, capsys, ["hook"], PAYLOADS["claude"])
    assert "git status" in first
    assert index.rebuild(Path("store")) == 0  # what the background rebuild runs
    assert index.candidates(Path("store"))  # now answered from the index
    assert _hook(monkeypatch, capsys, ["hook"], PAYLOADS["claude"]) == first
    assert _files(package_store) == before


def _own_store(tmp_path: Path) -> Path:
    """A store made from fixture logs (not the public one), as committed parts only."""
    from test_index import _claude_session

    logs = tmp_path / "logs"
    logs.mkdir()
    for session in ("sess-a", "sess-b"):
        _claude_session(
            logs / f"{session}.jsonl",
            session,
            [("git push", "fatal: the current branch has no upstream branch"), ("ls", None)],
        )
    made = tmp_path / "made"
    assert main(["ingest", "--store", str(made), "--claude", str(logs)]) == 0
    return _parts(made, tmp_path / "copied" / "store")


PUSH = {"tool_name": "Bash", "tool_input": {"command": "git push"}}


def test_a_never_opened_store_that_is_not_public_warns_on_the_first_call(tmp_path):
    copied = _own_store(tmp_path)
    assert not (copied / "wal").exists()
    assert "git push" in respond(json.dumps(PUSH), copied)


def test_a_busy_write_lock_means_silence_at_once_then_a_warning(tmp_path):
    from faildex.locks import held

    copied = _own_store(tmp_path)
    with held(store._write_lock(copied)):  # an ingest is writing it
        started = time.monotonic()
        assert respond(json.dumps(PUSH), copied) == ""
        assert time.monotonic() - started < 3
    assert "git push" in respond(json.dumps(PUSH), copied)


def test_in_a_swap_gap_nothing_is_opened_for_writing(tmp_path):
    """R1 P0-1: a writable open of the missing folder would create an empty store."""
    copied = _own_store(tmp_path)
    token = "5ca1ab1e5ca1ab1e"
    aside = copied.parent / f".store.old-{token}"
    copied.rename(aside)
    work = copied.parent / f".store.writing-{token}"
    shutil.copytree(aside, work)
    for folder in (aside, work):
        mark = {"pid": 1, "store": str(copied.resolve()), "token": token, "time": time.time()}
        (folder / ".faildex-swap.json").write_text(json.dumps(mark), encoding="utf-8")
    assert respond(json.dumps(PUSH), copied) == ""
    assert not copied.exists()
    assert not (aside / "wal").exists() and not (work / "wal").exists()


@pytest.mark.parametrize(
    "folder",
    [
        {"manifest.json": '{"name": "my-app", "icons": []}'},  # a web app manifest
        {"manifest.json": '{"format_version": 5, "node_parts": [], "rel_parts": []}'},
        {"manifest.json": "not json", "nodes/": None, "relationships/": None},
    ],
    ids=["web manifest", "manifest without nodes/", "not json"],
)
@pytest.mark.parametrize("agent", sorted(PAYLOADS))
def test_a_folder_called_store_that_is_not_a_store_is_left_alone(
    tmp_path, monkeypatch, capsys, folder, agent
):
    other = tmp_path / "project" / "store"
    other.mkdir(parents=True)
    for name, text in folder.items():
        if name.endswith("/"):
            (other / name).mkdir()
        else:
            (other / name).write_text(text, encoding="utf-8")
    before = _files(other.parent)
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(other.parent)
    out = _hook(monkeypatch, capsys, ["hook", "--agent", agent], PAYLOADS[agent])
    assert out.strip() == quiet(agent)
    assert _files(other.parent) == before
    with contextlib.suppress(Exception):
        index.rebuild(other)  # nor in the background
    assert not index.candidates(other)
    assert _files(other.parent) == before
