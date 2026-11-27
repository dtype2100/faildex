"""`faildex help` and the end of `faildex --help`: how to use faildex, in order.

The steps and their commands live here, untranslated; titles and notes come from
the i18n catalog. README.md and README.ko.md show the same three parts under the
same headings, and a test checks that their commands are exactly the commands here.
"""

from __future__ import annotations

import argparse

from faildex.i18n import CATALOG, DEFAULT, t, wrap

INSTALL = "curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh | sh"
APPROVE = "faildex rules --approve 1 3 --to ~/faildex-rules.md"

# Claude Code's PostToolUseFailure hook.
# `faildex link` puts it into ~/.claude/settings.json (agent_hooks.configure_claude); this
# text is for a project's .claude/settings.json. The README shows this same text.
CLAUDE_HOOK = (
    '{"hooks": {"PostToolUseFailure": [{"matcher": "Bash", "hooks": [\n'
    '  {"type": "command", "command": "faildex hook", "timeout": 5}\n'
    "]}]}}"
)

# The three parts, in order: first install (once), day to day (again), the effect.
# A part's heading is help.part.<part>; step N's title is help.<part>.N and its
# "what changes" line help.<part>.N.change. A step with no commands is the Claude Code
# hook: help.<part>.N.where, then CLAUDE_HOOK.
PARTS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    (
        "first",
        (
            (INSTALL, "faildex --version"),
            ("faildex demo",),
            ("faildex ingest",),
            ("faildex rules", APPROVE),
            ("faildex link",),
            (),
            ('faildex check "git status"',),
        ),
    ),
    ("again", (("faildex ingest",), ("faildex rules", APPROVE))),
    (
        "effect",
        (("faildex eval --store ~/.faildex/store",), ("faildex report --split 2026-11-17",)),
    ),
)


def commands(part: str | None = None) -> list[str]:
    """Every command of one part, or of all three, in order."""
    return [c for name, steps in PARTS if part in (None, name) for cmds in steps for c in cmds]


# Example commands per command; each note is ex.<command>.<n>.
EXAMPLES: dict[str, tuple[str, ...]] = {
    "build-store": ("faildex build-store", "faildex build-store --out /tmp/faildex-store"),
    "eval": ("faildex eval", "faildex eval --store ~/.faildex/store"),
    "rules": (
        "faildex rules",
        "faildex rules --top 3 --evidence",
        "faildex rules --approve 1 3 --to ~/faildex-rules.md",
    ),
    "link": ("faildex link --dry-run", "faildex link", "faildex link --remove"),
    "check": ('faildex check "git status"', "faildex check 'ls *.py && git push'"),
    "hook": (
        "faildex hook",
        "faildex hook --agent codex --event pre-shell --log ~/.faildex/hook.jsonl",
    ),
    "report": (
        "faildex report",
        'faildex report --split 2026-11-17 --key "not found"',
        "faildex report --split 2026-11-17 --hook-log ~/.faildex/hook.jsonl",
    ),
    "mcp": ("faildex mcp", "faildex mcp --store ~/.faildex/store"),
    "ingest": ("faildex ingest", "faildex ingest --claude ~/.claude/projects --store ./my-store"),
    "export-web": (
        "faildex export-web --out site/data.json",
        "faildex export-web --store ~/.faildex/store --out mine.json",
    ),
    "demo": ("faildex demo", "faildex --lang ko demo"),
    "sources": ("faildex sources",),
    "help": ("faildex help", "faildex help rules"),
    "lang": ("faildex lang", "faildex lang ko", "faildex lang en"),
}


def _step(part: str, number: int, cmds: tuple[str, ...], indent: str) -> list[str]:
    if cmds:
        return [f"{indent}{cmd}" for cmd in cmds]
    return [f"{indent}{t(f'help.{part}.{number}.where')}"] + [
        indent + line for line in CLAUDE_HOOK.splitlines()
    ]


def overview(names: list[str], lang: str) -> str:
    """The three parts, each step with its title, command(s) and what changes."""
    lines = [t("help.title"), ""]
    for part, steps in PARTS:
        lines += [t(f"help.part.{part}"), ""]
        for number, cmds in enumerate(steps, start=1):
            lines.append(f"{number}. {t(f'help.{part}.{number}')}")
            lines += _step(part, number, cmds, " " * 5)
            lines += wrap(f"     -> {t(f'help.{part}.{number}.change')}", 80, " " * 8)
            lines.append("")
    lines += wrap(t("help.undo"), 80, "  ")
    lines.append("")
    lines.append(t("help.more"))
    lines.append(t("help.commands", commands=", ".join(names)))
    lines.append(t("help.lang", language=lang))
    return "\n".join(lines)


def brief() -> str:
    """The end of `faildex --help`: every first-install step, then each other part in a line."""
    first, *rest = PARTS
    part, steps = first
    lines = [t(f"help.part.{part}")]
    for number, cmds in enumerate(steps, start=1):
        lines.append(f"  {number}. {t(f'help.{part}.{number}')}")
        lines += _step(part, number, cmds, " " * 7)
        if f"help.{part}.{number}.brief" in CATALOG[DEFAULT]:  # what must happen before the next
            lines += wrap(f"       -> {t(f'help.{part}.{number}.brief')}", 90, " " * 10)
    lines.append("")
    for part, _ in rest:
        lines += [t(f"help.part.{part}"), f"  {', '.join(commands(part))}"]
    lines += ["", t("help.next")]
    return "\n".join(lines)


def _options(sub: argparse.ArgumentParser) -> list[str]:
    formatter = sub._get_formatter()
    rows = []
    for action in sub._actions:
        if isinstance(action, argparse._HelpAction) or action.help == argparse.SUPPRESS:
            continue
        if "--lang" in action.option_strings:  # the same for every command: faildex help lang
            continue
        rows.append((formatter._format_action_invocation(action), action.help or ""))
    if not rows:
        return []
    from faildex.i18n import pad, width

    size = min(34, max(width(name) for name, _ in rows) + 2)
    out = []
    for name, text in rows:
        if width(name) + 2 > size:
            out += [f"  {name}", f"  {' ' * size}{text}".rstrip()]
        else:
            out.append(f"  {pad(name, size)}{text}".rstrip())
    return out


def command(name: str, sub: argparse.ArgumentParser) -> str:
    """What one command does, two or three examples, and its main options."""
    lines = [f"faildex {name}: {t(f'cmd.{name}')}", "", *wrap(t(f"about.{name}"), 80, ""), ""]
    lines.append(t("help.examples"))
    for number, example in enumerate(EXAMPLES[name], start=1):
        lines.append(f"  {example}")
        lines.append(f"      {t(f'ex.{name}.{number}')}")
    options = _options(sub)
    if options:
        lines += ["", t("help.options"), *options]
    lines += ["", t("help.see_also", command=name)]
    return "\n".join(lines)
