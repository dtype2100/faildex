"""The Claude Code hook right after a failed shell call (PostToolUseFailure).

The failure is keyed as the store keys it, looked up for the same command template,
and told when other sessions (not the hook's own session or its subagents) had it in
at least `min_sessions` sessions. Anything else is silence, including every payload
before a command (PreToolUse, Codex, Cursor): faildex warns no agent before a run.
"""

import io
import json
import sys
from pathlib import Path

import pytest

from faildex import index, refresh
from faildex.cli import main
from faildex.hook import respond

FIXTURES = Path(__file__).parent / "fixtures" / "post_failure"

PUSH_ERROR = "fatal: the current branch has no upstream branch"
CONFIG_ERROR = "error: config value missing"
NPM_ERROR = "npm ERR! cipm can only install with a lockfile"
TF_ERROR = "Error: No configuration files"
KO_ERROR = "error: 메모.txt를 열 수 없습니다"
SESSION = "sess-me"


def _session(path: Path, session: str, calls, agent: str | None = None) -> None:
    """A Claude Code transcript with these Bash calls; an error text marks a failure. With
    `agent`, it is that subagent's transcript under `session`."""
    lines = []
    for n, (command, error) in enumerate(calls):
        stamp = f"2026-11-17T09:{n // 60:02d}:{n % 60:02d}.000Z"
        base = {"sessionId": session, "timestamp": stamp}
        if agent:
            base |= {"isSidechain": True, "agentId": agent}
        use = f"{session}-{agent}-{n}"
        lines.append(
            base
            | {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": f"toolu_{use}",
                            "name": "Bash",
                            "input": {"command": command},
                        }
                    ],
                },
            }
        )
        lines.append(
            base
            | {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"toolu_{use}",
                            "is_error": error is not None,
                            "content": f"Exit code 1\n{error}" if error else "ok",
                        }
                    ],
                },
            }
        )
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    """A store from made-up logs.

    The hook runs in session `me` (SESSION), whose own failures a refresh has already
    stored. `git push` fails with PUSH_ERROR in sessions a, b and c, each getting past
    it by running `git branch` first, and in `me` and its subagent `x`, twice each.
    `make` fails with CONFIG_ERROR in sessions a and b and works on the next try; d
    runs it 100 times without a failure, so the failure is under 3% of its runs.
    `npm ci` fails in session a only, and `cargo build` only in `me` and `x`.
    `terraform plan` fails with TF_ERROR in a and b with no way out, and in `me`, which
    got past it by running `cd` (into the right folder) first.
    """
    base = tmp_path_factory.mktemp("seeded")
    logs = base / "logs"
    logs.mkdir()
    push = [("git push", PUSH_ERROR), ("git branch", None), ("git push", None)]
    for name in ("a", "b", "c"):
        calls = push + [("make", CONFIG_ERROR), ("make", None)] if name != "c" else push
        if name == "a":
            calls = calls + [("npm ci", NPM_ERROR)]
        if name in ("a", "b"):
            calls = calls + [("terraform plan", TF_ERROR), ("cat 메모.txt", KO_ERROR)]
        _session(logs / f"{name}.jsonl", f"sess-{name}", calls)
    _session(logs / "d.jsonl", "sess-d", [("make", None)] * 100)
    mine = [("git push", PUSH_ERROR), ("git push", PUSH_ERROR), ("cargo build", "error[E0425]")]
    terraform = [("terraform plan", TF_ERROR), ("cd infra", None), ("terraform plan", None)]
    _session(logs / "me.jsonl", SESSION, mine + terraform)
    _session(logs / "me-x.jsonl", SESSION, mine, agent="x")
    store = base / "store"
    with pytest.MonkeyPatch.context() as mp:  # module scope: before conftest's own home
        mp.setenv("HOME", str(base))
        mp.setenv("USERPROFILE", str(base))
        mp.setenv("XDG_CACHE_HOME", str(base / "cache"))
        assert main(["ingest", "--claude", str(logs), "--store", str(store)]) == 0
    return store


