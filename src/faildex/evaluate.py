"""Measure how often agents repeat a failure that the graph already holds.

Sessions of each public dataset are ordered by start time and split once: the
first 70% are the earlier period (what faildex would have learned from) and the
last 30% are the later period (what it is scored on). No session is in both.
Sessions are ordered by (start time, id), so the split is exact even when
sessions start together. The cut is the start time of the first later session,
and an earlier session that was still running at the cut contributes only what
happened before it, so nothing from the scored period leaks into what was
"already known".

    recurrence   share of later-period failures whose failure key was already
                 seen in an earlier-period session
    warnable     share of those where an earlier session also shows the way
                 out for the same command and the same failure: that command
                 succeeding within a few calls after it failed. Command lines
                 that chain several programs prove no recovery and are skipped

Every number comes from Cypher over the committed store, so `make eval` gives
the same table on any machine.

A private store made by `faildex ingest` has no public datasets, so its sessions
are grouped by agent instead and split the same way, one agent at a time.

The same split also replays the pre-run hook's own rule (`insight.warns`) on the
later period, with only the earlier period known: would the hook have spoken
before each later shell call, and did the failure it named follow? Nobody was
warned in these logs, so this shows when the hook would have spoken, not what an
agent would have done. It looks only at the stored first program of each line,
and leaves out the two zsh rules, which need the raw command line.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

EARLIER_SHARE = 0.7
RECOVERY_HOPS = 5
# The earlier hook's cap: at most this many warnings before one command. The replay keeps it.
MAX_WARNINGS = 2

_SESSIONS = """
MATCH (d:Source {name: $source})<-[:FROM]-(s:Session)
WHERE s.started_at IS NOT NULL
RETURN s.id AS id, s.started_at AS started ORDER BY started, id
"""

_AGENT_SESSIONS = """
MATCH (s:Session {agent: $source})
WHERE s.started_at IS NOT NULL
RETURN s.id AS id, s.started_at AS started ORDER BY started, id
"""

# One row per later-period failure.
_LATER = """
MATCH (s:Session)-[:HAS_CALL]->(c:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.id IN $later
OPTIONAL MATCH (c)-[:RAN]->(k:Command)
RETURN c.id AS call, e.sig AS sig, e.kind AS kind, k.template AS command,
       coalesce(c.compound, false) AS compound
"""

_EARLIER_KEYS = """
MATCH (s:Session)-[:HAS_CALL]->(c:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.id IN $earlier AND c.ts < $cut
RETURN DISTINCT e.sig AS sig
"""

# Earlier-period (failure key, command) pairs with a recorded recovery: the
# command fails, then within a few calls of the same session it succeeds.
_RECOVERED = f"""
MATCH (s:Session)-[:HAS_CALL]->(f:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.id IN $earlier AND f.ts < $cut AND coalesce(f.compound, false) = false
MATCH (f)-[:RAN]->(k:Command)<-[:RAN]-(g:Call {{ok: true}})
WHERE g.ts < $cut AND g.ts >= f.ts AND coalesce(g.compound, false) = false
MATCH (f)-[:NEXT*1..{RECOVERY_HOPS}]->(g)
RETURN DISTINCT e.sig AS sig, k.template AS command
"""

_SHARED = """
MATCH (a:Session)-[:HAS_CALL]->(:Call)-[:FAILED_WITH]->(e:ErrorSig)
WITH e, collect(DISTINCT a.agent) AS agents
WHERE size(agents) > 1
RETURN e.sig AS sig ORDER BY sig
"""

# What the earlier period tells the hook: runs per command, and per (command, failure)
# the failed calls and the sessions they were in. `$cut` None means every call.
_HOOK_RUNS = """
MATCH (s:Session)-[:HAS_CALL]->(c:Call)-[:RAN]->(k:Command)
WHERE s.id IN $earlier AND ($cut IS NULL OR c.ts < $cut)
RETURN k.template AS command, count(c) AS runs
"""

_HOOK_FAILURES = """
MATCH (s:Session)-[:HAS_CALL]->(c:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.id IN $earlier AND ($cut IS NULL OR c.ts < $cut)
MATCH (c)-[:RAN]->(k:Command)
RETURN k.template AS command, e.sig AS sig, e.kind AS kind,
       count(c) AS calls, count(DISTINCT s.id) AS sessions
"""

# Every later-period call, with its command and failure if any.
_HOOK_LATER = """
MATCH (s:Session)-[:HAS_CALL]->(c:Call)
WHERE s.id IN $later
OPTIONAL MATCH (c)-[:RAN]->(k:Command)
OPTIONAL MATCH (c)-[:FAILED_WITH]->(e:ErrorSig)
RETURN c.id AS call, s.id AS session, c.tool AS tool, c.ok AS ok,
       k.template AS command, e.sig AS sig, e.kind AS kind
ORDER BY call
"""

_SOURCES = "MATCH (d:Source) RETURN d.name AS name ORDER BY name"
_AGENTS = (
    "MATCH (s:Session) WHERE s.agent IS NOT NULL RETURN DISTINCT s.agent AS name ORDER BY name"
)


@dataclass(frozen=True)
class Result:
    source: str
    earlier_sessions: int
    later_sessions: int
    later_failures: int
    recurring: int
    warnable: int
    later_keys: frozenset[str] = frozenset()
    recurring_keys: frozenset[str] = frozenset()
    by_key: tuple[tuple[str, int], ...] = ()

    @property
    def recurrence(self) -> float:
        return self.recurring / self.later_failures if self.later_failures else 0.0

    @property
    def warnable_share(self) -> float:
        return self.warnable / self.recurring if self.recurring else 0.0


@dataclass(frozen=True)
class Rule:
    """One failure the hook would warn about before a command, and what it was told."""

    command: str
    sig: str
    calls: int
    runs: int
    sessions: int


@dataclass(frozen=True)
class RuleOutcome:
    rule: Rule
    warned: int  # later shell calls of the command that got this warning
    came_true: int  # of those, calls that failed with this failure
    runs: int = 0  # later shell calls of the command, warned or not (past the cap)


# How far each later-period failure got towards a warning, in order.
STAGES = ("failure", "shell", "named", "known", "command", "sessions", "rate", "cap")


@dataclass(frozen=True)
class HookReplay:
    source: str
    funnel: tuple[int, ...]  # later failures still in at each of STAGES
    shell_calls: int
    warned: int
    warned_ok: int
    came_true: int
    came_true_sessions: tuple[int, ...]  # per session that had any, largest first
    rules: tuple[RuleOutcome, ...] = ()
    stages: tuple[tuple[str, str], ...] = ()  # (call, last stage reached) per later failure

    @property
    def other(self) -> int:
        return self.warned - self.warned_ok - self.came_true


def shell_tools() -> frozenset[str]:
    """The tool name each agent's log gives its shell; the hook runs before these."""
    from faildex.adapters import antigravity, claude_code, codex, codex_local, cursor

    names = {m.SHELL_TOOL for m in (antigravity, claude_code, codex, cursor)}
    return frozenset(names | {codex_local.TOOL})  # local Codex logs only shell commands


def _earlier(db, earlier: list[str], cut: str | None):
    runs = {
        row["command"]: row["runs"]
        for row in db.execute(_HOOK_RUNS, {"earlier": earlier, "cut": cut})
    }
    seen = {
        (row["command"], row["sig"]): (row["calls"], row["sessions"])
        for row in db.execute(_HOOK_FAILURES, {"earlier": earlier, "cut": cut})
    }
    return runs, seen


def hook_rules(
    db, earlier: list[str], cut: str | None, min_sessions: int = 2
) -> dict[str, list[Rule]]:
    """What the hook would warn about, per command, knowing only `earlier` before `cut`.

    Each command is looked up with the hook's own `insight.warnings_for`, limited to
    what was known then, so the rules and their order are the hook's. The two zsh rules
    are left out: they are decided on the raw command line, which the store does not keep.
    """
    from faildex.insight import warnings_for, warns
    from faildex.normalize import shell_sig

    runs, seen = _earlier(db, earlier, cut)
    # Only a command with a failure that clears the rule can get a warning; look up those.
    candidates = sorted(
        {
            command
            for (command, sig), (calls, sessions) in seen.items()
            if warns(calls, sessions, runs.get(command, 0), min_sessions)
        }
    )
    rules: dict[str, list[Rule]] = {}
    for command in candidates:
        found = [
            Rule(command, item.sig, item.calls, item.runs, len(item.sessions))
            for item in warnings_for(db, command, min_sessions, sessions=earlier, cut=cut)
            if shell_sig(item.sig) is None
        ]
        if found:
            rules[command] = found
    return rules


def replay_source(
    db,
    source: str,
    kinds: tuple[str, ...] = ("text", "exit"),
    by: str = "dataset",
    min_sessions: int = 2,
    max_warnings: int | None = None,
) -> HookReplay | None:
    """Replay the hook on one dataset's (or agent's) later period."""
    from faildex.insight import MIN_RATE

    max_warnings = MAX_WARNINGS if max_warnings is None else max_warnings

    rows = db.execute(_AGENT_SESSIONS if by == "agent" else _SESSIONS, {"source": source})
    parts = split([(row["id"], row["started"]) for row in rows])
    if parts is None:
        return None
    earlier_ids, later_ids, cut = parts
    runs, seen = _earlier(db, earlier_ids, cut)
    known = {row["sig"] for row in db.execute(_EARLIER_KEYS, {"earlier": earlier_ids, "cut": cut})}
    rules = hook_rules(db, earlier_ids, cut, min_sessions)
    spoken = {command: found[:max_warnings] for command, found in rules.items()}
    shells = shell_tools()

    funnel = Counter()
    stages = []
    shell_calls = warned = warned_ok = 0
    true_sessions: Counter = Counter()
    per_rule_warned: Counter = Counter()
    per_rule_true: Counter = Counter()
    later_commands: Counter = Counter()
    for row in db.execute(_HOOK_LATER, {"later": later_ids}):
        shell = row["tool"] in shells
        command = row["command"] if shell else None
        said = spoken.get(command, []) if command else []
        if shell:
            shell_calls += 1
            later_commands[command] += 1
        if said:
            warned += 1
            warned_ok += bool(row["ok"])
            for rule in said:
                per_rule_warned[rule] += 1
        keyed = row["sig"] is not None and row["kind"] in kinds
        if keyed and any(rule.sig == row["sig"] for rule in said):
            true_sessions[row["session"]] += 1
            per_rule_true[next(r for r in said if r.sig == row["sig"])] += 1
        if not keyed:
            continue
        calls, sessions = seen.get((command, row["sig"]), (0, 0))
        reached = [
            True,
            shell,
            command is not None,
            row["sig"] in known,
            calls > 0,
            sessions >= min_sessions,
            calls > 0 and calls / max(runs.get(command, 0), 1) >= MIN_RATE,
            any(rule.sig == row["sig"] for rule in said),
        ]
        last = 0
        while last + 1 < len(reached) and reached[last + 1]:
            last += 1
        for stage in STAGES[: last + 1]:
            funnel[stage] += 1
        stages.append((row["call"], STAGES[last]))
    outcomes = tuple(
        RuleOutcome(rule, per_rule_warned[rule], per_rule_true[rule], later_commands[rule.command])
        for found in rules.values()
        for rule in found
    )
    return HookReplay(
        source=source,
        funnel=tuple(funnel[stage] for stage in STAGES),
        shell_calls=shell_calls,
        warned=warned,
        warned_ok=warned_ok,
        came_true=sum(true_sessions.values()),
        came_true_sessions=tuple(sorted(true_sessions.values(), reverse=True)),
        rules=outcomes,
        stages=tuple(stages),
    )


def replay(db, kinds: tuple[str, ...] = ("text", "exit")) -> list[HookReplay]:
    """The hook replay per dataset (or agent), then all of them together."""
    by, names = groups(db)
    found = [r for r in (replay_source(db, name, kinds, by) for name in names) if r]
    if not found:
        return []
    every = HookReplay(
        "all",
        tuple(sum(r.funnel[i] for r in found) for i in range(len(STAGES))),
        sum(r.shell_calls for r in found),
        sum(r.warned for r in found),
        sum(r.warned_ok for r in found),
        sum(r.came_true for r in found),
        tuple(sorted((n for r in found for n in r.came_true_sessions), reverse=True)),
        tuple(o for r in found for o in r.rules),
        tuple(pair for r in found for pair in r.stages),
    )
    return [*found, every]


def split(sessions: list[tuple[str, str]]) -> tuple[list[str], list[str], str] | None:
    """(earlier ids, later ids, cut) for sessions given as (id, start) in start order."""
    index = int(len(sessions) * EARLIER_SHARE)
    if not 0 < index < len(sessions):
        return None
    ids = [session for session, _ in sessions]
    return ids[:index], ids[index:], sessions[index][1]


def groups(db) -> tuple[str, list[str]]:
    """("dataset", public dataset names), or ("agent", agent names) for a store without any."""
    names = [row["name"] for row in db.execute(_SOURCES)]
    if names:
        return "dataset", names
    return "agent", [row["name"] for row in db.execute(_AGENTS)]


def evaluate_source(
    db, source: str, kinds: tuple[str, ...] = ("text", "exit"), by: str = "dataset"
) -> Result | None:
    rows = db.execute(_AGENT_SESSIONS if by == "agent" else _SESSIONS, {"source": source})
    parts = split([(row["id"], row["started"]) for row in rows])
    if parts is None:
        return None
    earlier_ids, later_ids, cut = parts
    params = {"earlier": earlier_ids, "cut": cut}
    earlier = {row["sig"] for row in db.execute(_EARLIER_KEYS, params)}
    recovered = {(row["sig"], row["command"]) for row in db.execute(_RECOVERED, params)}
    later = [r for r in db.execute(_LATER, {"later": later_ids}) if r["kind"] in kinds]
    recurring = [row for row in later if row["sig"] in earlier]
    tally: dict[str, int] = {}
    for row in recurring:
        tally[row["sig"]] = tally.get(row["sig"], 0) + 1
    return Result(
        source=source,
        earlier_sessions=len(earlier_ids),
        later_sessions=len(later_ids),
        later_failures=len(later),
        recurring=len(recurring),
        warnable=sum(
            1
            for row in recurring
            if not row["compound"] and (row["sig"], row["command"]) in recovered
        ),
        later_keys=frozenset(row["sig"] for row in later),
        recurring_keys=frozenset(row["sig"] for row in recurring),
        by_key=tuple(sorted(tally.items())),
    )


def total(results: list[Result]) -> Result:
    def add(name: str) -> int:
        return sum(getattr(r, name) for r in results)

    tally: dict[str, int] = {}
    for result in results:
        for sig, count in result.by_key:
            tally[sig] = tally.get(sig, 0) + count
    return Result(
        "all",
        add("earlier_sessions"),
        add("later_sessions"),
        add("later_failures"),
        add("recurring"),
        add("warnable"),
        frozenset().union(*(r.later_keys for r in results)),
        frozenset().union(*(r.recurring_keys for r in results)),
        tuple(sorted(tally.items())),
    )


def evaluate(db, kinds: tuple[str, ...] = ("text", "exit")) -> list[Result]:
    by, names = groups(db)
    results = [r for r in (evaluate_source(db, name, kinds, by) for name in names) if r]
    return [*results, total(results)] if results else []


def top_recurring(result: Result, limit: int = 8) -> list[tuple[str, int]]:
    """The failure keys that account for most recurring later-period failures."""
    return sorted(result.by_key, key=lambda item: (-item[1], item[0]))[:limit]


def shared_keys(db) -> list[str]:
    """Failure keys seen under more than one agent."""
    return [row["sig"] for row in db.execute(_SHARED)]


def _table(results: list[Result], by: str = "dataset") -> list[str]:
    from faildex.i18n import pad, t, width

    columns = [
        (t(f"eval.by.{by}"), 20, "<"),
        (t("eval.col.sessions"), 10, ">"),
        (t("eval.col.failures"), 10, ">"),
        (t("eval.col.recurring"), 11, ">"),
        (t("eval.col.recurrence"), 12, ">"),
        (t("eval.col.warnable"), 10, ">"),
        (t("eval.col.of_recurring"), 14, ">"),
    ]
    head = "".join(pad(name, size, align) for name, size, align in columns)
    lines = [head, "-" * width(head)]
    for r in results:
        sessions = f"{r.earlier_sessions}/{r.later_sessions}"
        name = t("eval.all") if r.source == "all" else r.source
        lines.append(
            f"{pad(name, 20)}{sessions:>10}{r.later_failures:>10}{r.recurring:>11}"
            f"{r.recurrence:>12.1%}{r.warnable:>10}{r.warnable_share:>14.1%}"
        )
    return lines


def report(db, report_command: str = "faildex report") -> str:
    from faildex.i18n import t, tn

    by, names = groups(db)
    both = evaluate(db)
    text_only = evaluate(db, kinds=("text",))
    label = t(f"eval.by.{by}")
    lines = []
    if by == "agent":
        lines.append(t("eval.by_agent"))
    lines += [
        t("eval.split", share=f"{EARLIER_SHARE:.0%}", by=label),
        t("eval.legend"),
    ]
    if not both:
        groups_found = tn("eval.groups", len(names), count=len(names), by=label)
        lines += [
            "",
            t("eval.nothing", by=label, groups=groups_found, command=report_command),
        ]
        return "\n".join(lines)
    lines += [
        "",
        t("eval.all_keys"),
        *_table(both, by),
        "",
        t("eval.text_only"),
        *_table(text_only, by),
    ]
    if both:
        keys = both[-1]
        lines += [
            "",
            t("eval.distinct", later=len(keys.later_keys), seen=len(keys.recurring_keys)),
        ]
    top = top_recurring(both[-1]) if both else []
    if top:
        lines += ["", t("eval.by_key")]
        lines += [f"  {count:>4}  {sig}" for sig, count in top]
        without = both[-1].recurring - top[0][1]
        base = both[-1].later_failures - top[0][1]
        if base:
            lines.append(
                t("eval.without_top", without=without, base=base, share=f"{without / base:.1%}")
            )
    shared = shared_keys(db)
    lines.append(t("eval.shared", count=len(shared)))
    lines += [f"  {sig}" for sig in shared]
    replays = replay(db)
    if replays:
        lines += ["", *_hook_lines(replays[-1], by)]
    return "\n".join(lines)


def _short(text: str, size: int) -> str:
    return text if len(text) <= size else text[: size - 3].rstrip() + "..."


def _hook_lines(r: HookReplay, by: str = "dataset", min_sessions: int = 2) -> list[str]:
    """The replay as text: the funnel, what the warned calls did, and the rules that spoke."""
    max_warnings = MAX_WARNINGS
    from faildex.i18n import pad, t, width, wrap
    from faildex.insight import MIN_RATE

    rate = f"{MIN_RATE:.0%}"
    lines = [
        *wrap(t("eval.hook.title", sessions=min_sessions, rate=rate, cap=max_warnings), 88, ""),
        # Public datasets were logged without faildex; a private store may hold warned calls.
        *wrap(t("eval.hook.note" if by == "dataset" else "eval.hook.note_agent"), 88, ""),
        "",
    ]
    for depth, (stage, count) in enumerate(zip(STAGES, r.funnel)):
        label = t(f"eval.hook.stage.{stage}", sessions=min_sessions, rate=rate, cap=max_warnings)
        lines.append(f"{pad('  ' * min(depth, 1) + label, 56)}{count:>6}")
    lines.append("")
    if not r.warned:
        lines.append(t("eval.hook.none"))
    else:
        share = f"{r.warned / r.shell_calls:.1%}"
        lines += wrap(
            t(
                "eval.hook.warned",
                warned=f"{r.warned:,}",
                calls=f"{r.shell_calls:,}",
                share=share,
                ok=f"{r.warned_ok:,}",
                true=r.came_true,
                other=r.other,
            ),
            88,
            "  ",
        )
    if r.came_true:
        lines.append(
            t(
                "eval.hook.sessions",
                true=r.came_true,
                sessions=len(r.came_true_sessions),
                most=r.came_true_sessions[0],
            )
        )
    spoke = sorted(
        (o for o in r.rules if o.warned),
        key=lambda o: (-o.warned, -o.came_true, o.rule.command, o.rule.sig),
    )
    if spoke:
        columns = [
            (t("eval.hook.col.command"), 14, "<"),
            (t("eval.hook.col.failure"), 42, "<"),
            (t("eval.hook.col.earlier"), 30, "<"),
            (t("eval.hook.col.warned"), 8, ">"),
            (t("eval.hook.col.true"), 10, ">"),
        ]
        head = "".join(pad(name, size, align) for name, size, align in columns)
        lines += ["", t("eval.hook.rules"), head, "-" * width(head)]
        for o in spoke:
            earlier = t(
                "eval.hook.earlier", calls=o.rule.calls, runs=o.rule.runs, sessions=o.rule.sessions
            )
            lines.append(
                f"{pad(_short(o.rule.command, 13), 14)}{pad(_short(o.rule.sig, 40), 42)}"
                f"{pad(earlier, 30)}{o.warned:>8}{o.came_true:>10}"
            )
    absent = sum(1 for o in r.rules if not o.runs)
    capped = sum(1 for o in r.rules if o.runs and not o.warned)
    if absent:
        lines.append(t("eval.hook.silent", count=absent))
    if capped:
        lines.append(t("eval.hook.capped", count=capped, cap=max_warnings))
    lines += ["", *wrap(t("eval.hook.limits"), 88, "  ")]
    return lines
