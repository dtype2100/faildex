from dataclasses import astuple
from pathlib import Path

import relate

from faildex.adapters.claude_code import count_tool_uses, read_dir, read_session
from faildex.schema import ingest

FIXTURES = Path(__file__).parent / "fixtures" / "claude_code"
ALPHA = FIXTURES / "sess-alpha.jsonl"
BETA = FIXTURES / "sess-beta.jsonl"
MISSING_SIG = "cat: <path>: no such file or directory"

# Words that appear only in the fixtures' command arguments, tool inputs and outputs.
RAW_WORDS = [
    "quokka",
    "wombat",
    "narwhal",
    "ocelot",
    "axolotl",
    "capybara",
    "/srv/zeta",
    "/work/zeta",
    "origin",
    "9000",
    "example.test",
    "not been read",
]


def test_one_record_per_tool_use_that_has_a_result():
    # alpha: 4 tool_use blocks, the last one never got a result.
    assert count_tool_uses(ALPHA) == 4
    assert [r.seq for r in read_session(ALPHA)] == [0, 1, 2]
    # beta: 3 tool_use blocks, all answered; the orphan result adds nothing.
    assert count_tool_uses(BETA) == 3
    assert [r.seq for r in read_session(BETA)] == [0, 1, 2]


def test_fields_of_a_successful_bash_call():
    first = read_session(ALPHA)[0]
    assert (first.agent, first.session_id, first.seq) == ("claude-code", "sess-alpha", 0)
    assert (first.tool, first.ok, first.command, first.error_sig) == (
        "Bash",
        True,
        "git push",
        None,
    )
    assert first.ts == "2026-01-05T09:00:04.000Z"
    assert (first.source_path, first.source_line) == (str(ALPHA), 3)


def test_failed_bash_call_has_command_and_error_signature():
    failed = [r for r in read_session(ALPHA) if not r.ok]
    assert len(failed) == 1
    # The result was a list of text blocks.
    assert (failed[0].command, failed[0].error_sig) == ("cat", MISSING_SIG)
    assert failed[0].source_line == 5


def test_non_bash_calls_have_no_command_and_no_signature():
    read, grep, edit = read_session(ALPHA)[2], read_session(BETA)[0], read_session(BETA)[2]
    assert (read.tool, read.ok, read.command, read.error_sig) == ("Read", True, None, None)
    assert (read.source_line, grep.tool, grep.ok) == (9, "Grep", True)
    # A failed call of another tool is recorded as failed, without a signature.
    assert (edit.tool, edit.ok, edit.command, edit.error_sig) == ("Edit", False, None, None)


def test_session_id_falls_back_to_file_stem_and_failure_is_shared():
    beta = read_session(BETA)
    assert {r.session_id for r in beta} == {"sess-beta"}
    # Same failure as in alpha, given as a plain string after a `cd`.
    assert (beta[1].command, beta[1].error_sig, beta[1].source_line) == ("cat", MISSING_SIG, 6)
    assert beta[1].source_line == beta[2].source_line


def test_subagent_transcript_gets_its_own_session(tmp_path):
    lines = ALPHA.read_text().splitlines()
    side = [
        line.replace('"sessionId"', '"isSidechain":true,"agentId":"a17","sessionId"')
        for line in lines
    ]
    path = tmp_path / "agent-a17.jsonl"
    path.write_text("\n".join(side) + "\n")
    assert {r.session_id for r in read_session(path)} == {"sess-alpha/agent-a17"}


def test_read_dir_walks_jsonl_files_and_accepts_str(tmp_path):
    (tmp_path / "notes.txt").write_text("not a transcript\n")
    (tmp_path / "empty.jsonl").write_text("")
    assert list(read_dir(tmp_path)) == []
    records = list(read_dir(str(FIXTURES)))
    assert records == read_session(ALPHA) + read_session(BETA)


def test_records_ingest_into_relate():
    records = list(read_dir(FIXTURES))
    db = relate.connect(":memory:")
    assert ingest(db, records, local_paths=True) == len(records) == 6

    def count(query):
        return next(iter(db.execute(query)))["n"]

    assert count("MATCH (c:Call) RETURN count(c) AS n") == 6
    assert count("MATCH (s:Session) RETURN count(s) AS n") == 2
    shared = "MATCH (e:ErrorSig)<-[:FAILED_WITH]-(:Call)<-[:HAS_CALL]-(s) RETURN count(s) AS n"
    assert count(shared) == 2


def test_no_raw_command_text_or_output_in_records():
    for record in read_dir(FIXTURES):
        # source_path points at the fixture file itself; every other field is checked.
        values = [str(v) for v in astuple(record) if v != record.source_path]
        for word in RAW_WORDS:
            assert not any(word in value for value in values), (word, record)


def test_a_call_is_dated_by_when_its_result_arrived(tmp_path):
    import json

    from faildex.adapters.claude_code import read_session

    lines = [
        {
            "type": "assistant",
            "sessionId": "late",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {"command": "git push"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "sessionId": "late",
            "timestamp": "2026-01-09T00:00:00Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "is_error": True,
                        "content": "Exit code 1\nerror: failed to push",
                    }
                ]
            },
        },
    ]
    path = tmp_path / "late.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines))
    (record,) = read_session(path)
    assert record.ts == "2026-01-09T00:00:00Z"


def test_a_call_logged_twice_is_one_call(tmp_path):
    import json

    from faildex.adapters.claude_code import read_session

    use = {
        "type": "assistant",
        "sessionId": "dup",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {
            "content": [
                {"type": "tool_use", "id": "dup", "name": "Bash", "input": {"command": "git push"}}
            ]
        },
    }
    result = {
        "type": "user",
        "sessionId": "dup",
        "timestamp": "2026-01-01T00:00:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "dup",
                    "is_error": True,
                    "content": "error: failed to push",
                }
            ]
        },
    }
    path = tmp_path / "dup.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in (use, use, result)))
    assert len(read_session(path)) == 1
