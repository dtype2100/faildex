import relate

from faildex.cli import main
from faildex.insight import RETRY, approve, proposals, render, warnings_for
from faildex.schema import CallRecord, ingest


def _call(session, seq, ok=True, command="git push", sig=None, tool="Bash"):
    return CallRecord(
        agent="claude_code",
        session_id=session,
        seq=seq,
        tool=tool,
        ok=ok,
        ts=f"2026-01-01T00:00:{seq:02d}Z",
        command=command,
        error_sig=sig,
        source_path=f"demo/{session}.jsonl",
        source_line=seq + 1,
    )


REJECTED = "rejected: non-fast-forward"


def _records():
    records = []
    # Three sessions hit the same push failure; two fix it with a pull, one by retrying.
    for session in ("s1", "s2"):
        records += [
            _call(session, 0, ok=False, sig=REJECTED),
            _call(session, 1, command="git pull"),
            _call(session, 2),
        ]
    records += [_call("s3", 0, ok=False, sig=REJECTED), _call("s3", 1)]
    # Seen in one session only: not worth a rule.
    records += [_call("s4", 0, ok=False, command="npm run", sig="missing script")]
    # Seen twice, never fixed.
    records += [
        _call(s, 0, ok=False, command="cargo build", sig="linker not found") for s in ("s5", "s6")
    ]
    return records


def _db():
    db = relate.connect(":memory:")
    ingest(db, _records())
    return db


def test_proposals_rank_recurring_failures_and_read_the_fix_off_the_graph():
    items = proposals(_db())
    assert [item.sig for item in items] == [REJECTED, "linker not found"]
    push = items[0]
    assert (len(push.sessions), push.calls, push.recovered) == (3, 3, 3)
    assert push.fix == "git pull"
    assert push.fixes[RETRY] == 1
    assert round(push.consistency, 2) == 0.67
    assert "running `git pull` first (2 of 3 recoveries)" in push.rule()
    assert "no recovery on record" in items[1].rule()


def test_evidence_points_into_the_logs():
    push = proposals(_db())[0]
    assert push.evidence[0] == "demo/s1.jsonl:1"
    assert "evidence: demo/s1.jsonl:1" in render([push])


def test_warnings_only_for_commands_with_a_known_recurring_failure():
    db = _db()
    assert [w.sig for w in warnings_for(db, "git push")] == [REJECTED]
    assert warnings_for(db, "git pull") == []
    assert warnings_for(db, "npm run") == []  # one session is not a pattern


def test_approve_writes_only_chosen_rules_once(tmp_path):
    items = proposals(_db())
    path = tmp_path / "rules.md"
    assert len(approve(items, [1], path)) == 1
    assert approve(items, [1], path) == []
    text = path.read_text()
    assert text.count("git pull") == 1
    assert "linker" not in text
    assert "Evidence: demo/s1.jsonl:1" in text


def test_cli_check_is_silent_for_unknown_commands(tmp_path, capsys):
    store = tmp_path / "store"
    db = relate.connect(str(store))
    ingest(db, _records())
    db.commit()
    db.flush()
    db.close()
    assert main(["check", "git push origin main", "--store", str(store)]) == 0
    assert "git pull" in capsys.readouterr().out
    assert main(["check", "ls -la", "--store", str(store)]) == 0
    assert capsys.readouterr().out == ""
    assert main(["rules", "--store", str(store)]) == 0
    assert capsys.readouterr().out.startswith("1. When `git push`")


def _store(tmp_path):
    store = tmp_path / "hookstore"
    db = relate.connect(str(store))
    ingest(db, _records())
    db.commit()
    db.flush()
    db.close()
    return store


def _payload(command, tool="Bash"):
    import json

    return json.dumps({"tool_name": tool, "tool_input": {"command": command}})


