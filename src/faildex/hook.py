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


def _lookup(
    db, payload: object, min_sessions: int, top: int = MAX_WARNINGS
) -> tuple[str | None, list]:
    """(command template, its recurring failures) for a shell call; (None, []) otherwise.

    Every part of a compound line is looked up (`ls && git status` warns for git).
    """
    from faildex.insight import warnings_for_line

    if not isinstance(payload, dict) or payload.get("tool_name") not in SHELL_TOOLS:
        return None, []
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None, []
    _, pairs = warnings_for_line(db, command, min_sessions)
    pairs = pairs[: max(0, top)]
    if not pairs:
        return None, []
    return pairs[0][0], [item for _, item in pairs]


def _context(template: str, found: list) -> str:
    lines = [f"faildex: `{template}` has failed the same way in earlier sessions."]
    lines += [f"- {item.rule()}" for item in found]
    return "\n".join(lines)


def context_for(db, payload: object, min_sessions: int = 2, top: int = MAX_WARNINGS) -> str | None:
    """The text to hand the agent before this tool call, or None for nothing."""
    template, found = _lookup(db, payload, min_sessions, top)
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


def respond(
    raw: str,
    store: Path,
    min_sessions: int = 2,
    log: Path | None = None,
    top: int = MAX_WARNINGS,
    *,
    agent: str = "claude",
    event: str = "pre-shell",
    rules: Path | None = None,
) -> str:
    """Hook stdout for one stdin payload; empty when there is nothing to say."""
    quiet = json.dumps({"permission": "allow"}) if agent == "cursor" else ""
    try:
        if event == "session-start":
            text = (rules or Path("~/faildex-rules.md")).expanduser().read_text(encoding="utf-8")
            text = "".join(
                line
                for line in text.splitlines(keepends=True)
                if not line.lstrip().lower().startswith("evidence:")
            )
            if agent == "cursor":
                return json.dumps({"additional_context": text})
            return json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": text,
                    }
                }
            )
        from faildex.store import open_store

        payload = json.loads(raw)
        if agent == "cursor" and isinstance(payload, dict):
            payload = {"tool_name": "Bash", "tool_input": {"command": payload.get("command")}}
        db = open_store(store)
        try:
            template, found = _lookup(db, payload, min_sessions, top)
        finally:
            db.close()
        if not found:
            return quiet
        context = _context(template, found)
        if log:
            _log(log, payload, context)
    except Exception:  # noqa: BLE001 - see module docstring
        return json.dumps({}) if event == "session-start" and agent == "cursor" else quiet
    if agent == "cursor":
        return json.dumps(
            {
                "permission": "allow",
                "user_message": notice_for(found),
                "agent_message": context,
            }
        )
    return json.dumps(
        {
            "systemMessage": notice_for(found),
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context},
        }
    )
