"""Hook behaviour after a failed shell call, on the public store and on zsh glob fixtures."""

import json
from pathlib import Path

import relate
from payloads import failed, git_status

from faildex.adapters.claude_code import read_dir, read_session
from faildex.hook import respond
from faildex.schema import ingest

GLOB_FIXTURES = Path(__file__).parent / "fixtures" / "zsh_glob"
GLOB_SIG = "no matches found: <glob>"
POST = "PostToolUseFailure"


def _glob_store(tmp_path):
    """A store built only from the zsh glob fixtures, so the failure recurs across sessions."""
    store = tmp_path / "globstore"
    db = relate.connect(str(store))
    ingest(db, read_dir(GLOB_FIXTURES), local_paths=True)
    db.commit()
    db.flush()
    db.close()
    return store


def _answer(out: str) -> None:
    """Silence, or a PostToolUseFailure notice: never anything else."""
    assert out == "" or json.loads(out)["hookSpecificOutput"]["hookEventName"] == POST


def test_hook_takes_scripts_containing_double_lt_without_error(public_copy):
    for command in [
        "git status <<'EOF'\nhello\nEOF",
        "cat <<EOF | git status\n$(private_customer_command)\nEOF",
        "echo '<<' && git status",
        "git status # <<",
        "cat <<< 'hello' && git status",
        "cat <<-EOF\n\t$(private_customer_command)\n\tEOF\ngit status",
        "cat <<EOF | grep x",
    ]:
        out = respond(git_status(command), public_copy)
        _answer(out)
        assert "private_customer_command" not in out


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
        _answer(respond(failed(command, "zsh:1: no matches found: *.x"), store))
        cursor_out = json.loads(respond(json.dumps({"command": command}), store, agent="cursor"))
        assert cursor_out == {"permission": "allow"}
        assert time.monotonic() - started < 0.5


def test_an_unwritable_log_does_not_hide_the_warning(tmp_path, public_copy):
    blocker = tmp_path / "file"
    blocker.write_text("")
    out = respond(git_status(), public_copy, log=blocker / "hook.jsonl")
    assert out and "git status" in json.loads(out)["systemMessage"]
