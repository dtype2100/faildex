"""Pre-run warning for Claude Code (PreToolUse hook).

Reads the hook's JSON from stdin. When the command about to run has a failure
that recurred across sessions, it gives the agent the known facts as
`additionalContext` and shows the person one line (`systemMessage`), which
Claude Code prints under the command.
It never decides permission, never blocks, and stays silent (exit 0, no output)
for unknown commands and on any error: a warning tool must not be able to break
the session it is watching. It answers from the store's index without writing
anything. The only store files it ever writes are those of a store never opened on
this machine, prepared once as every faildex command does (`_open_source`): faildex's
own public demo store as its cache copy, never inside the package, and any other
store where it is, only if it looks like a Relate store.

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


def _shell_command(payload: object) -> str | None:
    """The command line of a shell tool call; None for anything else."""
    if not isinstance(payload, dict) or payload.get("tool_name") not in SHELL_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return command if isinstance(command, str) else None


def _lookup(
    source, payload: object, min_sessions: int, top: int = MAX_WARNINGS
) -> tuple[str | None, list]:
    """(command template, its recurring failures) for a shell call; (None, []) otherwise.

    `source` is the hook's index of a store, or a connection to the store itself; both
    answer through `insight.line_warnings`. Every part of a compound line is looked up
    (`ls && git status` warns for git).
    """
    from faildex.insight import warnings_for_line

    command = _shell_command(payload)
    if command is None:
        return None, []
    if hasattr(source, "warnings_for_line"):
        _, pairs = source.warnings_for_line(command, min_sessions)
    else:
        _, pairs = warnings_for_line(source, command, min_sessions)
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
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry) + "\n")


def _open_read_only(store: Path):
    """The store, read-only. Unlike `open_store`, never a writable first open: the hook
    must not create or change files in a store that an ingest may be replacing."""
    import relate

    if not (Path(store) / "manifest.json").is_file():
        raise FileNotFoundError(store)
    return relate.connect(str(store), read_only=True)


def _to_prepare(store: Path) -> Path | None:
    """What to prepare for a store that refuses a read-only open (never opened on this
    machine): faildex's own public demo store (shipped in the package or the checkout,
    or its cache copy) through its cache copy, never inside the package; any other
    folder that looks like a Relate store (`looks_like_store`) where it is; else None."""
    from faildex.store import is_public, looks_like_store, public_store

    if is_public(store):
        return public_store()
    return Path(store) if looks_like_store(store) else None


def _open_source(store: Path, wait: bool = False):
    """The store read-only (`_open_read_only`); a store that refuses that because it was
    never opened on this machine is first prepared, as `main` did on the first call:
    `open_store` makes its per-machine files under the write lock, after checking the
    store is still there (`_to_prepare` says where). The hook does not wait for a lock
    someone else holds, and a store being swapped has no manifest, so it is never
    opened for writing. Preparing is the only time the hook writes store files."""
    import relate

    try:
        return _open_read_only(store)
    except relate.OperationalError:
        from faildex.store import open_store

        source = _to_prepare(store)
        if source is None:
            raise
        return open_store(source, wait=wait)


def _warning(source, payload: object, min_sessions: int, top: int) -> tuple[str, str] | None:
    """(context for the agent, notice for the person), or None for nothing to say.

    The text is written here, inside the step that may fail, so that an index entry
    that cannot even be put into words sends the hook on to the next source."""
    template, found = _lookup(source, payload, min_sessions, top)
    if not found:
        return None
    return _context(template, found), notice_for(found)


def _found(store: Path, payload: object, min_sessions: int, top: int, rebuild: bool):
    """The warning from the store's index, or from the store itself (read-only) when the
    index is missing, stale or damaged anywhere, words included; then, with `rebuild`,
    the index is rebuilt in the background."""
    from faildex import index

    if _shell_command(payload) is None:
        return None
    for found in index.candidates(store):
        try:
            return _warning(found, payload, min_sessions, top)
        except Exception:  # noqa: BLE001, S112 - damaged: try the next source
            continue
    try:
        db = _open_source(store)
        try:
            return _warning(db, payload, min_sessions, top)
        finally:
            db.close()
    finally:
        if rebuild and index.fingerprint(store) is not None:
            index.start_rebuild(store)


def quiet(agent: str = "claude", event: str = "pre-shell") -> str:
    """What the hook prints when it has nothing to say, for each agent and event."""
    if agent == "cursor":
        return json.dumps({}) if event == "session-start" else json.dumps({"permission": "allow"})
    return ""


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
    rebuild: bool = False,
) -> str:
    """Hook stdout for one stdin payload; empty when there is nothing to say.

    With `rebuild`, a missing or stale index is rebuilt in the background (the CLI asks
    for it; a test calling this directly does not)."""
    silent = quiet(agent, "pre-shell")
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
        payload = json.loads(raw)
        if agent == "cursor" and isinstance(payload, dict):
            payload = {"tool_name": "Bash", "tool_input": {"command": payload.get("command")}}
        warning = _found(store, payload, min_sessions, top, rebuild)
        if warning is None:
            return silent
        context, notice = warning
        if log:
            try:
                _log(log, payload, context)
            except OSError:
                pass  # an unwritable log must not hide the warning itself
    except Exception:  # noqa: BLE001 - see module docstring
        return quiet(agent, event)
    if agent == "cursor":
        return json.dumps(
            {
                "permission": "allow",
                "user_message": notice,
                "agent_message": context,
            }
        )
    return json.dumps(
        {
            "systemMessage": notice,
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context},
        }
    )
