"""What the graph knows about recurring failures.

One set of queries serves every surface: `faildex rules`, the pre-run hook and
the MCP tools all call the functions here, so they cannot disagree.

A recovery is read off the graph, not guessed: after a failed call, follow
NEXT for a few hops to the first call that runs the same command and succeeds.
If there are calls in between, the first of them is the step that got the
session unstuck; if there are none, the command simply worked on a changed
retry.
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

RECOVERY_HOPS = 5
# A warning must be worth the interruption: the failure has to account for at
# least this share of the command's runs. Otherwise every `ls` would carry one.
MIN_RATE = 0.03

_RUNS = "MATCH (:Command {template: $command})<-[:RAN]-(c:Call) RETURN count(c) AS n"
RETRY = "retry"
# Only these get better by running the same thing again; everything else needs a change.
# Digits are masked in signatures, so status codes are matched by their reason phrase.
_TRANSIENT = re.compile(
    r"timed out|\btimeout(?:error| error| expired| exceeded)\b|deadline exceeded"
    r"|connection (?:refused|reset|aborted)|econn(?:refused|reset)"
    r"|too many requests|rate.?limit|service unavailable|bad gateway|internal server error"
    r"|overloaded|temporarily unavailable|try again later|resource busy"
    r"|\b(?:database|file|resource|table) is locked\b|(?:acquire|obtain|get) (?:the |a )?lock\b"
    r"|index\.lock|another \S+ process seems to be running|\b(?:429|5\d\d)\b",
    re.IGNORECASE,
)
# Shell failures pooled across commands come with a fixed cure; the step that happened to
# follow them in a session is not one.
SHELL_FIXES = {
    "no matches found: <glob>": "quote the glob, star included (`--include='*.py'`, not `--include=*.py`)",
    "=<word> not found": "quote words that start with `=` (`echo '===='`, not `echo ====`)",
}


def is_transient(sig: str) -> bool:
    """A failure that the very same call can get past: timeouts, refused links, locks, 429, 5xx."""
    return bool(_TRANSIENT.search(sig))


# With a command, every count, recovery and rule is about that command alone.
_ALL = """
MATCH (e:ErrorSig)<-[:FAILED_WITH]-(f:Call)
OPTIONAL MATCH (f)-[:RAN]->(k:Command)
"""
_FOR_COMMAND = """
MATCH (k:Command {template: $command})<-[:RAN]-(f:Call)-[:FAILED_WITH]->(e:ErrorSig)
"""

_FAILURES = """
MATCH (f)<-[:HAS_CALL]-(s:Session)
RETURN e.sig AS sig, e.kind AS kind, s.id AS session, s.agent AS agent,
       k.template AS command, f.tool AS tool, f.id AS call, f.source_path AS path, f.source_line AS line
ORDER BY call
"""

# A compound command line does not say which part failed, so it proves no recovery.
_RECOVERIES = f"""
WITH e, f, k WHERE k IS NOT NULL AND coalesce(f.compound, false) = false
MATCH p = (f)-[:NEXT*1..{RECOVERY_HOPS}]->(g:Call {{ok: true}}), (g)-[:RAN]->(k)
WHERE coalesce(g.compound, false) = false AND (f.ts IS NULL OR g.ts IS NULL OR g.ts >= f.ts)
WITH e, f, k, min(length(p)) AS hops
MATCH q = (f)-[:NEXT*1..{RECOVERY_HOPS}]->(:Call {{ok: true}})
WHERE length(q) = hops
WITH e, f, k, hops, nodes(q)[1] AS step
OPTIONAL MATCH (step)-[:RAN]->(sk:Command)
RETURN DISTINCT e.sig AS sig, f.id AS call, hops, k.template AS command,
       step.tool AS tool, sk.template AS step