def test_hook_warns_about_a_known_failure_without_deciding_permission(tmp_path):
    import json

    from faildex.hook import respond

    out = json.loads(respond(_payload("git push origin main"), _store(tmp_path)))
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert "git pull" in specific["additionalContext"]
    assert "permissionDecision" not in specific
    assert out["systemMessage"] == (
        "faildex: `git push` failed with `rejected: non-fast-forward` in 3 earlier sessions; "
        "sessions got past it by running `git pull` first."
    )


def test_hook_is_silent_for_unknown_commands_other_tools_and_bad_input(tmp_path):
    from faildex.hook import respond

    store = _store(tmp_path)
    assert respond(_payload("ls -la"), store) == ""
    assert respond(_payload("git push", tool="Edit"), store) == ""
    assert respond("not json", store) == ""
    assert respond(_payload("git push"), tmp_path / "missing") == ""


def test_warnings_for_a_command_count_only_that_command():
    db = relate.connect(":memory:")
    records = [
        _call("p1", 0, ok=False, sig="permission denied"),
        _call("p1", 1),
        _call("p2", 0, ok=False, sig="permission denied"),
        _call("p2", 1),
        _call("r1", 0, ok=False, command="rm", sig="permission denied"),
        _call("r2", 0, ok=False, command="rm", sig="permission denied"),
    ]
    ingest(db, records)
    (warning,) = warnings_for(db, "rm")
    assert warning.command == "rm"
    assert (len(warning.sessions), warning.calls, warning.recovered) == (2, 2, 0)
    assert "no recovery on record" in warning.rule()


def test_a_compound_command_line_proves_no_recovery():
    from dataclasses import replace

    db = relate.connect(":memory:")
    failed = replace(_call("s1", 0, ok=False, sig="valueerror"), compound=True)
    ingest(db, [failed, _call("s1", 1), replace(failed, session_id="s2")])
    assert proposals(db)[0].recovered == 0


def test_a_compound_success_is_not_a_recovery():
    from dataclasses import replace

    db = relate.connect(":memory:")
    ingest(
        db,
        [
            _call("s1", 0, ok=False, sig="rejected"),
            replace(_call("s1", 1), compound=True),
            _call("s2", 0, ok=False, sig="rejected"),
        ],
    )
    assert proposals(db)[0].recovered == 0


def test_a_rare_failure_of_a_common_command_gives_no_warning():
    db = relate.connect(":memory:")
    records = [_call(f"ok{n}", 0, command="ls") for n in range(98)]
    records += [_call(s, 0, ok=False, command="ls", sig="no such file") for s in ("a", "b")]
    ingest(db, records)
    assert warnings_for(db, "ls") == []  # 2 of 100 runs
    (kept,) = warnings_for(db, "ls", min_rate=0.01)
    assert kept.runs == 100
    assert "2% of this command's 100 runs" in kept.rule()


def test_notice_says_what_happened_and_what_got_past_it():
    items = {item.sig: item for item in proposals(_db())}
    assert items["linker not found"].notice() == (
        "faildex: `cargo build` failed with `linker not found` in 2 earlier sessions; "
        "no recovery on record."
    )


def test_nomatch_combines_sessions_across_commands_only_for_unquoted_globs():
    from faildex.insight import warnings_for_line

    db = relate.connect(":memory:")
    sig = "no matches found: <glob>"
    ingest(
        db,
        [
            _call("a", 0, ok=False, command="ls", sig=sig),
            _call("b", 0, ok=False, command="rg", sig=sig),
        ],
    )
    for command in ["ls README*", "find *.py", "f=$(ls *.py | head -1)", "ls *.py; rg *.txt"]:
        _, pairs = warnings_for_line(db, command)
        assert len(pairs) == 1, command
        _, warning = pairs[0]
        assert warning.sig == sig
        assert warning.sessions == {"claude_code:a", "claude_code:b"}
        assert warning.calls == 2
        assert warning.recovered == 0
    for command in [
        "git status",
        "ls '*.py'",
        r"ls \*.py",
        "cat <<'EOF'\n$(ls *.py)\nEOF",
        "f() { ls *.py; }",
    ]:
        assert warnings_for_line(db, command)[1] == [], command
    db.close()
