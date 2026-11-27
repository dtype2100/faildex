"""Regression tests for the agy review of round 5 (2026-11-27, PASS with P2 1 and P3 2).

P2   `faildex ingest --store <folder>` on a folder with some other `manifest.json` (a web
     app's) read every log and copied the folder before failing with a traceback.
P3-a The hook started a background rebuild for a `./store` that is not a store at all.
"""

import io
import sys
from pathlib import Path

from payloads import git_status

from faildex import index, refresh
from faildex.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
REAL_START_REBUILD = index.start_rebuild  # before conftest stubs it for each test


def _web_app(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"name": "my-app", "icons": []}', encoding="utf-8")
    (folder / "app.js").write_text("console.log('hi')\n", encoding="utf-8")
    return folder


def _tree(folder: Path) -> dict:
    return {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}


# P2 ------------------------------------------------------------------------------------


def test_p2_ingest_refuses_a_folder_whose_manifest_is_not_a_stores(tmp_path, monkeypatch, capsys):
    from faildex.adapters import claude_code

    web = _web_app(tmp_path / "webapp")
    before = _tree(tmp_path)
    read = []
    monkeypatch.setattr(claude_code, "read_dir", lambda root: read.append(root) or [])
    code = main(["ingest", "--claude", str(FIXTURES / "claude_code"), "--store", str(web)])
    out = capsys.readouterr().out
    assert code == 1
    assert "is a folder with other files and no store in it" in out
    assert read == []  # refused before reading any log
    assert _tree(tmp_path) == before  # the folder as it was
    assert sorted(p.name for p in tmp_path.iterdir()) == ["webapp"]  # no lock, no .writing-*


def test_p2_stores_faildex_made_are_still_accepted(tmp_path, public_copy):
    import shutil

    logs = FIXTURES / "claude_code"
    empty = tmp_path / "empty-logs"
    empty.mkdir()
    made = tmp_path / "made"
    assert main(["ingest", "--claude", str(empty), "--store", str(made)]) == 0
    assert not (made / "nodes").exists()  # nothing to write yet: no parts folders
    assert main(["ingest", "--claude", str(logs), "--store", str(made)]) == 0
    assert main(["ingest", "--claude", str(logs), "--store", str(made)]) == 0
    copy = tmp_path / "public"
    shutil.copytree(public_copy, copy)
    assert main(["ingest", "--claude", str(logs), "--store", str(copy)]) == 0


# P3-a ----------------------------------------------------------------------------------


def test_p3a_no_background_rebuild_for_a_store_folder_that_is_not_a_store(
    tmp_path, monkeypatch, capsys
):
    _web_app(tmp_path / "project" / "store")
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path / "project")
    started = []
    monkeypatch.setattr(index, "start_rebuild", lambda store: started.append(store))
    payload = git_status()  # a failure: the path that would read the store
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["hook"]) == 0
    assert capsys.readouterr().out == ""
    assert started == []


def test_p3a_nor_any_rebuild_files_in_the_cache(tmp_path, monkeypatch, capsys):
    _web_app(tmp_path / "project" / "store")
    monkeypatch.delenv("FAILDEX_STORE", raising=False)
    monkeypatch.chdir(tmp_path / "project")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(index, "start_rebuild", REAL_START_REBUILD)
    spawned = []
    monkeypatch.setattr(refresh, "spawn", lambda argv, log: spawned.append(argv) or 1)
    payload = git_status()  # a failure: the path that would read the store
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["hook"]) == 0
    assert spawned == []
    left = [p.name for p in (tmp_path / "cache").rglob("*") if p.suffix in (".tried", ".log")]
    assert left == []