"""


@dataclass
class Failure:
    """One failure key with everything needed to propose a rule about it."""

    sig: str
    kind: str
    calls: int = 0
    sessions: set[str] = field(default_factory=set)
    agents: set[str] = field(default_factory=set)
    commands: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)
    fixes: Counter = field(default_factory=Counter)
    recovered: int = 0
    evidence: list[str] = field(default_factory=list)
    runs: int = 0  # all runs of the command, set when the failure is looked up for one command

    @property
    def command(self) -> str | None:
        return self.commands.most_common(1)[0][0] if self.commands else None

    @property
    def fix(self) -> str | None:
        return self.fixes.most_common(1)[0][0] if self.fixes else None

    @property
    def consistency(self) -> float:
        """Share of recorded recoveries that used the most common fix."""
        return self.fixes.most_common(1)[0][1] / self.recovered if self.recovered else 0.0

    @property
    def score(self) -> float:
        """Sessions that hit it, weighted up when the recoveries agree on a fix."""
        return len(self.sessions) * (1 + self.consistency)

    def notice(self) -> str:
        """One line for the person at the keyboard; rule() is the full text for the agent."""
        subject = f"`{self.command or self.tools.most_common(1)[0][0]}`"
        what = (
            f"failed with `{self.sig}`"
            if self.kind == "text"
            else f"exited with code {self.sig.rsplit(' ', 1)[-1]} and no useful output"
        )
        if self.sig in SHELL_FIXES:
            after = SHELL_FIXES[self.sig]
        elif not self.fix:
            after = "no recovery on record"
        elif self.fix == RETRY and is_transient(self.sig):
            after = "it worked again on a later try"
        elif self.fix == RETRY:
            after = "a later, changed call worked, so fix the cause before running it again"
        else:
            after = f"sessions got past it by running `{self.fix}` first"
        return f"faildex: {subject} {what} in {len(self.sessions)} earlier sessions; {after}."

    def rule(self) -> str:
        subject = f"`{self.command or self.tools.most_common(1)[0][0]}`"
        head = (
            f"When {subject} fails with `{self.sig}`"
            if self.kind == "text"
            else f"When `{self.sig.rsplit(' exited ', 1)[0]}` exits with code "
            f"{self.sig.rsplit(' ', 1)[-1]} and prints nothing useful"
        )
        seen = f"seen in {len(self.sessions)} sessions, {self.calls} calls"
        if self.runs:
            seen += f", {self.calls / self.runs:.0%} of this command's {self.runs} runs"
        if self.sig in SHELL_FIXES:
            return f"{head} ({seen}): the shell stops before the command runs; {SHELL_FIXES[self.sig]}."
        if not self.fix:
            return f"{head} ({seen}): no recovery on record yet; stop and check before retrying."
        top = self.fixes.most_common(1)[0][1]
        share = f"{top} of {self.recovered} recoveries"
        if self.fix == RETRY and is_transient(self.sig):
            return f"{head} ({seen}): retry it; a later try of the same command worked ({share})."
        if self.fix == RETRY:
            return (
                f"{head} ({seen}): fix the cause, then run it again; a later, changed call "
                f"of the same command worked ({share})."
            )
        return f"{head} ({seen}): earlier sessions got past it by running `{self.fix}` first ({share})."

    @property
    def key(self) -> str:
        """The failure key a rules file is deduplicated on, whatever the rule's wording."""
        return self.sig


def failures(db, command: str | None = None) -> dict[str, Failure]:
    """Failure keys with their recoveries: all of them, or those of one command."""
    from faildex.normalize import shell_sig

    scope = _FOR_COMMAND if command else _ALL
    params = {"command": command} if command else {}
    found: dict[str, Failure] = {}
    for row in db.execute(scope + _FAILURES, params):
        sig = shell_sig(row["sig"]) or row["sig"]
        item = found.setdefault(sig, Failure(sig, row["kind"] or "text"))
        item.calls += 1
        fresh = row["session"] not in item.sessions
        item.sessions.add(row["session"])
        item.agents.add(row["agent"])
        item.tools[row["tool"]] += 1
        if row["command"]:
            item.commands[row["command"]] += 1
        pointer = f"{row['path']}:{row['line']}"
        # One pointer per session, so the evidence shows the failure really spread.
        if row["path"] and fresh and len(item.evidence) < 3 and pointer not in item.evidence:
            item.evidence.append(pointer)
    for row in db.execute(scope + _RECOVERIES, params):
        sig = shell_sig(row["sig"]) or row["sig"]
        item = found.get(sig)
        if item is None:
            continue
        item.recovered += 1
        step = row["step"] or row["tool"]
        retried = row["hops"] == 1 or step == row["command"]
        item.fixes[RETRY if retried else step] += 1
    return found


