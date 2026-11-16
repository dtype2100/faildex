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

from collections import Counter
from dataclasses import dataclass, field

RECOVERY_HOPS = 5
# A warning must be worth the interruption: the failure has to account for at
# least this share of the command's runs. Otherwise every `ls` would carry one.
MIN_RATE = 0.03

_RUNS = "MATCH (:Command {template: $command})<-[:RAN]-(c:Call) RETURN count(c) AS n"
RETRY = "retry"

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
        if not self.fix:
            return f"{head} ({seen}): no recovery on record yet; stop and check before retrying."
        how = (
            "the same command succeeded on a later try in the same session"
            if self.fix == RETRY
            else f"earlier sessions got past it by running `{self.fix}` first"
        )
        top = self.fixes.most_common(1)[0][1]
        return f"{head} ({seen}): {how} ({top} of {self.recovered} recoveries)."


def failures(db, command: str | None = None) -> dict[str, Failure]:
    """Failure keys with their recoveries: all of them, or those of one command."""
    scope = _FOR_COMMAND if command else _ALL
    params = {"command": command} if command else {}
    found: dict[str, Failure] = {}
    for row in db.execute(scope + _FAILURES, params):
        item = found.setdefault(row["sig"], Failure(row["sig"], row["kind"] or "text"))
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
        item = found.get(row["sig"])
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


def render(items: list[Failure]) -> str:
    """Numbered proposals with their evidence pointers."""
    lines = []
    for number, item in enumerate(items, start=1):
        lines.append(f"{number}. {item.rule()}")
        lines.append(f"   evidence: {', '.join(item.evidence)}")
    return "\n".join(lines) if lines else "No failure has recurred across sessions yet."


def approve(items: list[Failure], numbers: list[int], path) -> list[str]:
    """Append the chosen proposals to a rules file. Nothing is written unasked."""
    chosen = [items[n - 1] for n in numbers if 0 < n <= len(items)]
    existing = path.read_text() if path.exists() else ""
    added = [item.rule() for item in chosen if item.rule() not in existing]
    if added:
        with path.open("a") as out:
            if not existing:
                out.write("# Rules learned from recurring failures (faildex)\n\n")
            for item in chosen:
                if item.rule() in added:
                    out.write(f"- {item.rule()}\n  Evidence: {', '.join(item.evidence)}\n")
    return added
