import json
from pathlib import Path

import pytest

from faildex.cli import main
from faildex.hook import respond
from faildex.link import link, unlink

STORE = Path(__file__).resolve().parents[1] / "store"


@pytest.mark.parametrize(
    "agent,key", [("codex", "hookSpecificOutput"), ("cursor", "additional_context")]
)
def test_session_rules_exclude_evidence(agent, key, tmp_path):
    rules = tmp_path / "rules.md"
    rules.write_text("# Rules\n- quote globs\n  Evidence: /private/log:1\n  Fix: use quotes\n")
    out = json.loads(respond("{}", STORE, agent=agent, event="session-start", rules=rules))
    context = out[key]
    if agent == "codex":
        assert context["hookEventName"] == "SessionStart"
        context = context["additionalContext"]
    assert "quote globs" in context and "Fix: use quotes" in context
    assert "Evidence" not in context and "/private/log" not in context


@pytest.mark.parametrize("agent", ["codex", "cursor"])
def test_shell_warning_uses_agent_protocol(agent):
    payload = (
        {"command": "git status"}
        if agent == "cursor"
        else {"tool_name": "Bash", "tool_input": {"command": "git status"}}
    )
    out = json.loads(respond(json.dumps(payload), STORE, agent=agent))
    if agent == "cursor":
        assert out["permission"] == "allow"
        assert "faildex" in out["user_message"] and "git status" in out["agent_message"]
    else:
        assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "git status" in out["hookSpecificOutput"]["additionalContext"]


def test_cursor_errors_still_allow_execution(tmp_path):
    assert json.loads(respond("broken", tmp_path, agent="cursor")) == {"permission": "allow"}


def test_link_preserves_hooks_backs_up_and_removes_only_faildex(tmp_path):
    original = {}
    for folder, event in [(".codex", "SessionStart"), (".cursor", "sessionStart")]:
        p = tmp_path / folder / "hooks.json"
        p.parent.mkdir()
        original[p] = {"version": 1, "other": "keep", "hooks": {event: [{"command": "herdr hook"}]}}
        p.write_text(json.dumps(original[p]))
    rules = tmp_path / "rules.md"
    link(rules, tmp_path)
    after = {p: p.read_bytes() for p in original}
    for p, before in original.items():
        assert any(
            json.loads(b.read_text()) == before for b in p.parent.glob("hooks.json.faildex-backup*")
        )
        assert json.loads(p.read_text())["other"] == "keep"
    link(rules, tmp_path)
    assert {p: p.read_bytes() for p in original} == after
    # Unrelated hooks added after installation must survive removal too.
    for p in original:
        data = json.loads(p.read_text())
        data["hooks"]["unrelated"] = [{"command": "orca hook"}]
        p.write_text(json.dumps(data))
    unlink(rules, tmp_path)
    for p, before in original.items():
        data = json.loads(p.read_text())
        hooks = data.pop("hooks")
        assert hooks.pop("unrelated") == [{"command": "orca hook"}]
        assert hooks == before["hooks"]
        assert data == {k: v for k, v in before.items() if k != "hooks"}
        assert "faildex hook" not in p.read_text()


def test_malformed_hooks_are_not_overwritten(tmp_path):
    p = tmp_path / ".codex/hooks.json"
    p.parent.mkdir()
    p.write_text("not json")
    link(tmp_path / "rules.md", tmp_path)
    assert p.read_text() == "not json"


def test_failed_hook_config_write_keeps_existing_hooks(tmp_path, monkeypatch):
    from faildex.agent_hooks import configure

    p = tmp_path / "hooks.json"
    original = '{"hooks":{"SessionStart":[{"command":"herdr hook"}]}}'
    p.write_text(original, encoding="utf-8")

    def fail_replace(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail_replace)
    status, _ = configure("codex", p, tmp_path / "rules.md", False, False)
    assert status == "skipped"
    assert p.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("agent,event", [("codex", "SessionStart"), ("cursor", "sessionStart")])
def test_registered_command_reads_literal_special_path(agent, event, tmp_path, monkeypatch, capsys):
    import io

    from faildex.agent_hooks import configure

    rules = tmp_path / "O'Brien $data & 규칙.md"
    rules.write_text("- quote globs\n", encoding="utf-8")
    p = tmp_path / "hooks.json"
    configure(agent, p, rules, False, False)
    entry = json.loads(p.read_text(encoding="utf-8"))["hooks"][event][0]
    command = entry["hooks"][0]["command"] if agent == "codex" else entry["command"]
    assert all(ch.isascii() and (ch.isalnum() or ch in " -_=") for ch in command)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert main(command.split()[1:]) == 0
    out = json.loads(capsys.readouterr().out)
    context = (
        out["hookSpecificOutput"]["additionalContext"]
        if agent == "codex"
        else out["additional_context"]
    )
    assert context == "- quote globs\n"


def test_cli_cursor_session_hook(tmp_path, monkeypatch, capsys):
    import io

    rules = tmp_path / "rules.md"
    rules.write_text("- quote globs\n  Evidence: secret\n")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert (
        main(["hook", "--agent", "cursor", "--event", "session-start", "--rules", str(rules)]) == 0
    )
    assert json.loads(capsys.readouterr().out) == {"additional_context": "- quote globs\n"}