def _failed(command: str, error: str, session: str = SESSION, **extra) -> str:
    payload = {
        "session_id": session,
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_use_id": "toolu_now",
        "error": f"Exit code 1\n{error}",
        "is_interrupt": False,
    }
    return json.dumps(payload | extra)


def _said(out: str) -> dict:
    data = json.loads(out)
    assert set(data) == {"systemMessage", "hookSpecificOutput"}
    assert data["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"
    assert set(data["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    return data


# Key contract ---------------------------------------------------------------------------


def _inputs():
    data = json.loads((FIXTURES / "key_inputs.json").read_text(encoding="utf-8"))
    return [(row["input"], row["command"], row["error"]) for row in data["inputs"]]


def test_the_phase_1_inputs_are_all_here():
    rows = _inputs()
    assert len(rows) == 24 and len({name for name, _, _ in rows}) == 24


@pytest.mark.parametrize(("name", "command", "error"), _inputs(), ids=[r[0] for r in _inputs()])
def test_the_hook_keys_a_failure_as_the_store_does(tmp_path, name, command, error):
    from faildex.adapters.claude_code import failed_call, read_session

    transcript = tmp_path / "t.jsonl"
    use = {"type": "tool_use", "id": "toolu_x", "name": "Bash", "input": {"command": command}}
    result = {"type": "tool_result", "tool_use_id": "toolu_x", "is_error": True, "content": error}
    lines = [
        {"type": "assistant", "sessionId": "s", "message": {"role": "assistant", "content": [use]}},
        {"type": "user", "sessionId": "s", "message": {"role": "user", "content": [result]}},
    ]
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    (stored,) = read_session(transcript)
    hooked = failed_call(command, error, "s")
    assert (hooked.command, hooked.failure) == (stored.command, stored.failure)
    assert (hooked.exit_code, hooked.compound) == (stored.exit_code, stored.compound)


# What it says ---------------------------------------------------------------------------


def test_it_tells_the_precedent_and_the_step_on_record_in_english_without_paths(seeded):
    data = _said(respond(_failed("git push origin main", PUSH_ERROR), seeded))
    context = data["hookSpecificOutput"]["additionalContext"]
    assert context.isascii() and data["systemMessage"].isascii()
    assert f"`{PUSH_ERROR}`" in context
    assert "(seen in 3 sessions, 3 calls)" in context  # sess-me and its subagent left out
    assert "running `git branch` first (3 of 3 recoveries)" in context
    assert "not instructions" in context
    assert "in 3 earlier sessions" in data["systemMessage"]
    assert "\n" not in data["systemMessage"]
    out = json.dumps(data)
    assert str(seeded.parent) not in out and ".jsonl" not in out and "/" not in context


def test_the_words_are_english_whatever_language_the_person_chose(seeded, monkeypatch, capsys):
    monkeypatch.setenv("FAILDEX_LANG", "ko")
    monkeypatch.setattr(sys, "stdin", io.StringIO(_failed("git push", PUSH_ERROR)))
    assert main(["hook", "--store", str(seeded)]) == 0
    out = capsys.readouterr().out
    assert out.isascii() and "git branch" in _said(out)["hookSpecificOutput"]["additionalContext"]


def test_a_later_try_that_worked_is_not_offered_as_a_retry_for_a_lasting_error(seeded):
    context = _said(respond(_failed("make", CONFIG_ERROR), seeded))["hookSpecificOutput"]
    text = context["additionalContext"]
    assert "fix the cause, then run it again" in text and "retry it" not in text


def test_a_compound_line_gets_the_precedent_and_no_next_step(seeded):
    data = _said(respond(_failed("git push && echo pushed", PUSH_ERROR), seeded))
    context = data["hookSpecificOutput"]["additionalContext"]
    assert "(seen in 3 sessions, 3 calls)" in context and "no next step" in context
    assert "git branch" not in context and "git branch" not in data["systemMessage"]


def test_the_three_percent_share_does_not_apply_after_a_failure(seeded):
    """`make` failed in 2 of its 104 runs: too rare to warn before a run, told after one."""
    before = json.dumps({"tool_name": "Bash", "tool_input": {"command": "make"}})
    assert respond(before, seeded) == ""
    data = _said(respond(_failed("make", CONFIG_ERROR), seeded))
    assert "(seen in 2 sessions, 2 calls)" in data["hookSpecificOutput"]["additionalContext"]
    assert "of this command's" not in data["hookSpecificOutput"]["additionalContext"]


def test_min_sessions_is_honoured(seeded):
    assert respond(_failed("git push", PUSH_ERROR), seeded, min_sessions=4) == ""
    assert respond(_failed("git push", PUSH_ERROR), seeded, min_sessions=3)


# Silence --------------------------------------------------------------------------------


SPEAKS = _failed("git push", PUSH_ERROR)


def _changed(**extra) -> str:
    return json.dumps(json.loads(SPEAKS) | extra)


SILENT = {
    "not Bash": _changed(tool_name="Read", tool_input={"command": "git push"}),
    "error not a string": _changed(error=None),
    "error a number": _changed(error=1),
    "error empty": _changed(error=""),
    "error blank": _changed(error="  \n"),
    "interrupted": _changed(is_interrupt=True),
    "exit 130": _changed(error=f"Exit code 130\n{PUSH_ERROR}"),
    "exit 143": _changed(error=f"Exit code 143\n{PUSH_ERROR}"),
    "stdin over the limit": _changed(padding="x" * 1_000_000),  # 1 MB
    "no key (grep found nothing)": _changed(
        tool_input={"command": "grep -r nothing ."}, error="Exit code 1"
    ),
    "no command": _changed(tool_input={"command": "   "}),
    "a key with no match": _failed("git push", "fatal: unable to access the remote"),
    "the same key for another command": _failed("git pull", PUSH_ERROR),
    "a precedent in one other session": _failed("npm ci", NPM_ERROR),
    "only the hook's own session and subagent": _failed("cargo build", "error[E0425]"),
}


def test_the_payload_that_speaks_speaks(seeded):
    assert _said(respond(SPEAKS, seeded))


@pytest.mark.parametrize("case", sorted(SILENT))
def test_silence(seeded, case):
    assert respond(SILENT[case], seeded) == ""


def test_the_own_session_and_its_subagents_are_left_out_of_the_counts(seeded):
    """Session `me` and `me/agent-x` failed `git push` twice each: from another session they
    count, from `me` they do not; and `me` alone never makes a precedent for itself."""
    assert "(seen in 5 sessions, 7 calls)" in respond(
        _failed("git push", PUSH_ERROR, "new"), seeded
    )
    assert "(seen in 3 sessions, 3 calls)" in respond(_failed("git push", PUSH_ERROR), seeded)
    cargo = ("cargo build", "error[E0425]")
    assert respond(_failed(*cargo), seeded, min_sessions=1) == ""
    # From a new session, `me` and its subagent are one other conversation: not two.
    assert respond(_failed(*cargo, "new"), seeded) == ""
    one = respond(_failed(*cargo, "new"), seeded, min_sessions=1)
    assert "(seen in 2 sessions, 2 calls)" in one  # the words count stored sessions


def test_the_own_sessions_recoveries_are_not_offered_as_earlier_sessions(seeded):
    """Only `me` got past the terraform failure: from `me`, the other two sessions have
    no recovery on record; from a new session, `me`'s recovery counts."""
    data = _said(respond(_failed("terraform plan", TF_ERROR), seeded))
    context = data["hookSpecificOutput"]["additionalContext"]
    assert "(seen in 2 sessions, 2 calls): no recovery on record" in context
    assert "`cd`" not in context and "`cd`" not in data["systemMessage"]
    other = respond(_failed("terraform plan", TF_ERROR, "new"), seeded)
    assert "running `cd` first (1 of 1 recoveries)" in other


def test_a_payload_that_is_not_json_is_silent(seeded):
    assert respond('{"hook_event_name": "PostToolUseFailure", ', seeded) == ""


# Sources --------------------------------------------------------------------------------


def test_the_index_answers_without_opening_the_store(seeded, monkeypatch):
    import relate

    assert index.candidates(seeded)  # ingest wrote it
    expected = respond(SPEAKS, seeded)
    assert _said(expected)

    def refuse(*args, **kwargs):
        raise AssertionError("the store was opened")

    monkeypatch.setattr(relate, "connect", refuse)
    assert respond(SPEAKS, seeded) == expected


def test_a_damaged_index_falls_back_to_the_store(seeded, tmp_path):
    import shutil

    store = tmp_path / "store"
    shutil.copytree(seeded, store)
    shutil.copy2(index.beside(seeded), index.beside(store))
    expected = respond(SPEAKS, store)
    assert _said(expected)
    path = index.beside(store)
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["commands"]["git push"]["failures"]:
        row["sessions"] = "abc"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert index.candidates(store)  # still taken as an index ...
    assert respond(SPEAKS, store) == expected  # ... and its damaged entry skipped


def test_the_index_keeps_failed_calls_per_session(seeded):
    (found,) = index.candidates(seeded)
    _, items = found.command_failures("git push")
    (item,) = items
    assert dict(item.session_calls) == {
        "claude-code:sess-a": 1,
        "claude-code:sess-b": 1,
        "claude-code:sess-c": 1,
        "claude-code:sess-me": 2,
        "claude-code:sess-me/agent-x": 2,
    }


# The pre-run path -----------------------------------------------------------------------


def _old_cases():
    """The payloads whose output e2c4ae6 pinned (PreToolUse, Codex, Cursor), now all silent."""
    return json.loads((FIXTURES / "pre_outputs.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("n", range(len(_old_cases())))
def test_no_warning_before_a_command_for_any_agent(public_copy, n):
    case = _old_cases()[n]
    out = respond(json.dumps(case["payload"]), public_copy, agent=case["agent"])
    assert out == ('{"permission": "allow"}' if case["agent"] == "cursor" else "")


# The CLI --------------------------------------------------------------------------------


def test_the_cli_answers_a_failure_and_nothing_before_a_command(seeded, monkeypatch, capsys):
    for raw, expected in (
        (SPEAKS, True),
        (json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}}), False),
        (
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git push"},
                }
            ),
            False,
        ),
    ):
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
        assert main(["hook", "--store", str(seeded)]) == 0
        out = capsys.readouterr().out
        assert bool(out) is expected
        if expected:
            assert _said(out)


