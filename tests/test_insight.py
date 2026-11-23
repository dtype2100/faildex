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
    rendered = render([push])
    assert "evidence (3): demo/s1.jsonl:1, +2 more" in rendered
    full = render([push], show_evidence=True)
    assert "demo/s1.jsonl:1" in full and "demo/s2.jsonl:1" in full and "demo/s3.jsonl:1" in full
    assert "+2 more" not in full


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
    rules_out = capsys.readouterr().out
    assert "6 sessions, 6 failed calls, 2 recurring" in rules_out
    assert "1. `git push` — rejected: non-fast-forward" in rules_out
    assert "3 sessions, 3 failed calls · 3 of 3 recovered within 5 calls" in rules_out
    assert "Action: run `git pull` first; 2 of 3 recoveries did that." in rules_out
    assert "full evidence paths: --evidence" in rules_out
    assert (
        f"Write a rule: faildex rules --approve 1 2 --store {store} --to ~/faildex-rules.md"
        in rules_out
    )


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


def test_warnings_for_line_skips_scripts_containing_double_lt_without_error():
    from faildex.insight import warnings_for_line

    db = _db()
    try:
        assert warnings_for_line(db, "git push")[1] != []
        for command in [
            "git push <<'EOF'\nhello\nEOF",
            "cat <<EOF | git push\n$(private_customer_command)\nEOF",
            "echo '<<' && git push",
            "git push # <<",
            "cat <<< 'hello' && git push",
            "cat <<-EOF\n\t$(private_customer_command)\n\tEOF\ngit push",
            "cat <<EOF | grep x",
            "echo $\\\n'don\\'t; git push'",
            "((\ngit push\n))",
        ]:
            assert warnings_for_line(db, command) == ([], [])
    finally:
        db.close()


def test_nomatch_combines_sessions_across_commands_only_for_unquoted_globs():
    from faildex.insight import warnings_for_line

    db = relate.connect(":memory:")
    sig = "no matches found: <glob>"
    records = [_call(f"ok{n}", 0, command="ls") for n in range(98)]
    records += [
        _call("a", 0, ok=False, command="ls", sig=sig),
        _call("b", 0, ok=False, command="rg", sig=sig),
        _call("c", 0, ok=False, command="grep", sig=sig),
    ]
    ingest(db, records)
    for command in [
        "ls README*",
        "find *.py",
        "for f in *.x; do ls README*; done",
        "( ls README* readme* )",
        "f=$(ls README* readme* | head -1)",
        'echo "$(ls README*)"',
        "ls *.py; rg *.txt",
        'cd ~ && for d in a b; do ( cd "$d" && { git log -1; f=$(ls README* readme* | head -1); } ); done',
    ]:
        _, pairs = warnings_for_line(db, command)
        assert len(pairs) == 1, command
        _, warning = pairs[0]
        assert warning.sig == sig
        assert warning.sessions == {"claude_code:a", "claude_code:b", "claude_code:c"}
        assert warning.calls == 3
        assert warning.recovered == 0
    for command in [
        "git status",
        "ls -la",
        "ls '*.py'",
        'ls "*.py"',
        r"ls \*.py",
        'echo "a \\"*.private"',
        "[ -f a ] && git status",
        "cat <<'EOF'\n$(ls *.py)\nEOF",
        "cat <<EOF | ls *.py\n$(ls *.py)\nEOF",
        "f() { ls *.py; }",
    ]:
        assert warnings_for_line(db, command)[1] == [], command
    db.close()


