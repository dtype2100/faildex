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
- Codex and Cursor: the skill and two user hooks for session rules and shell warnings.

Every change is idempotent: running it twice changes nothing the second time.
Files that are not faildex's own are never replaced.
"""

from __future__ import annotations

import json
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
        return (
            json.loads((plugin / "plugin.json").read_text(encoding="utf-8")).get("name") == PLUGIN
        )
    except (OSError, ValueError):
        return False


def _is_faildex_skill(path: Path) -> bool:
    try:
        head = path.read_text(encoding="utf-8").split("---", 2)[1]
    except (OSError, IndexError):
        return False
    return any(line.strip() == "name: faildex" for line in head.splitlines())


def _resolved(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return None


def _symlink_path(path: Path, home: Path) -> bool:
    """Do not write through user links, including links used as parent folders."""
    while path != home:
        if path.is_symlink():
            return True
        path = path.parent
    return False


def _link_paths() -> tuple[set[str], set[str]]:
    files = {
        ".claude/CLAUDE.md",
        ".claude/skills/faildex/SKILL.md",
        ".codex/skills/faildex/SKILL.md",
        ".cursor/skills/faildex/SKILL.md",
        ".gemini/config/plugins/faildex-rules/plugin.json",
        ".gemini/config/plugins/faildex-rules/rules/AGENTS.md",
        ".gemini/config/plugins/faildex-rules/skills/faildex/SKILL.md",
    }
    dirs = {p.as_posix() for name in files for p in Path(name).parents if p != Path(".")}
    return files, dirs


def _ownership(home: Path) -> dict[str, list[str]] | None:
    state = home / ".faildex-link.json"
    if not state.exists() and not state.is_symlink():
        return None
    if state.is_symlink():
        raise ValueError("faildex link ownership file must not be a symlink")
    data = json.loads(state.read_text(encoding="utf-8"))
    files, dirs = _link_paths()
    if not isinstance(data, dict) or any(
        not isinstance(data.get(key), list)
        or any(not isinstance(name, str) or name not in allowed for name in data[key])
        for key, allowed in (("files", files), ("dirs", dirs))
    ):
        raise ValueError("invalid faildex link ownership file")
    return data


def _install_skill(agent: str, folder: Path, dry_run: bool, home: Path) -> Step:
    """Copy the shipped skill, preserving other skills and user symlinks."""
    dest = folder / "SKILL.md"
    if _symlink_path(dest, home):
        return Step(agent, "skipped", dest, "a symlink is there; left alone", "skill")
    text = skill_source().read_text(encoding="utf-8")
    if dest.exists() and dest.read_text(encoding="utf-8") == text:
        return Step(agent, "already", dest, what="skill")
    if dest.exists() and not _is_faildex_skill(dest):
        return Step(agent, "skipped", dest, "a different skill is there; not replaced", "skill")
    if dry_run:
        return Step(agent, "would install", dest, what="skill")
    status = "updated" if dest.exists() else "installed"
    folder.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return Step(agent, status, dest, what="skill")


def _remove_file(path: Path, home: Path, owned: dict[str, list[str]] | None) -> bool:
    if owned is None or _symlink_path(path.parent, home):
        return False
    if path.relative_to(home).as_posix() not in owned["files"]:
        return False
    path.unlink()
    return True


def _remove_skill(
    agent: str, folder: Path, dry_run: bool, home: Path, owned: dict[str, list[str]] | None
) -> Step:
    dest = folder / "SKILL.md"
    if _symlink_path(dest, home):
        return Step(agent, "skipped", dest, "a symlink is there; left alone", "skill")
    if not dest.exists():
        return Step(agent, "absent", dest, what="skill")
    if (
        owned is None
        or dest.relative_to(home).as_posix() not in owned["files"]
        or not _is_faildex_skill(dest)
    ):
        return Step(agent, "skipped", dest, "not installed by faildex; left alone", "skill")
    if dry_run:
        return Step(agent, "would remove", dest, what="skill")
    _remove_file(dest, home, owned)
    return Step(agent, "removed", dest, what="skill")


def _write_manifest(plugin: Path, rules: Path) -> None:
    plugin.mkdir(parents=True, exist_ok=True)
    if (plugin / "plugin.json").exists():
        return
    (plugin / "plugin.json").write_text(
        json.dumps(
            {
                "name": PLUGIN,
                "version": "1.1.0",
                "description": f"faildex for Antigravity: approved rules (in {rules}) and the faildex skill.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _is_copy(target: Path, rules: Path) -> bool:
    try:
        return target.read_text(encoding="utf-8").startswith(COPY.format(rules))
    except OSError:
        return False


def link(rules: Path, home: Path | None = None, dry_run: bool = False) -> list[Step]:
    home = home or Path.home()
    rules = rules.expanduser().resolve()
    owned = _ownership(home)
    files, dirs = _link_paths()
    before = {name for name in files | dirs if (home / name).exists() or (home / name).is_symlink()}
    steps: list[Step] = []
    if not rules.exists() and not dry_run:
        rules.parent.mkdir(parents=True, exist_ok=True)
        rules.write_text(HEADER, encoding="utf-8")

    # Claude Code: one import line.
    claude = _claude_md(home)
    line = f"@{rules}"
    text = (
        claude.read_text(encoding="utf-8")
        if claude.exists() and not _symlink_path(claude, home)
        else ""
    )
    if _symlink_path(claude, home):
        steps.append(Step("Claude Code", "skipped", claude, "a symlink is there; left alone"))
    elif line in text.splitlines():
        steps.append(Step("Claude Code", "already", claude, line))
    elif dry_run:
        steps.append(Step("Claude Code", "would link", claude, line))
    else:
        claude.parent.mkdir(parents=True, exist_ok=True)
        with claude.open("a", encoding="utf-8") as out:
            out.write(("" if not text or text.endswith("\n") else "\n") + line + "\n")
        steps.append(Step("Claude Code", "linked", claude, line))
    steps.append(
        _install_skill("Claude Code", home / ".claude" / "skills" / "faildex", dry_run, home)
    )

    # Antigravity: a plugin whose rules file is a link to ours.
    plugin = _plugin(home)
    target = plugin / "rules" / "AGENTS.md"
    target_rel = target.relative_to(home).as_posix()
    target_owned = owned is not None and target_rel in owned["files"]
    if not _has_antigravity(home):
        steps.append(
            Step(
                "Antigravity",
                "skipped",
                plugin,
                "Antigravity is not installed (~/.gemini not found)",
            )
        )
    elif _symlink_path(plugin, home) or (plugin / "plugin.json").is_symlink():
        steps.append(Step("Antigravity", "skipped", plugin, "a symlink is there; left alone"))
    elif plugin.exists() and not _ours(plugin):
        steps.append(
            Step("Antigravity", "skipped", plugin, "a different plugin already uses this folder")
        )
    elif _symlink_path(target.parent, home):
        steps.append(Step("Antigravity", "skipped", target, "a symlink is there; left alone"))
    elif target.is_symlink() and _resolved(target) == rules:
        steps.append(Step("Antigravity", "already", target, f"-> {rules}"))
    elif target.is_symlink() and not target_owned:
        steps.append(Step("Antigravity", "skipped", target, "a symlink is there; left alone"))
    elif not target.is_symlink() and target.exists() and not _is_copy(target, rules):
        steps.append(
            Step("Antigravity", "skipped", target, "a regular file is there; not replaced")
        )
    elif dry_run:
        status = "would update" if target.is_symlink() else "would link"
        steps.append(Step("Antigravity", status, target, f"-> {rules}"))
    else:
        updating = target.is_symlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_manifest(plugin, rules)
        if updating:
            target.unlink()
        copied = target.exists()
        if not copied:
            try:
                target.symlink_to(rules)
            except OSError:
                copied = True
        if copied:
            target.write_text(
                COPY.format(rules) + rules.read_text(encoding="utf-8"), encoding="utf-8"
            )
            steps.append(
                Step(
                    "Antigravity",
                    "copied",
                    target,
                    "rules copy; run faildex link again after approving rules",
                )
            )
        else:
            status = "updated" if updating else "linked"
            steps.append(Step("Antigravity", status, target, f"-> {rules}"))

    if (
        _has_antigravity(home)
        and not _symlink_path(plugin, home)
        and not (plugin / "plugin.json").is_symlink()
        and (not plugin.exists() or _ours(plugin))
    ):
        if not dry_run and not (plugin / "plugin.json").exists():
            _write_manifest(plugin, rules)
        steps.append(_install_skill("Antigravity", plugin / "skills" / "faildex", dry_run, home))

    from faildex.agent_hooks import configure

    for agent, folder in (("Codex", ".codex"), ("Cursor", ".cursor")):
        if (home / folder).is_dir() and not _symlink_path(home / folder, home):
            path = home / folder / "hooks.json"
            status, note = configure(agent.lower(), path, rules, False, dry_run)
            steps.append(Step(agent, status, path, note, "hooks"))
    if (home / ".codex").is_dir():
        steps.append(_install_skill("Codex", home / ".codex" / "skills" / "faildex", dry_run, home))
    if (home / ".cursor").is_dir():
        steps.append(
            _install_skill("Cursor", home / ".cursor" / "skills" / "faildex", dry_run, home)
        )
    if not dry_run:
        created = {
            key: sorted(
                set((owned or {}).get(key, []))
                | {
                    name
                    for name in paths - before
                    if (home / name).exists() or (home / name).is_symlink()
                }
            )
            for key, paths in (("files", files), ("dirs", dirs))
        }
        (home / ".faildex-link.json").write_text(
            json.dumps(created, indent=2) + "\n", encoding="utf-8"
        )
    return steps


def unlink(rules: Path, home: Path | None = None, dry_run: bool = False) -> list[Step]:
    home = home or Path.home()
    rules = rules.expanduser().resolve()
    owned = _ownership(home)
    steps: list[Step] = []
    from faildex.agent_hooks import configure

    for agent, folder in (("Codex", ".codex"), ("Cursor", ".cursor")):
        path = home / folder / "hooks.json"
        if path.exists() and not _symlink_path(path.parent, home):
            status, note = configure(agent.lower(), path, rules, True, dry_run)
            steps.append(Step(agent, status, path, note, "hooks"))

    claude = _claude_md(home)
    line = f"@{rules}"
    lines = (
        claude.read_text(encoding="utf-8").splitlines(keepends=True)
        if claude.exists() and not _symlink_path(claude, home)
        else []
    )
    kept = [x for x in lines if x.rstrip("\n") != line]
    if len(kept) == len(lines):
        steps.append(Step("Claude Code", "absent", claude))
    elif dry_run:
        steps.append(Step("Claude Code", "would remove", claude, line))
    else:
        leftover = "".join(kept)
        if not leftover and owned is not None and ".claude/CLAUDE.md" in owned["files"]:
            _remove_file(claude, home, owned)
        else:
            claude.write_text(leftover, encoding="utf-8")
        steps.append(Step("Claude Code", "removed", claude, line))

    steps.append(
        _remove_skill("Claude Code", home / ".claude" / "skills" / "faildex", dry_run, home, owned)
    )
    steps.append(
        _remove_skill("Codex", home / ".codex" / "skills" / "faildex", dry_run, home, owned)
    )
    steps.append(
        _remove_skill("Cursor", home / ".cursor" / "skills" / "faildex", dry_run, home, owned)
    )

    plugin = _plugin(home)
    if not plugin.exists():
        steps.append(Step("Antigravity", "absent", plugin))
    elif owned is None or _symlink_path(plugin, home) or not _ours(plugin):
        steps.append(Step("Antigravity", "skipped", plugin, "not a faildex plugin; left alone"))
    elif dry_run:
        steps.append(Step("Antigravity", "would remove", plugin))
    else:
        target = plugin / "rules" / "AGENTS.md"
        target_rel = target.relative_to(home).as_posix()
        if not _symlink_path(target.parent, home) and (
            (target.is_symlink() and target_rel in owned["files"])
            or (not target.is_symlink() and _is_copy(target, rules))
        ):
            _remove_file(target, home, owned)
        steps.append(
            _remove_skill("Antigravity", plugin / "skills" / "faildex", False, home, owned)
        )
        manifest = plugin / "plugin.json"
        if not _symlink_path(manifest, home):
            _remove_file(manifest, home, owned)
        steps.append(Step("Antigravity", "removed", plugin, "rules and skill"))
    if not dry_run and owned is not None:
        for name in sorted(owned["dirs"], key=lambda name: len(Path(name).parts), reverse=True):
            folder = home / name
            if not _symlink_path(folder, home):
                try:
                    folder.rmdir()
                except OSError:
                    pass  # A user file added after link keeps its containing folders.
        (home / ".faildex-link.json").unlink()
    return steps


def render(steps: list[Step], home: Path | None = None) -> str:
    home = home or Path.home()

    def short(p: Path) -> str:
        s = str(p)
        return "~" + s[len(str(home)) :] if s.startswith(str(home)) else s

    from faildex.i18n import CATALOG, DEFAULT, pad, t

    english = CATALOG[DEFAULT]
    notes = {english[key]: key for key in english if key.startswith("link.note.")}

    def word(prefix: str, value: str) -> str:
        key = f"{prefix}.{value}"
        return t(key) if key in english else value

    rows = []
    for step in steps:
        note = t(notes[step.note]) if step.note in notes else step.note
        note = note.replace(str(home), "~")
        rows.append(
            f"{pad(step.agent, 12)} {pad(word('link.what', step.what), 6)} "
            f"{pad(word('link.status', step.status), 14)} {short(step.where)}"
            + (f"  ({note})" if note else "")
        )
    return "\n".join(rows)