def proposals(db, min_sessions: int = 2, command: str | None = None) -> list[Failure]:
    """Failures worth a rule: seen in several sessions, best first."""
    keep = [f for f in failures(db, command).values() if len(f.sessions) >= min_sessions]
    return sorted(keep, key=lambda f: (-f.score, -f.calls, f.sig))


def warnings_for(
    db, command: str, min_sessions: int = 2, min_rate: float = MIN_RATE
) -> list[Failure]:
    """Recurring failures of one command that are frequent enough to warn about."""
    runs = next(iter(db.execute(_RUNS, {"command": command})))["n"]
    found = proposals(db, min_sessions, command)
    for item in found:
        item.runs = runs
    return [item for item in found if runs and item.calls / runs >= min_rate]


def warnings_for_line(
    db, line: str, min_sessions: int = 2
) -> tuple[list[str], list[tuple[str, Failure]]]:
    """(templates looked up, (template, warning) pairs) for a whole command line.

    A compound line is looked up part by part, so `ls && git status` warns for git.
    """
    from faildex.normalize import (
        EQUALS_SIG,
        NOMATCH_SIG,
        command_templates,
        has_unquoted_equals,
        has_unquoted_glob,
        shell_sig,
    )

    templates = command_templates(line)
    found = [
        (t, item)
        for t in templates
        for item in warnings_for(db, t, min_sessions)
        if shell_sig(item.sig) is None
    ]
    # NOMATCH and `=` expansion happen in the shell before any program runs, so
    # their evidence is pooled across commands and gated on the line itself.
    shell = [
        sig
        for sig, present in ((NOMATCH_SIG, has_unquoted_glob), (EQUALS_SIG, has_unquoted_equals))
        if present(line)
    ]
    if shell:
        pooled = failures(db)
        for sig in shell:
            item = pooled.get(sig)
            if item and len(item.sessions) >= min_sessions:
                item.commands = Counter({"zsh": item.calls})
                found.append(("zsh", item))
    return templates, found


MAX_DISPLAY_SIG = 79
LINE_WIDTH = 80


def _can_encode(text: str, encoding: str) -> bool:
    try:
        text.encode(encoding, errors="strict")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def safe_console_text(text: str, stream=None) -> str:
    """Replace glyphs the target console cannot encode so printing never crashes."""
    out_stream = stream if stream is not None else sys.stdout
    encoding = getattr(out_stream, "encoding", None) or "utf-8"
    if _can_encode(text, encoding):
        return text
    replacements = (("—", "--"), ("·", "|"), ("…", "..."), ("→", "->"), ("✓", "ok"), ("✕", "x"))
    cleaned = text
    for glyph, fallback in replacements:
        if glyph in cleaned and not _can_encode(glyph, encoding):
            cleaned = cleaned.replace(glyph, fallback)
    if _can_encode(cleaned, encoding):
        return cleaned
    try:
        return cleaned.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except LookupError:
        return cleaned.encode("ascii", errors="replace").decode("ascii")


def use_color(stream=None) -> bool:
    """True only when writing to a live terminal without NO_COLOR / dumb TERM."""
    out_stream = stream if stream is not None else sys.stdout
    isatty = getattr(out_stream, "isatty", None)
    if not callable(isatty) or not isatty():
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return os.environ.get("TERM") != "dumb"


