import relate

import faildex
from faildex.cli import main


def test_version_is_set():
    assert faildex.__version__


def test_cli_runs():
    assert main([]) == 0


def test_relate_opens_in_memory():
    db = relate.connect(":memory:")
    rows = list(db.execute("RETURN 1 + 2 AS n"))
    assert rows[0]["n"] == 3


def test_top_and_min_sessions_must_be_positive(capsys):
    import pytest

    for argv in (
        ["check", "--top", "0", "git status"],
        ["check", "--top", "-1", "git status"],
        ["rules", "--min-sessions", "0"],
        ["hook", "--top", "x"],
    ):
        with pytest.raises(SystemExit):
            main(argv)
        assert "1 or more" in capsys.readouterr().err


def test_a_missing_store_points_at_ingest_not_make(tmp_path, capsys):
    assert main(["check", "--store", str(tmp_path / "none"), "git status"]) == 1
    out = capsys.readouterr().out
    assert "faildex ingest --store" in out and "make" not in out


def test_export_web_never_picks_your_own_logs_unasked(tmp_path, monkeypatch, capsys):
    """Outside a checkout the default is the shipped public store, even when ~/.faildex exists."""
    import json

    from faildex.schema import CallRecord, ingest

    home = tmp_path / "home"
    private = home / ".faildex" / "store"
    private.parent.mkdir(parents=True)
    db = relate.connect(str(private))
    ingest(db, [CallRecord("claude-code", "mine", 0, "Bash", True, command="ls")], local_paths=True)
    db.commit()
    db.flush()
    db.close()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("FAILDEX_STORE", str(private))

    assert main(["export-web", "--out", str(tmp_path / "public.json")]) == 0
    out = capsys.readouterr().out
    data = json.loads((tmp_path / "public.json").read_text())
    assert len(data["sessions"]) == 422 and "note:" not in out

    assert main(["export-web", "--store", str(private), "--out", str(tmp_path / "p.json")]) == 0
    assert "do not publish" in capsys.readouterr().out


def test_report_honours_faildex_store_before_your_own_store(tmp_path, monkeypatch, capsys):
    from faildex.schema import CallRecord, ingest

    def make(path, agent):
        db = relate.connect(str(path))
        rec = CallRecord(agent, "s", 0, "Bash", True, command="ls", ts="2026-11-01T00:00:00Z")
        ingest(db, [rec], local_paths=True)
        db.commit()
        db.flush()
        db.close()

    home = tmp_path / "home"
    (home / ".faildex").mkdir(parents=True)
    make(home / ".faildex" / "store", "cursor")
    make(tmp_path / "named", "codex")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("FAILDEX_STORE", str(tmp_path / "named"))
    assert main(["report"]) == 0
    out = capsys.readouterr().out
    assert "codex" in out and "cursor" not in out


def test_public_store_cache_survives_a_leftover_partial_folder(tmp_path, monkeypatch):
    from faildex.store import public_store

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    first = public_store()
    import shutil

    shutil.rmtree(first)
    first.mkdir()  # an interrupted older copy: the folder without a manifest
    again = public_store()
    assert again == first and (again / "manifest.json").is_file()
    assert public_store() == first  # a ready cache is reused as is
    assert [p.name for p in first.parent.iterdir()] == [first.name]  # no temp folders left
