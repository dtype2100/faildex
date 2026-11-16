import json
import sqlite3

import pytest

from faildex.adapters.cursor import read_dir, read_store


def _call(call_id, tool, args):
    part = {"type": "tool-call", "toolCallId": call_id, "toolName": tool, "args": args}
    return {"role": "assistant", "id": "m", "content": [part]}


def _result(call_id, tool, result):
    part = {"type": "tool-result", "toolCallId": call_id, "toolName": tool, "result": result}
    return {"role": "tool", "id": "m", "content": [part]}


MESSAGES = [
    {"role": "user", "content": "please build it"},
    _call("c1", "Shell", {"command": "git status", "description": "look"}),
    _result("c1", "Shell", "Exit code: 0\nOn branch main\nShell state persisted."),
    _call("c2", "Shell", {"command": "npm run build"}),
    _result("c2", "Shell", 'Exit code: 1\nnpm error Missing script: "build"'),
    _call("c3", "Read", {"path": "/work/demo/package.json"}),
    _result("c3", "Read", '{"name": "demo"}'),
    _call("c4", "Shell", {"command": "sleep 100"}),  # never answered
    _call("c5", "Shell", {"command": "pytest -q && ruff check ."}),
    _result("c5", "Shell", "Exit code: 2"),
]


@pytest.fixture
def chat(tmp_path):
    folder = tmp_path / "workspace" / "chat-1"
    folder.mkdir(parents=True)
    path = folder / "store.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    meta = {"agentId": "cursor-chat-1", "createdAt": 1767225600000, "name": "demo"}
    con.execute("INSERT INTO meta VALUES ('0', ?)", (json.dumps(meta).encode().hex(),))
    con.execute("INSERT INTO blobs VALUES ('bin', ?)", (b"\x00\x01\xff binary bookkeeping",))
    for index, message in enumerate(MESSAGES):
        con.execute("INSERT INTO blobs VALUES (?, ?)", (f"b{index}", json.dumps(message).encode()))
    con.commit()
    con.close()
    return path


def test_one_record_per_answered_call_in_write_order(chat):
    records = read_store(chat)
    assert [(r.seq, r.tool, r.command, r.ok) for r in records] == [
        (0, "Shell", "git status", True),
        (1, "Shell", "npm run", False),
        (2, "Read", None, True),
        (4, "Shell", "pytest", False),
    ]
    assert {r.agent for r in records} == {"cursor"}
    assert {r.session_id for r in records} == {"cursor-chat-1"}
    assert {r.ts for r in records} == {"2026-01-01T00:00:00+00:00"}


def test_failures_carry_signature_exit_code_and_compound_flag(chat):
    records = read_store(chat)
    assert records[1].failure == ("npm error missing script: <s>", "text")
    assert records[3].compound and records[3].failure == ("pytest exited 2", "exit")


def test_no_raw_text_reaches_a_record(chat):
    records = read_store(chat)
    assert all("Missing script" not in repr(r) for r in records)
    assert all("package.json" not in repr(r) for r in records)


def test_read_dir_skips_files_that_are_not_chats(chat, tmp_path):
    other = tmp_path / "workspace" / "broken"
    other.mkdir()
    (other / "store.db").write_text("not a database")
    assert len(list(read_dir(tmp_path))) == 4
