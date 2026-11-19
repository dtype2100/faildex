"""Make every agent on this machine use faildex: the approved rules and the skill.

`faildex rules --approve` writes rules to a Markdown file; an agent only follows
them once its own instructions load that file. The faildex skill tells an agent
when to ask faildex (before retrying a failed command, when asked what keeps
going wrong). This module wires both in, and takes them out again:

- Claude Code: an `@<file>` import line in `~/.claude/CLAUDE.md`, and the skill
  at `~/.claude/skills/faildex/SKILL.md`.
- Antigravity: a plugin at `~/.gemini/config/plugins/faildex-rules/` whose
  `rules/AGENTS.md` is a link to the file and whose `skills/faildex/SKILL.md` is
  the skill (Antigravity loads plugin rules and skills in every workspace).
- Codex: the skill at `~/.codex/skills/faildex/SKILL.md`. The rules are reported,
  not changed: its single `~/.codex/AGENTS.md` has no import syntax.
- Cursor: the skill at `~/.cursor/skills/faildex/SKILL.md`. Its global rules live
  in Cursor's settings, not in a file, so they are reported, not changed.

Every change is idempotent: running it twice changes nothing the second time.
Files that are not faildex's own are never replaced.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

HEADER = "# Rules learned from recurring failures (faildex)\n\n"
# Where symlinks are not allowed (Windows without Developer Mode) the plugin gets a
# marked copy instead, refreshed by running `faildex link` again.
COPY = "<!-- faildex link: copy of {} -->\n"
PLUGIN = "faildex-rules"
_HERE = Path(__file__).resolve().parent


def skill_source() -> Path:
    """The SKILL.md that ships with this copy of faildex (wheel or checkout)."""
    for candidate in (
        _HERE / "_skills" / "faildex" / "SKILL.md",
        _HERE.parents[1] / "skills" / "faildex" / "SKILL.md",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("the faildex skill is missing from this installation")


@dataclass
class Step:
    agent: str
    status: str  # linked, installed, updated, already, removed, absent, skipped, would ...
    where: Path
    note: str = ""
    what: str = "rules"  # rules or skill


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


def _is_faildex_skill(path: Path) -> bool:
    try:
        head = path.read_text().split("---", 2)[1]
    except (OSError, IndexError):
        return False
    return any(line.strip() == "name: faildex" for line in head.splitlines())


def _install_skill(agent: str, folder: Path, dry_run: bool) -> Step:
    """Copy the shipped skill to `folder/SKILL.md`, unless someone else's skill is there."""
    dest = folder / "SKILL.md"
    text = skill_source().read_text()
    if dest.exists() and dest.read_text() == text:
        return Step(agent, "already", dest, what="skill")
    if dest.exists() and not _is_faildex_skill(dest):
        return Step(agent, "skipped", dest, "a different skill is there; not replaced", "skill")
    if dry_run:
        return Step(agent, "would install", dest, what="skill")
    status = "updated" if dest.exists() else "installed"
    folder.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    return Step(agent, status, dest, what="skill")


def _remove_skill(agent: str, folder: Path, dry_run: bool) -> Step:
    dest = folder / "SKILL.md"
    if not dest.exists():
        return Step(agent, "absent", dest, what="skill")
    if not _is_faildex_skill(dest):
        return Step(agent, "skipped", dest, "not the faildex skill; left alone", "skill")
    if dry_run:
        return Step(agent, "would remove", dest, what="skill")
    shutil.rmtree(folder)
    return Step(agent, "removed", dest, what="skill")


def _write_manifest(plugin: Path, rules: Path) -> None:
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "name": PLUGIN,
                "version": "1.1.0",
                "description": f"faildex for Antigravity: approved rules (in {rules}) and the faildex skill.",
            },
            indent=2,
        )
        + "\n"
    )


def _is_copy(target: Path, rules: Path) -> bool:
    try:
        return target.read_text().startswith(COPY.format(rules))
    except OSError:
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
    steps.append(_install_skill("Claude Code", home / ".claude" / "skills" / "faildex", dry_run))

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
    elif target.exists() and not target.is_symlink() and not _is_copy(target, rules):
        steps.append(
            Step("Antigravity", "skipped", target, "a regular file is there; not replaced")
        )
    elif dry_run:
        steps.append(Step("Antigravity", "would link", target, f"-> {rules}"))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_manifest(plugin, rules)
        if target.is_symlink() or target.exists():
            target.unlink()
        try:
            target.symlink_to(rules)
            steps.append(Step("Antigravity", "linked", target, f"-> {rules}"))
        except OSError:
            target.write_text(COPY.format(rules) + rules.read_text())
            steps.append(
                Step(
                    "Antigravity",
                    "copied",
                    target,
                    "symlinks not allowed here; run faildex link again after approving rules",
                )
            )

    if _has_antigravity(home) and (not plugin.exists() or _ours(plugin)):
        if not dry_run and not (plugin / "plugin.json").exists():
            _write_manifest(plugin, rules)
        steps.append(_install_skill("Antigravity", plugin / "skills" / "faildex", dry_run))

    steps.append(
        Step(
            "Codex",
            "skipped",
            home / ".codex" / "AGENTS.md",
            "no import syntax; copy the rule lines in yourself if you want them there",
        )
    )
    if (home / ".codex").is_dir():
        steps.append(_install_skill("Codex", home / ".codex" / "skills" / "faildex", dry_run))
    if (home / ".cursor").is_dir():
        steps.append(
            Step(
                "Cursor",
                "skipped",
                home / ".cursor",
                "global rules live in Cursor's settings; paste the rule lines there if you want them",
            )
        )
        steps.append(_install_skill("Cursor", home / ".cursor" / "skills" / "faildex", dry_run))
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

    steps.append(_remove_skill("Claude Code", home / ".claude" / "skills" / "faildex", dry_run))
    steps.append(_remove_skill("Codex", home / ".codex" / "skills" / "faildex", dry_run))
    steps.append(_remove_skill("Cursor", home / ".cursor" / "skills" / "faildex", dry_run))

    plugin = _plugin(home)
    if not plugin.exists():
        steps.append(Step("Antigravity", "absent", plugin))
    elif not _ours(plugin):
        steps.append(Step("Antigravity", "skipped", plugin, "not a faildex plugin; left alone"))
    elif dry_run:
        steps.append(Step("Antigravity", "would remove", plugin))
    else:
        shutil.rmtree(plugin)
        steps.append(Step("Antigravity", "removed", plugin, "rules and skill"))
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
            f"{step.agent:<12} {step.what:<6} {step.status:<14} {short(step.where)}"
            + (f"  ({note})" if note else "")
        )
    return "\n".join(rows)
