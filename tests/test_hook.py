"""Hook behaviour on the public store that ships in the repository."""

import json
from pathlib import Path

from faildex.hook import respond

STORE = Path(__file__).resolve().parents[1] / "store"


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