def test_refresh_every_counts_only_failures(seeded, monkeypatch, capsys):
    noted = []
    monkeypatch.setattr(refresh, "note", lambda store, every: noted.append(store))
    before = json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    )
    for raw in (before, SPEAKS, before):
        monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
        assert main(["hook", "--store", str(seeded), "--refresh-every", "200"]) == 0
    assert noted == [seeded]


def test_refresh_every_counts_failed_calls(seeded, monkeypatch, capsys):
    noted = []
    monkeypatch.setattr(refresh, "note", lambda store, every: noted.append((store, every)))
    monkeypatch.setattr(sys, "stdin", io.StringIO(SPEAKS))
    assert main(["hook", "--store", str(seeded), "--refresh-every", "200"]) == 0
    assert _said(capsys.readouterr().out)
    assert noted == [(seeded, 200)]


def test_the_log_notes_a_warning_after_a_failure_without_the_error(seeded, tmp_path):
    log = tmp_path / "hook.jsonl"
    assert respond(SPEAKS, seeded, log=log)
    (entry,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert set(entry) == {"ts", "command", "warnings", "event"}
    assert (entry["command"], entry["warnings"], entry["event"]) == ("git push", 1, "post-failure")
    assert PUSH_ERROR not in log.read_text()


def test_stored_text_is_handed_on_without_control_characters_and_capped():
    from faildex.hook import MAX_LINE, _clean

    assert _clean("a\x1b[31mb\x07c" + chr(0x202E) + "d\n") == "a [31mb c d "
    long = _clean("x" * (MAX_LINE * 2))
    assert len(long) == MAX_LINE and long.endswith("…")


# --refresh-every on the error paths, and the stdin bound ---------------------------------


def test_refresh_every_with_a_store_that_cannot_be_chosen_stays_quiet(monkeypatch, capsys):
    from faildex import cli

    def broken(args):
        raise RuntimeError("Symlink loop from '~/.faildex/store'")

    monkeypatch.setattr(cli, "_hook_store", broken)
    monkeypatch.setattr(sys, "stdin", io.StringIO(SPEAKS))
    assert main(["hook", "--refresh-every", "200"]) == 0
    out = capsys.readouterr()
    assert (out.out, out.err) == ("", "")


def test_refresh_every_with_stdin_that_is_not_utf8_stays_quiet(seeded, monkeypatch, capsys):
    noted = []
    monkeypatch.setattr(refresh, "note", lambda store, every: noted.append(store))
    stdin = io.TextIOWrapper(io.BytesIO(b'{"error": "\xff\xfe"}'), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert main(["hook", "--store", str(seeded), "--refresh-every", "200"]) == 0
    out = capsys.readouterr()
    assert (out.out, out.err, noted) == ("", "", [])


def test_stdin_is_read_up_to_the_bound_and_a_longer_payload_is_not_counted(
    seeded, monkeypatch, capsys
):
    from faildex.hook import MAX_STDIN

    asked = []

    class Stdin(io.StringIO):
        def read(self, size=-1):
            asked.append(size)
            return super().read(size)

    noted = []
    monkeypatch.setattr(refresh, "note", lambda store, every: noted.append(store))
    long = json.dumps({**json.loads(SPEAKS), "padding": "x" * MAX_STDIN})
    monkeypatch.setattr(sys, "stdin", Stdin(long))
    assert main(["hook", "--store", str(seeded), "--refresh-every", "200"]) == 0
    assert capsys.readouterr().out == "" and noted == []
    assert asked == [MAX_STDIN + 1]


def test_the_payload_is_parsed_once(seeded, monkeypatch, capsys):
    from faildex import hook

    real, parsed = json.loads, []

    def loads(text, *args, **kwargs):
        if text == SPEAKS:
            parsed.append(1)
        return real(text, *args, **kwargs)

    monkeypatch.setattr(hook.json, "loads", loads)
    monkeypatch.setattr(refresh, "note", lambda store, every: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(SPEAKS))
    assert main(["hook", "--store", str(seeded), "--refresh-every", "200"]) == 0
    assert _said(capsys.readouterr().out) and parsed == [1]


def test_a_parent_and_its_subagent_in_one_other_conversation_are_one_precedent(seeded):
    """`cargo build` failed only in `me` and `me/agent-x`: one conversation."""
    cargo = ("cargo build", "error[E0425]")
    assert respond(_failed(*cargo, "someone-else"), seeded) == ""
    assert respond(_failed(*cargo, "someone-else"), seeded, min_sessions=1)


def test_korean_text_arrives_whole_whatever_the_console_code_page(seeded, monkeypatch, capsys):
    """Read as bytes and decoded as UTF-8: a Windows code page does not mangle it."""
    from faildex.adapters.claude_code import failed_call

    raw = json.dumps(json.loads(_failed("cat 메모.txt", KO_ERROR)), ensure_ascii=False)
    assert "메모" in raw  # raw UTF-8 bytes on stdin, not \\u escapes
    stdin = io.TextIOWrapper(io.BytesIO(raw.encode("utf-8")), encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert main(["hook", "--store", str(seeded)]) == 0
    data = _said(capsys.readouterr().out)
    key = failed_call("cat 메모.txt", f"Exit code 1\n{KO_ERROR}").failure[0]
    assert key in data["hookSpecificOutput"]["additionalContext"]
    assert "를 열 수 없습니다" in key


def test_a_payload_over_the_byte_bound_is_silent(seeded, monkeypatch, capsys):
    from faildex.hook import MAX_STDIN

    raw = json.dumps(
        {**json.loads(SPEAKS), "padding": "가" * (MAX_STDIN // 3 + 1)}, ensure_ascii=False
    )
    assert len(raw) < MAX_STDIN < len(raw.encode("utf-8"))  # short in characters, long in bytes
    stdin = io.TextIOWrapper(io.BytesIO(raw.encode("utf-8")), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert main(["hook", "--store", str(seeded)]) == 0
    assert capsys.readouterr().out == ""