def test_legacy_unpooled_nomatch_keys_in_existing_stores_still_pool_on_query():
    from faildex.insight import warnings_for_line

    db = relate.connect(":memory:")
    ingest(
        db,
        [
            _call(
                "a", 0, ok=False, command="grep", sig="(eval):<n>: no matches found: --include=*.py"
            ),
            _call("b", 0, ok=False, command="ls", sig="(eval):<n>: no matches found: <path>*/"),
            _call("c", 0, ok=False, command="rg", sig="zsh:<n>: no matches found: <path>*"),
        ],
    )
    _, pairs = warnings_for_line(db, "ls README* readme*")
    assert len(pairs) == 1
    cmd, warning = pairs[0]
    assert cmd == "zsh"
    assert warning.sig == "no matches found: <glob>"
    assert warning.calls == 3
    assert len(warning.sessions) == 3
    # A non-glob grep command must not emit a warning from the legacy NOMATCH key.
    assert warnings_for_line(db, "grep foo bar.py")[1] == []
    db.close()


def test_rules_truncate_at_word_boundaries_and_shorten_home(tmp_path, monkeypatch):
    from faildex.insight import short_pointer, tilde_path, truncate_words

    long_sig = (
        "rg: <path>: the filename, directory name, or volume label syntax is incorrect. (os error <"
    )
    shortened = truncate_words(long_sig, 79)
    assert (
        shortened
        == "rg: <path>: the filename, directory name, or volume label syntax is incorrect…"
    )
    assert "(os error <" not in shortened

    mid_word = (
        "rg: <path>: io error for operation on <path>: the filename, directory name, or volume labe"
    )
    shortened_mid = truncate_words(mid_word, 79)
    assert (
        shortened_mid
        == "rg: <path>: io error for operation on <path>: the filename, directory name, or…"
    )
    assert "labe" not in shortened_mid

    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    deep = f"{fake_home}/.claude/projects/-Users-alice-very-long-workspace-name/01234567-89ab-cdef-0123-456789abcdef.jsonl:42"
    assert tilde_path(deep).startswith("~/.claude/")
    compact = short_pointer(deep)
    assert compact.startswith("~/.claude/.../") and compact.endswith(":42")
    assert len(compact) <= 48


def test_rules_output_color_no_color_and_cp1252_safety(tmp_path, monkeypatch, capsys):
    import io
    from collections import Counter

    from faildex.insight import Failure, render, safe_console_text, use_color

    store = _store(tmp_path)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    # Non-TTY stdout (pipe / capsys) has no ANSI escape sequences.
    assert main(["rules", "--store", str(store)]) == 0
    piped = capsys.readouterr().out
    assert "\033[" not in piped

    class FakeTTY(io.StringIO):
        def isatty(self):
            return True

    tty = FakeTTY()
    assert use_color(tty) is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert use_color(tty) is False

    item = Failure(
        sig="rg: <path>: io error for operation on <path>: the filename, directory name, or volume labe",
        kind="text",
        calls=7,
        sessions={"s1", "s2"},
        fixes=Counter({"retry": 6}),
        recovered=6,
        evidence=["demo/s1.jsonl:1"],
    )
    item.commands["rg"] = 7
    cp1252_text = safe_console_text(
        render([item], encoding="ascii") + " → ✓", io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    )
    cp1252_text.encode("cp1252", errors="strict")
    assert "->" in cp1252_text and "ok" in cp1252_text and "..." in cp1252_text


