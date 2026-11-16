"""Pre-run warning for Claude Code (PreToolUse hook).

Reads the hook's JSON from stdin. When the command about to run has a failure
that recurred across sessions, prints the known facts as `additionalContext`.
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
from pathlib import Path

from faildex.normalize import command_template

SHELL_TOOLS = frozenset(["Bash"])
MAX_WARNINGS = 2


def context_for(db, payload: object, min_sessions: int = 2) -> str | None:
    """The text to hand the agent before this tool call, or None for nothing."""
    from faildex.insight import warnings_for

    if not isinstance(payload, dict) or payload.get("tool_name") not in SHELL_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    template = command_template(command) if isinstance(command, str) else None
    if not template:
        return None
    found = warnings_for(db, template, min_sessions)[:MAX_WARNINGS]
    if not found:
        return None
    lines = [f"faildex: `{template}` has failed the same way in earlier sessions."]
    lines += [f"- {item.rule()}" for item in found]
    return "\n".join(lines)


def respond(raw: str, store: Path, min_sessions: int = 2) -> str:
    """Hook stdout for one stdin payload; empty when there is nothing to say."""
    try:
        from faildex.store import open_store

        payload = json.loads(raw)
        db = open_store(store)
        try:
            context = context_for(db, payload, min_sessions)
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - see module docstring
        return ""
    if not context:
        return ""
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context}}
    )
