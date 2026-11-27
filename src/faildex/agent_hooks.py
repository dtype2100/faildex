"""Install faildex's hooks (Codex, Cursor, Claude Code) without replacing other tools' hooks."""

from __future__ import annotations

import base64
import copy
import json
import shutil
import tempfile
import time
from pathlib import Path


def _ours(entry: dict) -> bool:
    command = entry.get("command")
    return isinstance(command, str) and command.startswith("faildex hook --agent ")


def configure(agent: str, path: Path, rules: Path, remove: bool, dry_run: bool) -> tuple[str, str]:
    """Install faildex's session-start hook (the rules file) for Codex or Cursor, or take
    every faildex hook out. Return (status, note); invalid or linked configs stay untouched.

    No hook that runs before a shell command is installed for any agent, and a faildex
    one from an earlier `faildex link` (Codex `PreToolUse`, Cursor `beforeShellExecution`)
    is taken out, other tools' hooks kept."""
    if path.is_symlink():
        return "skipped", "hooks.json is a symlink; left alone"
    if remove and not path.exists():
        return "absent", ""
    try:
        original = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        if not isinstance(original, dict) or not isinstance(original.get("hooks", {}), dict):
            raise TypeError("hooks must be an object")
        data = copy.deepcopy(original)
        hooks = data.setdefault("hooks", {})
        events = (
            ("SessionStart", "PreToolUse")
            if agent == "codex"
            else (
                "sessionStart",
                "beforeShellExecution",
            )
        )
        for event, kind in zip(events, ("session-start", "pre-shell")):
            entries = hooks.get(event, [])
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise ValueError("hook event must contain objects")

            def ours(entry: dict, kind: str = kind) -> bool:
                # Before a shell command, any faildex hook goes, by whatever path it runs.
                return _ours(entry) or (
                    kind == "pre-shell" and _faildex_hook_command(entry.get("command"))
                )

            kept = []
            for entry in entries:
                if ours(entry):
                    continue
                if "hooks" in entry:
                    children = entry["hooks"]
                    if not isinstance(children, list) or any(
                        not isinstance(e, dict) for e in children
                    ):
                        raise ValueError("nested hooks must contain objects")
                    remaining = [child for child in children if not ours(child)]
                    if not remaining and len(remaining) != len(children):
                        continue
                    entry = {**entry, "hooks": remaining}
                kept.append(entry)
            if not remove and kind == "session-start":
                # Only shell-safe tokens: Windows hook runners use different shells.
                encoded = base64.urlsafe_b64encode(str(rules).encode("utf-8")).decode("ascii")
                command = f"faildex hook --agent {agent} --event {kind} --rules-encoded {encoded}"
                entry = {"command": command}
                if agent == "codex":
                    entry = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
                kept.append(entry)
            if kept:
                hooks[event] = kept
            else:
                hooks.pop(event, None)
        if agent == "cursor" and not remove:
            data.setdefault("version", 1)
        if data == original:
            return ("absent" if remove else "already"), ""
        if dry_run:
            return ("would remove" if remove else "would install"), ""
        if path.exists():
            shutil.copy2(path, path.with_name(f"{path.name}.faildex-backup-{time.time_ns()}"))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as out:
                temp = Path(out.name)
                out.write(json.dumps(data, indent=2) + "\n")
            temp.replace(path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        note = (
            "review and trust new hooks in Codex /hooks" if agent == "codex" and not remove else ""
        )
        return ("removed" if remove else "installed"), note
    except (OSError, ValueError, TypeError):
        return "skipped", "could not safely update hooks.json; left alone"


# Claude Code: faildex's hook in ~/.claude/settings.json, after a failed shell call.
CLAUDE_EVENT = "PostToolUseFailure"
CLAUDE_COMMAND = "faildex hook --agent claude"  # shell-safe tokens only, as above
WOULD = {"installed": "would install", "moved": "would move", "updated": "would update"}


def _faildex_hook_command(command: object) -> bool:
    """A `faildex hook ...` command line, however faildex is named: `faildex hook`, an
    absolute path to it (`/x/.venv/bin/faildex hook --store ...`), `faildex.exe`."""
    import shlex
    from pathlib import PureWindowsPath

    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command, posix=False)
    except ValueError:
        return False
    words = [word.strip("'\"") for word in words]
    return (
        len(words) >= 2
        and PureWindowsPath(words[0]).name.lower() in ("faildex", "faildex.exe")
        and words[1] == "hook"
    )


