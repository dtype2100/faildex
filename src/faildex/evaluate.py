"""Measure how often agents repeat a failure that the graph already holds.

Sessions of each public dataset are ordered by start time and split once: the
first 70% are the earlier period (what faildex would have learned from) and the
last 30% are the later period (what it is scored on). No session is in both.

    recurrence   share of later-period failures whose failure key was already
                 seen in an earlier-period session
    warnable     share of those where an earlier session also shows the way
                 out: the same command succeeding within a few calls after
                 the failure

Every number comes from Cypher over the committed store, so `make eval` gives
the same table on any machine.
"""

from __future__ import annotations

from dataclasses import dataclass

EARLIER_SHARE = 0.7
RECOVERY_HOPS = 5

_STARTS = """
MATCH (d:Source {name: $source})<-[:FROM]-(s:Session)
WHERE s.started_at IS NOT NULL
RETURN s.started_at AS started ORDER BY started
"""

# One row per later-period failure, with whether its key was seen earlier.
_LATER = """
MATCH (d:Source {name: $source})<-[:FROM]-(s:Session)-[:HAS_CALL]->(c:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.started_at >= $cut
RETURN c.id AS call, e.sig AS sig, e.kind AS kind
"""

_EARLIER_KEYS = """
MATCH (d:Source {name: $source})<-[:FROM]-(s:Session)-[:HAS_CALL]->(:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.started_at < $cut
RETURN e.sig AS sig, count(DISTINCT s) AS sessions
"""

# Earlier-period keys with a recorded recovery: failure, then within a few
# calls of the same session the same command succeeds.
_RECOVERED_KEYS = f"""
MATCH (d:Source {{name: $source}})<-[:FROM]-(s:Session)-[:HAS_CALL]->(f:Call)-[:FAILED_WITH]->(e:ErrorSig)
WHERE s.started_at < $cut
MATCH (f)-[:RAN]->(k:Command)<-[:RAN]-(g:Call {{ok: true}})
MATCH (f)-[:NEXT*1..{RECOVERY_HOPS}]->(g)
RETURN DISTINCT e.sig AS sig
"""

_SHARED = """
MATCH (a:Session)-[:HAS_CALL]->(:Call)-[:FAILED_WITH]->(e:ErrorSig)
WITH e, collect(DISTINCT a.agent) AS agents
WHERE size(agents) > 1
RETURN e.sig AS sig ORDER BY sig
"""

_SOURCES = "MATCH (d:Source) RETURN d.name AS name ORDER BY name"


@dataclass(frozen=True)
class Result:
    source: str
    earlier_sessions: int
    later_sessions: int
    later_failures: int
    recurring: int
    warnable: int
    later_keys: int
    recurring_keys: int

    @property
    def recurrence(self) -> float:
        return self.recurring / self.later_failures if self.later_failures else 0.0

    @property
    def warnable_share(self) -> float:
        return self.warnable / self.recurring if self.recurring else 0.0


def cutoff(starts: list[str]) -> str | None:
    """Start time of the first later-period session."""
    index = int(len(starts) * EARLIER_SHARE)
    return starts[index] if 0 < index < len(starts) else None


def evaluate_source(db, source: str, kinds: tuple[str, ...] = ("text", "exit")) -> Result | None:
    starts = [row["started"] for row in db.execute(_STARTS, {"source": source})]
    cut = cutoff(starts)
    if cut is None:
        return None
    params = {"source": source, "cut": cut}
    earlier = {row["sig"] for row in db.execute(_EARLIER_KEYS, params)}
    recovered = {row["sig"] for row in db.execute(_RECOVERED_KEYS, params)}
    later = [row for row in db.execute(_LATER, params) if row["kind"] in kinds]
    recurring = [row for row in later if row["sig"] in earlier]
    return Result(
        source=source,
        earlier_sessions=sum(1 for s in starts if s < cut),
        later_sessions=sum(1 for s in starts if s >= cut),
        later_failures=len(later),
        recurring=len(recurring),
        warnable=sum(1 for row in recurring if row["sig"] in recovered),
        later_keys=len({row["sig"] for row in later}),
        recurring_keys=len({row["sig"] for row in recurring}),
    )


def total(results: list[Result]) -> Result:
    def add(name: str) -> int:
        return sum(getattr(r, name) for r in results)

    return Result(
        "all",
        *(
            add(n)
            for n in (
                "earlier_sessions",
                "later_sessions",
                "later_failures",
                "recurring",
                "warnable",
                "later_keys",
                "recurring_keys",
            )
        ),
    )


def evaluate(db, kinds: tuple[str, ...] = ("text", "exit")) -> list[Result]:
    names = [row["name"] for row in db.execute(_SOURCES)]
    results = [r for r in (evaluate_source(db, name, kinds) for name in names) if r]
    return [*results, total(results)] if results else []


def top_recurring(db, limit: int = 8) -> list[tuple[str, int]]:
    """The failure keys that account for most recurring later-period failures."""
    tally: dict[str, int] = {}
    for name in [row["name"] for row in db.execute(_SOURCES)]:
        starts = [row["started"] for row in db.execute(_STARTS, {"source": name})]
        cut = cutoff(starts)
        if cut is None:
            continue
        params = {"source": name, "cut": cut}
        earlier = {row["sig"] for row in db.execute(_EARLIER_KEYS, params)}
        for row in db.execute(_LATER, params):
            if row["sig"] in earlier:
                tally[row["sig"]] = tally.get(row["sig"], 0) + 1
    return sorted(tally.items(), key=lambda item: (-item[1], item[0]))[:limit]


def shared_keys(db) -> list[str]:
    """Failure keys seen under more than one agent."""
    return [row["sig"] for row in db.execute(_SHARED)]


def _table(results: list[Result]) -> list[str]:
    head = (
        f"{'dataset':<20}{'sessions':>10}{'failures':>10}{'recurring':>11}"
        f"{'recurrence':>12}{'warnable':>10}{'of recurring':>14}"
    )
    lines = [head, "-" * len(head)]
    for r in results:
        sessions = f"{r.earlier_sessions}/{r.later_sessions}"
        lines.append(
            f"{r.source:<20}{sessions:>10}{r.later_failures:>10}{r.recurring:>11}"
            f"{r.recurrence:>12.1%}{r.warnable:>10}{r.warnable_share:>14.1%}"
        )
    return lines


def report(db) -> str:
    both = evaluate(db)
    text_only = evaluate(db, kinds=("text",))
    lines = [
        (
            f"Split: first {EARLIER_SHARE:.0%} of each dataset's sessions by start time "
            "= earlier, the rest = later."
        ),
        "sessions = earlier/later; failures = later-period failed calls with a failure key.",
        "",
        "All failure keys (failure text, or command + exit code when nothing usable was printed)",
        *_table(both),
        "",
        "Failure text only",
        *_table(text_only),
    ]
    if both:
        keys = both[-1]
        lines += [
            "",
            (
                f"Distinct later-period failure keys: {keys.later_keys}, "
                f"already seen earlier: {keys.recurring_keys}"
            ),
        ]
    top = top_recurring(db)
    if top:
        lines += ["", "Recurring later-period failures by key"]
        lines += [f"  {count:>4}  {sig}" for sig, count in top]
        without = both[-1].recurring - top[0][1]
        base = both[-1].later_failures - top[0][1]
        if base:
            lines.append(
                f"Recurrence without the most common key: {without}/{base} = {without / base:.1%}"
            )
    shared = shared_keys(db)
    lines.append(f"Failure keys seen under more than one agent: {len(shared)}")
    lines += [f"  {sig}" for sig in shared]
    return "\n".join(lines)
