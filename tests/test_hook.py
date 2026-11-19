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


def test_compound_lines_are_looked_up_part_by_part():
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls && git status"}})
    out = respond(payload, STORE)
    assert out and "git status" in json.loads(out)["systemMessage"]


def test_top_limits_the_warnings_and_zero_silences():
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git status"}})
    assert respond(payload, STORE, top=0) == ""


def test_zsh_glob_fixtures_record_one_shared_failure():
    """The two sessions hit the same NOMATCH key under `ls`, across all three constructs."""
    records = list(read_dir(GLOB_FIXTURES))
    assert len(records) == 6
    assert {r.session_id for r in records} == {"sess-glob-a", "sess-glob-b"}
    assert {r.command for r in records} == {"ls"}
    assert {r.error_sig for r in records} == {GLOB_SIG}
    # One call per construct in each session (for-loop, subshell, substitution).
    assert [r.command for r in read_session(GLOB_FIXTURES / "sess-glob-a.jsonl")] == ["ls"] * 3


def _glob_store(tmp_path):
    """A store built only from the zsh glob fixtures, so the failure is frequent enough to warn."""
    store = tmp_path / "globstore"
    db = relate.connect(str(store))
    ingest(db, read_dir(GLOB_FIXTURES), local_paths=True)
    db.commit()
    db.flush()
    db.close()
    return store


def _bash(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def test_hook_warns_for_glob_in_for_subshell_and_substitution(tmp_path):
    """A zsh glob inside `for … do … done`, `( … )`, or `$(…)` is a known recurring failure."""
    store = _glob_store(tmp_path)
    for command in GLOB_CASES:
        out = respond(_bash(command), store)
        assert out, command
        message = json.loads(out)["systemMessage"]
        assert GLOB_SIG in message, command
        assert "`ls`" in message, command
    # The session line that first missed the warning: loop + subshell + substitution together.
    combined = 'cd ~ && for d in a b; do ( cd "$d" && { git log -1; f=$(ls README* readme* | head -1); } ); done'
    out = respond(_bash(combined), store)
    assert out and GLOB_SIG in json.loads(out)["systemMessage"]
