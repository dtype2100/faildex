"""Install faildex's two hooks without replacing other tools' hooks."""

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
    """Return (status, note); invalid or linked configs stay untouched."""
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
            kept = []
            for entry in entries:
                if _ours(entry):
                    continue
                if "hooks" in entry:
                    children = entry["hooks"]
                    if not isinstance(children, list) or any(
                        not isinstance(e, dict) for e in children
                    ):
                        raise ValueError("nested hooks must contain objects")
                    remaining = [child for child in children if not _ours(child)]
                    if not remaining and len(remaining) != len(children):
                        continue
                    entry = {**entry, "hooks": remaining}
                kept.append(entry)
            if not remove:
                argv = ["faildex", "hook", "--agent", agent, "--event", kind]
                if kind == "session-start":
                    # Only shell-safe tokens: Windows hook runners use different shells.
                    encoded = base64.urlsafe_b64encode(str(rules).encode("utf-8")).decode("ascii")
                    argv += ["--rules-encoded", encoded]
                command = " ".join(argv)
                entry = {"command": command}
                if agent == "codex":
                    entry = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
                    if kind == "pre-shell":
                        entry["matcher"] = "Bash"
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
