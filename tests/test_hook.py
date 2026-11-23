"""Hook behaviour on the public store that ships in the repository."""

import json
from pathlib import Path

import relate

from faildex.adapters.claude_code import read_dir, read_session
from faildex.hook import respond
from faildex.schema import ingest

STORE = Path(__file__).resolve().parents[1] / "store"
GLOB_FIXTURES = Path(__file__).parent / "fixtures" / "zsh_glob"
GLOB_SIG = "no matches found: <glob>"

# One command line per construct from issue #10. The hook must warn on each.
GLOB_CASES = [
    "for f in *.x; do ls README*; done",
    "( ls README* readme* )",
    "f=$(ls README* readme* | head -1)",
]


def _glob_store(tmp_path):
    """A store built only from the zsh glob fixtures, so the failure recurs across sessions."""
    store = tmp_path / "globstore"
    db = relate.connect(str(store))
    ingest(db, read_dir(GLOB_FIXTURES), local_paths=True)
    db.commit()
    db.flush()
    db.close()
    return store


def _bash(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def test_compound_lines_are_looked_up_part_by_part():
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls && git status"}})
    out = respond(payload, STORE)
    assert out and "git status" in json.loads(out)["systemMessage"]


def test_top_limits_the_warnings_and_zero_silences():
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    assert respond(payload, STORE, top=0) == ""


def test_hook_skips_scripts_containing_double_lt_without_error():
    for command in [
        "git status <<'EOF'\nhello\nEOF",
        "cat <<EOF | git status\n$(private_customer_command)\nEOF",
        "echo '<<' && git status",
        "git status # <<",
        "cat <<< 'hello' && git status",
        "cat <<-EOF\n\t$(private_customer_command)\n\tEOF\ngit status",
        "cat <<EOF | grep x",
    ]:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        assert respond(payload, STORE) == ""
        cursor_out = json.loads(respond(json.dumps({"command": command}), STORE, agent="cursor"))
        assert cursor_out == {"permission": "allow"}


def test_zsh_glob_fixtures_record_one_shared_failure():
    """Both sessions share the pooled NOMATCH signature across all three constructs."""
    records = list(read_dir(GLOB_FIXTURES))
    assert len(records) == 6
    assert {r.session_id for r in records} == {"sess-glob-a", "sess-glob-b"}
    assert {r.error_sig for r in records} == {GLOB_SIG}
    assert [r.command for r in read_session(GLOB_FIXTURES / "sess-glob-a.jsonl")] == [
        None,
        "ls",
        None,
    ]


def test_hook_warns_for_glob_in_for_subshell_and_substitution(tmp_path):
    """A zsh glob inside `for … do … done`, `( … )`, or `$(…)` triggers the pooled warning."""
    store = _glob_store(tmp_path)
    for command in GLOB_CASES:
        out = respond(_bash(command), store)
        assert out, command
        message = json.loads(out)["systemMessage"]
        assert GLOB_SIG in message, command
        assert "`zsh`" in message, command
    # The issue #10 session line: loop + subshell + substitution together.
    combined = 'cd ~ && for d in a b; do ( cd "$d" && { git log -1; f=$(ls README* readme* | head -1); } ); done'
    out = respond(_bash(combined), store)
    assert out and GLOB_SIG in json.loads(out)["systemMessage"]


def test_hook_is_silent_for_quoted_globs_and_false_positives(tmp_path):
    store = _glob_store(tmp_path)
    for command in [
        "ls '*.py'",
        'ls "*.py"',
        r"ls \*.py",
        'echo "a \\"*.private"',
        "[ -f a ] && git status",
        "cat <<'EOF'\n$(ls README*)\nEOF",
    ]:
        assert respond(_bash(command), store) == "", command


def test_hook_handles_long_adversarial_inputs_quickly(tmp_path):
    import time

    store = _glob_store(tmp_path)
    cases = [
        "a" * 12000,
        "a \\\n" * 3000,
        "env \\\n" * 2000 + "ls",
        "foo() " + "\\\n" * 5000 + "{\nls *.x\n}",
        "( (" * 1800 + "ls *.x" + ") )" * 1800,
        "$(" * 5500,
        "$((" * 3500,
        "[" * 12000,
        r"echo \$'a' " * 1200,
    ]
    for command in cases:
        started = time.monotonic()
        assert respond(_bash(command), store) == ""
        cursor_out = json.loads(respond(json.dumps({"command": command}), store, agent="cursor"))
        assert cursor_out == {"permission": "allow"}
        assert time.monotonic() - started < 0.5


def test_an_unwritable_log_does_not_hide_the_warning(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    out = respond(_bash("git status"), STORE, log=blocker / "hook.jsonl")
    assert out and "git status" in json.loads(out)["systemMessage"]
