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
"""

from __future__ import annotations

from dataclasses import dataclass

EARLIER_SHARE = 0.7
RECOVERY_HOPS = 5

_SESSIONS = """
MATCH (d:Source {name: $source})<-[:FROM]-(s:Session)
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

_SOURCES = "MATCH (d:Source) RETURN d.name AS name ORDER BY name"


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


def split(sessions: list[tuple[str, str]]) -> tuple[list[str], list[str], str] | None:
    """(earlier ids, later ids, cut) for sessions given as (id, start) in start order."""
    index = int(len(sessions) * EARLIER_SHARE)
    if not 0 < index < len(sessions):
        return None
    ids = [session for session, _ in sessions]
    return ids[:index], ids[index:], sessions[index][1]


def evaluate_source(db, source: str, kinds: tuple[str, ...] = ("text", "exit")) -> Result | None:
    rows = db.execute(_SESSIONS, {"source": source})
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
    names = [row["name"] for row in db.execute(_SOURCES)]
    results = [r for r in (evaluate_source(db, name, kinds) for name in names) if r]
    return [*results, total(results)] if results else []


def top_recurring(result: Result, limit: int = 8) -> list[tuple[str, int]]:
    """The failure keys that account for most recurring later-period failures."""
    return sorted(result.by_key, key=lambda item: (-item[1], item[0]))[:limit]


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
                f"Distinct later-period failure keys: {len(keys.later_keys)}, "
                f"already seen earlier: {len(keys.recurring_keys)}"
            ),
        ]
    top = top_recurring(both[-1]) if both else []
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
