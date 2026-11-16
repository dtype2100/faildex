from pathlib import Path

from faildex.adapters.codex_local import read_dir, read_session

FIXTURE = Path(__file__).parent / "fixtures" / "codex_local" / "rollout-demo.jsonl"


def test_one_record_per_executed_command():
    records = read_session(FIXTURE)
    assert [(r.seq, r.command, r.ok) for r in records] == [
        (0, "git status", True),
        (1, "npm run", False),
        (2, "npm run", True),
        (3, "pytest", False),
    ]
    assert {r.session_id for r in records} == {"local-1"}
    assert {r.agent for r in records} == {"codex"}


def test_failures_carry_signature_exit_code_and_compound_flag():
    records = read_session(FIXTURE)
    failed = records[1]
    assert failed.error_sig == "npm error missing script: <s>"
    assert failed.exit_code == 1
    assert failed.failure == ("npm error missing script: <s>", "text")
    assert not records[2].compound  # cd only sets up the real command
    assert records[3].compound
    assert records[3].failure == ("pytest exited 1", "exit")


def test_no_raw_text_and_pointers_into_the_file():
    records = read_session(FIXTURE)
    assert records[1].source_line == 4
    assert all("Missing script" not in repr(r) for r in records)
    assert all("/work/demo" not in repr(r) for r in records)


def test_read_dir_and_missing_session_meta(tmp_path):
    lines = FIXTURE.read_text().splitlines()[1:]
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "rollout-x.jsonl").write_text("\n".join(lines))
    records = list(read_dir(tmp_path))
    assert len(records) == 4
    assert records[0].session_id == "rollout-x"
