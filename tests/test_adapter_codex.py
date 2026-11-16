import json
from dataclasses import asdict
from pathlib import Path

import relate

from faildex.adapters.codex import read_file, read_rows
from faildex.schema import ingest

FIXTURE = Path(__file__).parent / "fixtures" / "codex" / "trajectories.sample.jsonl"

# The fixture is synthetic: 6 lines, 5 valid rows, 9 tool calls. One call has no
# tool message and one has arguments that are not JSON, so 7 records remain.
# (session, seq, line, tool, ok, command) in the order the sessions really ran.
EXPECTED = [
    ("sess-alpha", 0, 5, "shell_command", True, "Get-ChildItem"),
    ("sess-alpha", 1, 4, "shell_command", True, "uv run pytest"),
    ("sess-alpha", 2, 1, "apply_patch", True, None),
    ("sess-alpha", 3, 1, "shell_command", True, "git status"),
    ("sess-beta", 0, 2, "shell_command", False, "git status"),
    ("sess-beta", 1, 6, "update_plan", True, None),
    ("sess-beta", 2, 6, "shell_command", False, "cargo build"),
]


def records():
    return list(read_file(FIXTURE))


def by_key(recs):
    return sorted(recs, key=lambda r: (r.session_id, r.seq))


def fixture_rows():
    """The parseable rows of the fixture, with None standing in for the malformed line."""
    rows = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append(None)
    return rows


def test_one_record_per_answered_call():
    recs = by_key(records())
    got = [(r.session_id, r.seq, r.source_line, r.tool, r.ok, r.command) for r in recs]
    assert got == EXPECTED
    assert {r.agent for r in recs} == {"codex"}
    assert {r.source_path for r in recs} == {str(FIXTURE)}


def test_seq_follows_timestamp_then_segment_not_file_order():
    alpha = [r for r in by_key(records()) if r.session_id == "sess-alpha"]
    assert [r.seq for r in alpha] == [0, 1, 2, 3]
    assert [r.ts for r in alpha] == [
        "2026-01-05T10:00:00.000Z",
        "2026-01-05T10:00:00.000Z",
        "2026-01-05T10:05:00.000Z",
        "2026-01-05T10:05:00.000Z",
    ]
    # Line 5 is segment 1 and line 4 is segment 2 of the same turn; line 1 is the later turn.
    assert [r.source_line for r in alpha] == [5, 4, 1, 1]


def test_failed_call_gets_command_and_error_signature():
    failed = [r for r in by_key(records()) if not r.ok]
    assert [(r.command, r.error_sig) for r in failed] == [
        ("git status", "the token <s> is not a valid statement separator in this version."),
        ("cargo build", "error: could not find <s> in <s> or any parent directory"),
    ]
    assert all(r.error_sig is None for r in records() if r.ok)


def test_records_ingest_into_relate():
    recs = records()
    db = relate.connect(":memory:")
    assert ingest(db, recs) == len(recs) == 7

    def count(query):
        return next(iter(db.execute(query)))["n"]

    assert count("MATCH (c:Call) RETURN count(c) AS n") == 7
    assert count("MATCH (s:Session) RETURN count(s) AS n") == 2
    assert count("MATCH (:Call)-[r:NEXT]->(:Call) RETURN count(r) AS n") == 5
    assert count("MATCH (:Call)-[r:FAILED_WITH]->(:ErrorSig) RETURN count(r) AS n") == 2


def test_no_raw_arguments_or_output_in_records():
    raw = set()
    for row in filter(None, fixture_rows()):
        for message in row["messages"]:
            for call in message.get("tool_calls") or []:
                arguments = call["function"]["arguments"]
                raw.add(arguments)
                try:
                    raw.update(v for v in json.loads(arguments).values() if isinstance(v, str))
                except ValueError:
                    pass
            if message["role"] == "tool":
                raw.add(message["content"])
    assert len(raw) > 15
    fields = [v for r in records() for v in asdict(r).values() if isinstance(v, str)]
    for text in raw:
        assert not any(text in field for field in fields), text


def test_read_rows_matches_read_file():
    assert list(read_rows(fixture_rows(), FIXTURE)) == records()


def test_bad_input_is_skipped():
    call = {"id": "c1", "function": {"name": "shell_command", "arguments": '{"command": "ls"}'}}
    answer = {"role": "tool", "tool_call_id": "c1", "content": "Exit code: 0\nOutput:\n"}
    good = {"session_id": "s", "timestamp": None, "messages": [{"tool_calls": [call]}, answer]}
    rows = [
        None,
        [],
        {"messages": [{"tool_calls": [call]}, answer]},  # no session
        {"session_id": "s", "messages": "nope"},
        {"session_id": "s", "messages": [None, {"tool_calls": [None, {"id": "c2"}]}]},
        {"session_id": "s", "timestamp": "not a time", "messages": [{"tool_calls": "x"}]},
        good,
    ]
    recs = list(read_rows(rows, "mem.jsonl"))
    assert [(r.seq, r.source_line, r.command, r.ts) for r in recs] == [(0, 7, "ls", None)]


def test_tool_without_exit_code_is_ok_unless_it_reports_one():
    def row(content):
        call = {"id": "c1", "function": {"name": "py_eval", "arguments": "{}"}}
        answer = {"role": "tool", "tool_call_id": "c1", "content": content}
        return {"session_id": "s", "messages": [{"tool_calls": [call]}, answer]}

    def ok(content):
        (record,) = read_rows([row(content)], "mem.jsonl")
        return record.ok, record.error_sig

    assert ok("Wall time: 0.1 seconds\nOutput:\nTraceback") == (True, None)
    assert ok("Exit code: 0\nOutput:\n") == (True, None)
    assert ok("Exit code: 2\nOutput:\nboom") == (False, None)
