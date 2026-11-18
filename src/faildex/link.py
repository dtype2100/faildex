"""Make every agent on this machine read one approved-rules file.

`faildex rules --approve` writes rules to a Markdown file; an agent only follows
them once its own instructions load that file. This module wires the file into
each agent's global instructions, and takes it out again:

- Claude Code: an `@<file>` import line in `~/.claude/CLAUDE.md`.
- Antigravity: a plugin at `~/.gemini/config/plugins/faildex-rules/` whose
  `rules/AGENTS.md` is a link to the file (Antigravity loads plugin rules for
  every workspace).

Every change is idempotent: running it twice changes nothing the second time.
Nothing outside these two places is touched. Codex is reported, not changed:
its single `~/.codex/AGENTS.md` has no import syntax.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

HEADER = "# Rules learned from recurring failures (faildex)\n\n"
PLUGIN = "faildex-rules"


@dataclass
class Step:
    agent: str
    status: str  # linked, already, removed, absent, skipped, would link, would remove
    where: Path
    note: str = ""


def _claude_md(home: Path) -> Path:
    return home / ".claude" / "CLAUDE.md"


def _plugin(home: Path) -> Path:
    return home / ".gemini" / "config" / "plugins" / PLUGIN


def _has_antigravity(home: Path) -> bool:
    return any(
        (home / ".gemini" / name).is_dir() for name in ("antigravity", "antigravity-cli", "config")
    )


def _ours(plugin: Path) -> bool:
    try:
        return json.loads((plugin / "plugin.json").read_text()).get("name") == PLUGIN
    except (OSError, ValueError):
        return False


def link(rules: Path, home: Path | None = None, dry_run: bool = False) -> list[Step]:
    home = home or Path.home()
    rules = rules.expanduser().resolve()
    steps: list[Step] = []
    if not rules.exists() and not dry_run:
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(HEADER)

    # Claude Code: one import line.
    claude = _claude_md(home)
    line = f"@{rules}"
    text = claude.read_text() if claude.exists() else ""
    if line in text.splitlines():
        steps.append(Step("Claude Code", "already", claude, line))
    elif dry_run:
        steps.append(Step("Claude Code", "would link", claude, line))
    else:
        claude.parent.mkdir(parents=True, exist_ok=True)
        with claude.open("a") as out:
            out.write(("" if not text or text.endswith("\n") else "\n") + line + "\n")
        steps.append(Step("Claude Code", "linked", claude, line))

    # Antigravity: a plugin whose rules file is a link to ours.
    plugin = _plugin(home)
    target = plugin / "rules" / "AGENTS.md"
    if not _has_antigravity(home):
        steps.append(
            Step(
                "Antigravity",
                "skipped",
                plugin,
                "Antigravity is not installed (~/.gemini not found)",
            )
        )
    elif plugin.exists() and not _ours(plugin):
        steps.append(
            Step("Antigravity", "skipped", plugin, "a different plugin already uses this folder")
        )
    elif target.is_symlink() and target.resolve() == rules:
        steps.append(Step("Antigravity", "already", target, f"-> {rules}"))
    elif target.exists() and not target.is_symlink():
        steps.append(
            Step("Antigravity", "skipped", target, "a regular file is there; not replaced")
        )
    elif dry_run:
        steps.append(Step("Antigravity", "would link", target, f"-> {rules}"))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        (plugin / "plugin.json").write_text(
            json.dumps(
                {
                    "name": PLUGIN,
                    "version": "1.0.0",
                    "description": f"Rules approved with faildex; they live in {rules}.",
                },
                indent=2,
            )
            + "\n"
        )
        if target.is_symlink():
            target.unlink()
        target.symlink_to(rules)
        steps.append(Step("Antigravity", "linked", target, f"-> {rules}"))

    steps.append(
        Step(
            "Codex",
            "skipped",
            home / ".codex" / "AGENTS.md",
            "no import syntax; copy the rule lines in yourself if you want them there",
        )
    )
    return steps


def unlink(rules: Path, home: Path | None = None, dry_run: bool = False) -> list[Step]:
    home = home or Path.home()
    rules = rules.expanduser().resolve()
    steps: list[Step] = []

    claude = _claude_md(home)
    line = f"@{rules}"
    lines = claude.read_text().splitlines(keepends=True) if claude.exists() else []
    kept = [x for x in lines if x.rstrip("\n") != line]
    if len(kept) == len(lines):
        steps.append(Step("Claude Code", "absent", claude))
    elif dry_run:
        steps.append(Step("Claude Code", "would remove", claude, line))
    else:
        claude.write_text("".join(kept))
        steps.append(Step("Claude Code", "removed", claude, line))

    plugin = _plugin(home)
    if not plugin.exists():
        steps.append(Step("Antigravity", "absent", plugin))
    elif not _ours(plugin):
        steps.append(Step("Antigravity", "skipped", plugin, "not a faildex plugin; left alone"))
    elif dry_run:
        steps.append(Step("Antigravity", "would remove", plugin))
    else:
        shutil.rmtree(plugin)
        steps.append(Step("Antigravity", "removed", plugin))
    return steps


def render(steps: list[Step], home: Path | None = None) -> str:
    home = home or Path.home()

    def short(p: Path) -> str:
        s = str(p)
        return "~" + s[len(str(home)) :] if s.startswith(str(home)) else s

    rows = []
    for step in steps:
        note = step.note.replace(str(home), "~")
        rows.append(
            f"{step.agent:<12} {step.status:<12} {short(step.where)}"
            + (f"  ({note})" if note else "")
        )
    return "\n".join(rows)