def truncate_words(text: str, limit: int = MAX_DISPLAY_SIG, ellipsis: str = "…") -> str:
    """Shorten failure text at a word boundary without splitting mask tokens like <path>."""
    if len(text) <= limit and not (text.endswith("<") or _has_unclosed_tag(text)):
        return text
    body_limit = max(1, limit - len(ellipsis))
    head = text[:body_limit]
    unclosed = _unclosed_tag_start(head)
    if unclosed is not None:
        head = head[:unclosed]
        # Rewind to the previous word boundary when a mask tag was cut in half.
        cut = max(head.rfind(" "), head.rfind("\t"))
        if cut >= len(head) // 3:
            head = head[:cut]
    elif len(text) > body_limit and not text[body_limit].isspace():
        cut = max(head.rfind(" "), head.rfind("\t"))
        if cut >= len(head) // 3:
            head = head[:cut]
    head = head.rstrip(" \t.,;:([")
    if not head:
        head = text[:body_limit].rstrip()
    return head + ellipsis


def _unclosed_tag_start(text: str) -> int | None:
    pos = text.rfind("<")
    if pos >= 0 and text.find(">", pos) == -1:
        return pos
    return None


def _has_unclosed_tag(text: str) -> bool:
    return _unclosed_tag_start(text) is not None


def tilde_path(path: str | Path) -> str:
    """Replace a leading home directory path with `~`."""
    raw = str(path)
    home = str(Path.home())
    if not home:
        return raw
    if raw == home:
        return "~"
    for sep in ("/", "\\"):
        if raw.startswith(home + sep):
            return "~" + raw[len(home) :]
    return raw


def short_pointer(pointer: str, max_len: int = 48) -> str:
    """One compact log pointer (`path:line`) with `~` home prefix."""
    short = tilde_path(pointer)
    if len(short) <= max_len:
        return short
    path_part, sep, line_part = short.rpartition(":")
    if not sep or not line_part.isdigit():
        path_part, suffix = short, ""
    else:
        suffix = f":{line_part}"
    parts = [p for p in path_part.replace("\\", "/").split("/") if p]
    if len(parts) <= 2:
        name = parts[-1] if parts else path_part
        room = max(16, max_len - len(suffix) - 4)
        if len(name) > room:
            return f".../{name[:room]}...{suffix}"
        return f".../{name}{suffix}"
    if parts[0] == "~":
        head = f"~/{parts[1]}" if len(parts) >= 3 else "~"
    elif path_part.startswith("/"):
        head = f"/{parts[0]}"
    else:
        head = parts[0]
    tail = parts[-1]
    if len(tail) > 26:
        stem, dot, ext = tail.rpartition(".")
        if dot and len(ext) <= 8:
            tail = f"{stem[:8]}..{dot}{ext}"
        else:
            tail = f"{tail[:18]}..."
    candidate = f"{head}/.../{tail}{suffix}"
    if len(candidate) <= max_len:
        return candidate
    return f".../{tail}{suffix}"


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


def _subject(item: Failure) -> str:
    if item.command:
        return item.command
    if item.kind == "exit" and " exited " in item.sig:
        return item.sig.rsplit(" exited ", 1)[0]
    if item.tools:
        return item.tools.most_common(1)[0][0]
    return "command"


def _recovery_summary(item: Failure) -> str:
    """Failed calls that the same command later got past, within RECOVERY_HOPS calls."""
    return f"{item.recovered:,} of {item.calls:,} recovered within {RECOVERY_HOPS} calls"


def _action_line(item: Failure) -> str:
    """What to do, and how many of the recoveries back it (the `top of recovered` share)."""
    if item.sig in SHELL_FIXES:
        return f"{SHELL_FIXES[item.sig]}; the shell stops before any command runs."
    if not item.fix:
        return "stop and check before retrying; no recovery on record yet."
    top = item.fixes.most_common(1)[0][1]
    share = f"{top:,} of {item.recovered:,} {'recovery' if item.recovered == 1 else 'recoveries'}"
    if item.fix == RETRY:
        # Counts cover every command that hit this failure, so name one only when it is alone.
        what = f"`{_subject(item)}`" if len(item.commands) <= 1 else "the same command"
        if is_transient(item.sig):
            return f"retry {what}; a later try worked in {share}."
        what = what if len(item.commands) <= 1 else "it"
        return (
            f"fix the cause, then run {what} again; a later, changed call of the same "
            f"command worked in {share}."
        )
    return f"run `{item.fix}` first; {share} did that."