def test_rules_cli_marks_public_vs_private_store_and_evidence_flag(tmp_path, monkeypatch, capsys):
    import shutil
    from pathlib import Path

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    private = home / ".faildex" / "store"
    db = relate.connect(str(private))
    ingest(db, _records())
    db.commit()
    db.flush()
    db.close()

    monkeypatch.chdir(tmp_path)
    assert main(["rules"]) == 0
    priv_out = capsys.readouterr().out
    assert priv_out.startswith("Your logs (~/.faildex/store): 6 sessions, 6 failed calls")

    assert main(["rules", "--evidence"]) == 0
    ev_out = capsys.readouterr().out
    assert "demo/s1.jsonl:1" in ev_out and "demo/s2.jsonl:1" in ev_out
    assert "+2 more" not in ev_out and "full evidence paths" not in ev_out

    public_copy = tmp_path / "pub"
    shutil.copytree(Path(__file__).resolve().parents[1] / "store", public_copy)
    assert main(["rules", "--store", str(public_copy), "--top", "2"]) == 0
    pub_out = capsys.readouterr().out
    assert "Public demo logs (" in pub_out
    assert "Showing 2 of " in pub_out and "Note: this is demo data." in pub_out
    assert "faildex rules --store ~/.faildex/store" in pub_out
    assert f"--approve 1 2 --store {public_copy}" in pub_out

    # A relative `store/` directory with ingested private logs (no Source nodes) is not public.
    local_priv = tmp_path / "other_proj" / "store"
    db2 = relate.connect(str(local_priv))
    ingest(db2, _records())
    db2.commit()
    db2.flush()
    db2.close()
    monkeypatch.chdir(tmp_path / "other_proj")
    assert main(["rules", "--store", "store"]) == 0
    rel_out = capsys.readouterr().out
    assert rel_out.startswith("Store (store):") and "Public demo" not in rel_out


def test_rules_lines_fit_80_columns_on_the_public_store(monkeypatch, capsys):
    from pathlib import Path

    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    assert main(["rules", "--store", "store", "--top", "25"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Public demo logs (./store): 422 sessions")
    assert [line for line in out if len(line) > 80] == []
    assert "a later try worked in" in "\n".join(out)


def test_rules_mark_failures_shared_by_several_commands():
    from collections import Counter

    from faildex.insight import Failure, render

    item = Failure(
        sig="command timed out after <n> milliseconds",
        kind="text",
        calls=5,
        sessions={"s1", "s2", "s3"},
        commands=Counter({"Get-ChildItem": 3, "rg": 2}),
        fixes=Counter({"retry": 2}),
        recovered=2,
    )
    out = render([item])
    assert out.startswith("1. `Get-ChildItem` +1 more command — command timed out")
    # The counts cover both commands, so the action must not pin them on one.
    assert "Action: retry the same command; a later try worked in 2 of 2 recoveries." in out


def test_rules_quote_a_store_path_with_spaces_in_the_next_step(tmp_path, capsys):
    import os
    import shlex

    store = tmp_path / "my logs"
    db = relate.connect(str(store))
    ingest(db, _records())
    db.commit()
    db.flush()
    db.close()
    assert main(["rules", "--store", str(store)]) == 0
    last = capsys.readouterr().out.splitlines()[-1]
    if os.name == "nt":
        assert f'--store "{store}" --to' in last
    else:
        assert f"--store {shlex.quote(str(store))} --to" in last
        words = shlex.split(last.split(": ", 1)[1])
        assert words[words.index("--store") + 1] == str(store)


def test_zsh_equals_expansion_pools_across_commands_and_legacy_keys():
    """`(eval):1: ===== not found` is the shell's, whatever command it hit, like NOMATCH."""
    from faildex.insight import proposals, warnings_for_line

    db = relate.connect(":memory:")
    records = [_call(f"ok{n}", 0, command="cat") for n in range(200)]
    records += [
        _call("a", 0, ok=False, command="cat", sig="(eval):<n>: ===== not found"),
        _call("b", 0, ok=False, command="echo", sig="(eval):<n>: ==== not found"),
        _call("c", 0, ok=False, command="sed", sig="=<word> not found"),
    ]
    ingest(db, records)
    for command in ["echo =====", "cat x && echo '---' && echo ====", '[ "$a" == b ]']:
        _, pairs = warnings_for_line(db, command)
        assert [(t, w.sig) for t, w in pairs] == [("zsh", "=<word> not found")], command
        assert pairs[0][1].sessions == {"claude_code:a", "claude_code:b", "claude_code:c"}
    for command in ["echo '====='", "cat x", "[[ $a == b ]]", "echo a==b"]:
        assert warnings_for_line(db, command)[1] == [], command
    assert [p.sig for p in proposals(db)] == ["=<word> not found"]
    db.close()
