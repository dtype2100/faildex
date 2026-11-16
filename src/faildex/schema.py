"""Graph schema and the single write path into the store.

Nodes
    Session  key: id = "<agent>:<session_id>"
    Call     key: id = "<agent>:<session_id>:<seq>"
    Command  key: template   (normalized command, shared across sessions)
    ErrorSig key: sig        (failure key, shared across sessions; kind "text" is
                             normalized failure text, kind "exit" is
                             "<command> exited <code>" for failures that printed
                             nothing usable)

Relationships
    (Session)-[:HAS_CALL]->(Call)
    (Call)-[:NEXT]->(Call)          consecutive calls of one session, by seq
    (Call)-[:RAN]->(Command)
    (Call)-[:FAILED_WITH]->(ErrorSig)

Every write is a MERGE on the key, so ingesting the same records twice
leaves the graph unchanged. Each key has a uniqueness constraint, which also
gives MERGE and MATCH an index: without one, loading 4,000 calls takes a minute
instead of half a second. Raw text never enters the graph: a Call keeps
only a pointer (source_path, source_line) to where it came from.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from itertools import pairwise

from faildex.normalize import SCRIPT

BATCH = 2000
# Programs that exit 1 to say "no match" or "differs".
NO_RESULT = frozenset(
    (program, 1)
    for program in (
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "findstr",
        "diff",
        "git diff",
        "cmp",
        "test",
        "pgrep",
        "which",
        "Select-String",
        "Test-Path",
        "Get-Command",
    )
)


@dataclass(frozen=True)
class CallRecord:
    """One tool call, in the shape every adapter produces."""

    agent: str
    session_id: str
    seq: int
    tool: str
    ok: bool
    ts: str | None = None
    command: str | None = None
    error_sig: str | None = None
    source_path: str | None = None
    source_line: int | None = None
    exit_code: int | None = None

    @property
    def session_key(self) -> str:
        return f"{self.agent}:{self.session_id}"

    @property
    def call_key(self) -> str:
        return f"{self.session_key}:{self.seq}"

    @property
    def failure(self) -> tuple[str, str] | None:
        """(key, kind) of a failed call, or None when nothing identifies the failure."""
        if self.ok:
            return None
        if self.error_sig:
            return self.error_sig, "text"
        if (self.command, self.exit_code) in NO_RESULT:
            return None  # "nothing matched" is an answer, not a failure worth a key
        if self.command and self.command != SCRIPT and self.exit_code is not None:
            return f"{self.command} exited {self.exit_code}", "exit"
        return None


KEYS = {"Session": "id", "Call": "id", "Command": "template", "ErrorSig": "sig"}


def ensure_schema(db) -> None:
    """Create the key constraints. Safe to call on a store that already has them."""
    for label, key in KEYS.items():
        db.execute(
            f"CREATE CONSTRAINT {label.lower()}_{key} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        )


_CALLS = """
UNWIND $rows AS row
MERGE (s:Session {id: row.session_key})
  ON CREATE SET s.agent = row.agent, s.session_id = row.session_id
  SET s.started_at = CASE
        WHEN s.started_at IS NULL OR row.started_at < s.started_at THEN row.started_at
        ELSE s.started_at END
MERGE (c:Call {id: row.call_key})
  SET c.seq = row.seq, c.tool = row.tool, c.ok = row.ok, c.ts = row.ts, c.exit_code = row.exit_code,
      c.source_path = row.source_path, c.source_line = row.source_line
MERGE (s)-[:HAS_CALL]->(c)
"""

_COMMANDS = """
UNWIND $rows AS row
MATCH (c:Call {id: row.call_key})
MERGE (k:Command {template: row.command})
MERGE (c)-[:RAN]->(k)
"""

_ERRORS = """
UNWIND $rows AS row
MATCH (c:Call {id: row.call_key})
MERGE (e:ErrorSig {sig: row.failure})
  ON CREATE SET e.kind = row.kind
MERGE (c)-[:FAILED_WITH]->(e)
"""

_NEXT = """
UNWIND $rows AS row
MATCH (a:Call {id: row.prev}), (b:Call {id: row.next})
MERGE (a)-[:NEXT]->(b)
"""


def _batches(rows: list[dict]) -> Iterable[list[dict]]:
    for i in range(0, len(rows), BATCH):
        yield rows[i : i + BATCH]


def _run(db, query: str, rows: list[dict]) -> None:
    for batch in _batches(rows):
        db.execute(query, {"rows": batch})


_CLEAR = """
UNWIND $rows AS row
MATCH (c:Call {id: row.call_key})-[r:RAN|FAILED_WITH]->()
DELETE r
"""

_SESSION_CALLS = """
UNWIND $rows AS row
MATCH (s:Session {id: row.session_key})-[:HAS_CALL]->(c:Call)
RETURN s.id AS session, c.id AS call, c.seq AS seq
"""

_UNLINK = """
UNWIND $rows AS row
MATCH (s:Session {id: row.session_key})-[:HAS_CALL]->(:Call)-[r:NEXT]->()
DELETE r
"""


def utc(ts: str | None) -> str | None:
    """One spelling per instant, so that string order is time order."""
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ingest(db, records: Iterable[CallRecord]) -> int:
    """Write records into the graph. Returns the number of calls written.

    A call that is ingested again replaces what was known about it, and the
    NEXT chain of every touched session is rebuilt from the calls the graph
    holds, so partial and repeated loads end in the same graph as one load.
    """
    ensure_schema(db)
    unique = {r.call_key: replace(r, ts=utc(r.ts)) for r in records}
    recs = sorted(unique.values(), key=lambda r: (r.session_key, r.seq))
    started: dict[str, str] = {}
    for r in recs:
        if r.ts and r.ts < started.get(r.session_key, "~"):
            started[r.session_key] = r.ts
    rows = []
    for r in recs:
        key, kind = r.failure or (None, None)
        rows.append(
            {
                **asdict(r),
                "session_key": r.session_key,
                "call_key": r.call_key,
                "started_at": started.get(r.session_key),
                "failure": key,
                "kind": kind,
            }
        )
    _run(db, _CALLS, rows)
    _run(db, _CLEAR, rows)
    _run(db, _COMMANDS, [r for r in rows if r["command"]])
    _run(db, _ERRORS, [r for r in rows if r["failure"]])

    sessions = [{"session_key": key} for key in sorted({r.session_key for r in recs})]
    held: dict[str, list[tuple[int, str]]] = {}
    for batch in _batches(sessions):
        for row in db.execute(_SESSION_CALLS, {"rows": batch}):
            held.setdefault(row["session"], []).append((row["seq"], row["call"]))
    _run(db, _UNLINK, sessions)
    links = []
    for calls in held.values():
        links += [{"prev": a[1], "next": b[1]} for a, b in pairwise(sorted(calls))]
    _run(db, _NEXT, links)
    return len(rows)
