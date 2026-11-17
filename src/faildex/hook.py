"""Pre-run warning for Claude Code (PreToolUse hook).

Reads the hook's JSON from stdin. When the command about to run has a failure
that recurred across sessions, it gives the agent the known facts as
`additionalContext` and shows the person one line (`systemMessage`), which
Claude Code prints under the command.
It never decides permission, never blocks, and stays silent (exit 0, no output)
for unknown commands and on any error: a warning tool must not be able to break
the session it is watching.

Register it in `.claude/settings.json`:

    {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "faildex hook --store /path/to/store", "timeout": 5}
    ]}]}}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from faildex.normalize import command_template

SHELL_TOOLS = frozenset(["Bash"])
MAX_WARNINGS = 2


def _lookup(db, payload: object, min_sessions: int) -> tuple[str | None, list]:
    """(command template, its recurring failures) for a shell call; (None, []) otherwise."""
    from faildex.insight import warnings_for

    if not isinstance(payload, dict) or payload.get("tool_name") not in SHELL_TOOLS:
        return None, []
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    template = command_template(command) if isinstance(command, str) else None
    if not template:
        return None, []
    return template, warnings_for(db, template, min_sessions)[:MAX_WARNINGS]


def _context(template: str, found: list) -> str:
    lines = [f"faildex: `{template}` has failed the same way in earlier sessions."]
    lines += [f"- {item.rule()}" for item in found]
    return "\n".join(lines)


def context_for(db, payload: object, min_sessions: int = 2) -> str | None:
    """The text to hand the agent before this tool call, or None for nothing."""
    template, found = _lookup(db, payload, min_sessions)
    return _context(template, found) if found else None


def notice_for(found: list) -> str:
    """The one line the person sees in the session, above the command's result."""
    more = f" (+{len(found) - 1} more for the agent)" if len(found) > 1 else ""
    return found[0].notice() + more


def _log(path: Path, payload: dict, context: str) -> None:
    """Note that a warning was given: when and for which command template, nothing more."""
    command = payload.get("tool_input", {}).get("command")
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": command_template(command) if isinstance(command, str) else None,
        "warnings": context.count("\n- "),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write(json.dumps(entry) + "\n")


def respond(raw: str, store: Path, min_sessions: int = 2, log: Path | None = None) -> str:
    """Hook stdout for one stdin payload; empty when there is nothing to say."""
    try:
        from faildex.store import open_store

        payload = json.loads(raw)
        db = open_store(store)
        try:
            template, found = _lookup(db, payload, min_sessions)
        finally:
            db.close()
        if not found:
            return ""
        context = _context(template, found)
        if log:
            _log(log, payload, context)
    except Exception:  # noqa: BLE001 - see module docstring
        return ""
    return json.dumps(
        {
            "systemMessage": notice_for(found),
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context},
        }
    )