class _Unsafe(Exception):
    """settings.json is not what faildex can safely edit; the message is the link note."""


def _groups(hooks: dict, event: str) -> list:
    groups = hooks.get(event, [])
    if not isinstance(groups, list) or any(not isinstance(g, dict) for g in groups):
        raise _Unsafe("settings.json: a hook event is not a list of objects; left alone")
    for group in groups:
        children = group.get("hooks", [])
        if not isinstance(children, list) or any(not isinstance(c, dict) for c in children):
            raise _Unsafe("settings.json: a hook event is not a list of objects; left alone")
    return groups


def _split(groups: list) -> tuple[list, list]:
    """(the groups without faildex's hooks, the faildex hooks of each group as new groups)."""
    kept, taken = [], []
    for group in groups:
        children = group.get("hooks", [])
        ours = [child for child in children if _faildex_hook_command(child.get("command"))]
        if not ours:
            kept.append(group)
            continue
        rest = [child for child in children if child not in ours]
        if rest:
            kept.append({**group, "hooks": rest})
        taken.append({**group, "hooks": ours})
    return kept, taken


def configure_claude(
    path: Path, remove: bool, dry_run: bool, created: bool = False
) -> tuple[str, str]:
    """Put faildex's hook under PostToolUseFailure in Claude Code's settings.json, or take
    it out of PostToolUseFailure and PreToolUse. Return (status, note).

    A faildex hook under PreToolUse (the earlier setting) never stays: it moves to
    PostToolUseFailure with its command unchanged, or, when one is there already, is
    just taken out; the other hooks of its group stay behind. A faildex hook already
    under PostToolUseFailure alone is left as it is. Other keys, hooks and their order are
    kept; the file is written only when it changes, after a backup, through a temporary
    file. A symlink, invalid JSON or an unexpected shape is left alone, with the reason.
    With `created` (faildex link made the file), a removal that leaves nothing else in
    it deletes the file.
    """
    if path.is_symlink():
        return "skipped", "settings.json is a symlink; left alone"
    if remove and not path.exists():
        return "absent", ""
    try:
        try:
            original = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        except ValueError:
            raise _Unsafe("settings.json is not a valid JSON object; left alone") from None
        if not isinstance(original, dict):
            raise _Unsafe("settings.json is not a valid JSON object; left alone")
        if not isinstance(original.get("hooks", {}), dict):
            raise _Unsafe("settings.json: hooks is not an object; left alone")
        data = copy.deepcopy(original)
        hooks = data.setdefault("hooks", {})
        post, pre = _groups(hooks, CLAUDE_EVENT), _groups(hooks, "PreToolUse")
        post_kept, post_ours = _split(post)
        pre_kept, pre_ours = _split(pre)
        status = "installed"
        if remove:
            for event, kept, ours in (
                (CLAUDE_EVENT, post_kept, post_ours),
                ("PreToolUse", pre_kept, pre_ours),
            ):
                if not ours:
                    continue
                if kept:
                    hooks[event] = kept
                else:
                    hooks.pop(event, None)
        elif pre_ours:  # faildex no longer runs before a Claude Code call
            if pre_kept:
                hooks["PreToolUse"] = pre_kept
            else:
                hooks.pop("PreToolUse", None)
            if post_ours:
                status = "updated"
            else:
                status = "moved"
                hooks[CLAUDE_EVENT] = post + pre_ours
        elif not post_ours:
            entry = {"type": "command", "command": CLAUDE_COMMAND, "timeout": 5}
            hooks[CLAUDE_EVENT] = post + [{"matcher": "Bash", "hooks": [entry]}]
        if not hooks and "hooks" not in original:
            data.pop("hooks")
        if data == original:
            return ("absent" if remove else "already"), ""
        if dry_run:
            return ("would remove" if remove else WOULD[status]), ""
        if remove and created and data in ({}, {"hooks": {}}):
            path.unlink()  # it held only faildex's hook
            return "removed", ""
        if path.exists():
            shutil.copy2(path, path.with_name(f"{path.name}.faildex-backup-{time.time_ns()}"))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as out:
                temp = Path(out.name)
                out.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            temp.replace(path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        if remove:
            return "removed", ""
        return (
            status,
            "new Claude Code sessions use it; in a running session, review it with /hooks",
        )
    except _Unsafe as why:
        return "skipped", str(why)
    except OSError:
        return "skipped", "could not safely update settings.json; left alone"
