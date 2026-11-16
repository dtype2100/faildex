import shutil
from pathlib import Path

import pytest

from faildex import build
from faildex.cli import main
from faildex.store import open_store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A tiny stand-in for `.tmp/data`, laid out like the real datasets."""
    data = tmp_path / "data"
    shutil.copytree(FIXTURES / "claude_code", data / "wisp" / "transcripts" / "proj")
    (data / "codex-trajectories").mkdir()
    for name in ("trajectories.train.jsonl", "trajectories.eval.jsonl"):
        shutil.copy(
            FIXTURES / "codex" / "trajectories.sample.jsonl", data / "codex-trajectories" / name
        )
    return data


def _count(db, query: str) -> int:
    return next(iter(db.execute(query)))["n"]


def test_build_store_writes_sources_and_pointers(data_dir, tmp_path):
    out = tmp_path / "store"
    result = build.build_store(data_dir, out)

    assert result["counts"]["Source"] == 2
    assert result["counts"]["Call"] > 0
    assert result["bytes"] > 0

    db = open_store(out)
    sessions = _count(db, "MATCH (n:Session) RETURN count(n) AS n")
    assert _count(db, "MATCH (:Session)-[r:FROM]->(:Source) RETURN count(r) AS n") == sessions
    paths = [r["p"] for r in db.execute("MATCH (c:Call) RETURN DISTINCT c.source_path AS p")]
    assert paths and all(p.startswith(("wisp/", "codex-trajectories/")) for p in paths)
    assert not any(str(tmp_path) in p for p in paths)
    db.close()


def test_build_store_is_repeatable(data_dir, tmp_path):
    first = build.build_store(data_dir, tmp_path / "store")["counts"]
    second = build.build_store(data_dir, tmp_path / "store")["counts"]
    assert first == second


def test_store_opens_read_only_from_committed_files_alone(data_dir, tmp_path):
    out = tmp_path / "store"
    expected = build.build_store(data_dir, out)["counts"]["Call"]

    # What a fresh clone has: no lock files and no write-ahead log.
    clone = tmp_path / "clone"
    shutil.copytree(
        out, clone, ignore=shutil.ignore_patterns("*.lock", ".cypherlite.writer", "wal")
    )
    db = open_store(clone)
    assert _count(db, "MATCH (n:Call) RETURN count(n) AS n") == expected
    with pytest.raises(Exception, match="(?i)read.?only|write"):
        db.execute("CREATE (:Scratch)")
    db.close()


def test_open_store_without_a_store(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_store(tmp_path / "nothing")


def test_cli_build_store(data_dir, tmp_path, capsys):
    assert main(["build-store", "--data", str(data_dir), "--out", str(tmp_path / "s")]) == 0
    assert "Call" in capsys.readouterr().out
    assert (
        main(["build-store", "--data", str(tmp_path / "none"), "--out", str(tmp_path / "s")]) == 1
    )
