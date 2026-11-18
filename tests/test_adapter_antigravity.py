from pathlib import Path

from faildex.adapters.antigravity import read_dir, read_session

ROOT = Path(__file__).parent / "fixtures" / "antigravity"
CONV = ROOT / "brain" / "conv-1"


def test_answers_are_paired_with_calls_in_order():
    records = read_session(CONV)
    assert [(r.seq, r.tool, r.command, r.ok) for r in records] == [
        (0, "run_command", "git status", False),
        (1, "view_file", None, True),
        (2, "run_command", "ls", True),
        (3, "run_command", "npm test", False),
    ]
    assert {r.agent for r in records} == {"antigravity"}
    assert {r.session_id for r in records} == {"conv-1"}


def test_exit_codes_and_error_steps_become_failure_keys():
    records = read_session(CONV)
    git, npm = records[0], records[3]
    assert git.exit_code == 128
    assert git.error_sig == "fatal: not a git repository (or any of the parent directories): .git"
    assert npm.failure[0].startswith("error: command failed to start")


def test_interrupted_calls_and_stray_answers_are_skipped():
    assert len(read_session(CONV)) == 4  # `sleep 100` was interrupted


def test_no_raw_text_leaves_the_adapter():
    records = read_session(CONV)
    assert all("/work/demo" not in repr(r) and "README.md" not in repr(r) for r in records)


def test_read_dir_accepts_the_data_folder_or_brain(tmp_path):
    assert len(list(read_dir(ROOT))) == 4
    assert len(list(read_dir(ROOT / "brain"))) == 4
    assert list(read_dir(tmp_path)) == []


def test_ingest_takes_antigravity_folders(tmp_path, capsys):
    from faildex.cli import main

    store = tmp_path / "store"
    assert main(["ingest", "--antigravity", str(ROOT), "--store", str(store)]) == 0
    assert "ingested 4 calls" in capsys.readouterr().out
