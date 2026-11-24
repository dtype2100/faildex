"""`faildex help`: how to use faildex in order, and how to use one command.

The steps and example commands live here, untranslated; their titles and notes come
from the i18n catalog. README.md and README.ko.md list the same steps, and a test
checks that the commands there are exactly the commands here.
"""

from __future__ import annotations

import argparse

from faildex.i18n import t, wrap

INSTALL = "curl -fsSL https://raw.githubusercontent.com/dtype2100/faildex/main/install.sh | sh"

# (step number, commands); the title and "what changes" line are help.step.N / help.change.N.
STEPS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (INSTALL,)),
    (2, ("faildex demo",)),
    (3, ("faildex ingest",)),
    (4, ("faildex rules",)),
    (5, ("faildex rules --approve 1 3 --to ~/faildex-rules.md",)),
    (6, ("faildex link",)),
    (7, ("faildex hook", "faildex mcp", 'faildex check "git status"')),
    (8, ("faildex eval", "faildex report --split 2026-11-17")),
)

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


def overview(commands: list[str], lang: str) -> str:
    """The steps, in order: title, command(s), what changes."""
    lines = [t("help.title"), ""]
    for number, cmds in STEPS:
        lines.append(f"{number}. {t(f'help.step.{number}')}")
        lines += [f"     {cmd}" for cmd in cmds]
        lines += wrap(f"     -> {t(f'help.change.{number}')}", 80, " " * 8)
        lines.append("")
    lines.append(t("help.more"))
    lines.append(t("help.commands", commands=", ".join(commands)))
    lines.append(t("help.lang", language=lang))
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
