import json

import relate
from payloads import failed

from faildex.cli import main
from faildex.hook import respond
from faildex.report import periods, render
from faildex.schema import CallRecord, ingest


def _call(session, day, seq, ok=True, sig=None, agent="claude_code", command="echo"):
    return CallRecord(
        agent=agent,
        session_id=session,
        seq=seq,
        tool="Bash",
        ok=ok,
        command=command,
        error_sig=sig,
        ts=f"2026-11-{day:02d}T10:00:{seq:02d}Z",
    )


NOT_FOUND = "(eval):<n>: ==== not found"


def _records():
    return [
        _call("a", 10, 0, ok=False, sig=NOT_FOUND),
        _call("a", 10, 1),
        _call("b", 12, 0, ok=False, sig=NOT_FOUND),
        _call("b", 12, 1, ok=False, sig="permission denied", command="rm"),
        _call("c", 18, 0),
        _call("c", 18, 1),
        _call("c", 18, 2, ok=False, sig="permission denied", command="rm"),
        _call("x", 18, 0, ok=False, sig="permission denied", agent="codex", command="rm"),
    ]


def _db():
    db = relate.connect(":memory:")
    ingest(db, _records())
    return db


def test_periods_split_on_the_day_and_count_the_key():
    before, after = periods(_db(), "2026-11-17", "not found")
    assert (before.calls, before.failed, before.matched) == (4, 3, 2)
    assert (after.calls, after.failed, after.matched) == (4, 2, 0)
    assert (len(before.sessions), len(after.sessions)) == (2, 2)
    assert before.rate(before.matched) == "500.0"


def test_without_a_split_there_is_one_period():
    (everything,) = periods(_db(), None, None)
    assert (everything.calls, everything.failed, everything.matched) == (8, 5, 0)


def test_render_lists_agents_and_shared_keys():
    text = render(_db(), "2026-11-17", "not found")
    assert "failure keys seen under more than one agent: 1" in text
    assert "codex" in text and "claude_code" in text
    assert "not a controlled comparison" in text


def test_hook_log_records_the_template_only_and_report_counts_it(tmp_path, capsys):
    store = tmp_path / "store"
    db = relate.connect(str(store))
    ingest(db, _records())
    db.commit()
    db.flush()
    db.close()
    log = tmp_path / "logs" / "hook.jsonl"
    assert respond(failed("rm -rf /Users/alice/private", "permission denied"), store, log=log)
    assert respond(failed("ls", "permission denied"), store, log=log) == ""
    (entry,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert entry["command"] == "rm" and entry["warnings"] == 1
    assert "alice" not in log.read_text()

    assert main(["report", "--store", str(store), "--hook-log", str(log)]) == 0
    assert "hook warnings" in capsys.readouterr().out


def test_report_rejects_a_split_that_is_not_a_day(tmp_path, capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["report", "--store", str(tmp_path), "--split", "2026/11/20"])
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_report_refuses_a_missing_hook_log(tmp_path, capsys):
    assert main(["report", "--store", str(tmp_path), "--hook-log", str(tmp_path / "no.jsonl")]) == 1
    assert "no hook log" in capsys.readouterr().out


def test_report_shows_the_matched_column_only_with_a_key():
    db = _db()
    plain = render(db, "2026-11-15", None)
    keyed = render(db, "2026-11-15", "not found")
    db.close()
    assert "matched" not in plain and "failed with" not in plain
    assert 'failed with "not found"' in keyed
    assert "counts in both periods" in plain


def test_report_says_how_many_calls_had_no_timestamp():
    db = relate.connect(":memory:")
    undated = CallRecord(agent="claude_code", session_id="u", seq=0, tool="Bash", ok=True)
    ingest(db, [*_records(), undated])
    out = render(db, None, None)
    db.close()
    assert "1 call(s) without a timestamp are not counted above." in out