def render(
    items: list[Failure],
    *,
    show_evidence: bool = False,
    color: bool = False,
    encoding: str | None = None,
) -> str:
    """Readable numbered proposals with counts, recovery clarity, action, and evidence."""
    if not items:
        return "No failure has recurred across sessions yet."

    enc = encoding or getattr(sys.stdout, "encoding", None) or "utf-8"
    dash = "—" if _can_encode("—", enc) else "--"
    dot = "·" if _can_encode("·", enc) else "|"
    ellip = "…" if _can_encode("…", enc) else "..."

    def style(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if color else text

    blocks = []
    for number, item in enumerate(items, start=1):
        subject = f"`{_subject(item)}`"
        if len(item.commands) > 1:
            others = len(item.commands) - 1
            subject += f" +{others} more {_plural(others, 'command')}"
        if item.kind == "text":
            # Keep the whole first line within LINE_WIDTH columns.
            room = max(40, LINE_WIDTH - len(f"{number}. {subject} {dash} "))
            what = truncate_words(item.sig, min(room, MAX_DISPLAY_SIG), ellipsis=ellip)
        else:
            code = item.sig.rsplit(" ", 1)[-1]
            what = f"exited with code {code} (no error output)"

        head = f"{style(f'{number}.', '1')} {style(subject, '1')} {dash} {style(what, '31')}"
        counts = (
            f"{len(item.sessions):,} {_plural(len(item.sessions), 'session')}, "
            f"{item.calls:,} failed {_plural(item.calls, 'call')}"
        )
        rec = _recovery_summary(item)
        rec_styled = style(rec, "32" if item.recovered else "31")
        stats = f"   {counts} {dot} {rec_styled}"
        # Wrap the action under itself so every line stays within LINE_WIDTH columns.
        action = textwrap.wrap(
            f"   Action: {_action_line(item)}",
            LINE_WIDTH,
            subsequent_indent=" " * len("   Action: "),
            break_long_words=False,
            break_on_hyphens=False,
        )
        action[0] = action[0].replace("Action:", style("Action:", "1;36"), 1)

        lines = [head, stats, *action]
        if item.evidence:
            if show_evidence:
                ev_head = f"   evidence ({len(item.evidence)}):"
                lines.append(style(ev_head, "2"))
                for ptr in item.evidence:
                    lines.append(style(f"     {tilde_path(ptr)}", "2"))
            else:
                first_ptr = short_pointer(item.evidence[0])
                more = f", +{len(item.evidence) - 1} more" if len(item.evidence) > 1 else ""
                lines.append(style(f"   evidence ({len(item.evidence)}): {first_ptr}{more}", "2"))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


_RULE_TEXT = re.compile(r"^- When `[^`\n]*` fails with `(.*?)` \(seen", re.MULTILINE)
_RULE_EXIT = re.compile(r"^- When `(.*?)` exits with code (\S+) and prints nothing", re.MULTILINE)


def _rule_keys(text: str) -> set[str]:
    """Failure keys of the rules already in a file, older wordings and raw shell keys included."""
    from faildex.normalize import shell_sig

    keys = {shell_sig(sig) or sig for sig in _RULE_TEXT.findall(text)}
    keys |= {f"{command} exited {code}" for command, code in _RULE_EXIT.findall(text)}
    return keys


def approve(items: list[Failure], numbers: list[int], path) -> list[str]:
    """Append the chosen proposals to a rules file. Nothing is written unasked.

    A failure that already has a rule is skipped, even when the wording has changed since.
    """
    existing = path.read_text() if path.exists() else ""
    seen = _rule_keys(existing)
    chosen = []
    for n in numbers:
        if 0 < n <= len(items) and items[n - 1].key not in seen:
            seen.add(items[n - 1].key)
            chosen.append(items[n - 1])
    if chosen:
        with path.open("a") as out:
            if not existing:
                out.write("# Rules learned from recurring failures (faildex)\n\n")
            elif not existing.endswith("\n"):
                out.write("\n")
            for item in chosen:
                out.write(f"- {item.rule()}\n  Evidence: {', '.join(item.evidence)}\n")
    return [item.rule() for item in chosen]
