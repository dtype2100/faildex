"""Graph schema and the single write path into the store.

Nodes
    Session  key: id = "<agent>:<session_id>"
    Call     key: id = "<agent>:<session_id>:<seq>"
    Command  key: template   (normalized command, shared across sessions)
    ErrorSig key: sig        (normalized failure text, shared across sessions)

Relationships
    (Session)-[:HAS_CALL]->(Call)
    (Call)-[:NEXT]->(Call)          consecutive calls of one session, by seq
    (Call)-[:RAN]->(Command)
    (Call)-[:FAILED_WITH]->(ErrorSig)

Every write is a MERGE on the key, so ingesting the same records twice
leaves the graph unchanged. Raw text never enters the graph: a Call keeps
only a pointer (source_path, source_line) to where it came from.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from itertools import groupby, pairwise

BATCH = 2000


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

    @property
    def session_key(self) -> str:
        return f"{self.agent}:{self.session_id}"

    @property
    def call_key(self) -> str:
        return f"{self.session_key}:{self.seq}"


_CALLS = """
UNWIND $rows AS row
MERGE (s:Session {id: row.session_key})
  ON CREATE SET s.agent = row.agent, s.session_id = row.session_id
MERGE (c:Call {id: row.call_key})
  SET c.seq = row.seq, c.tool = row.tool, c.ok = row.ok, c.ts = row.ts,
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
MERGE (e:ErrorSig {sig: row.error_sig})
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


def ingest(db, records: Iterable[CallRecord]) -> int:
    """Write records into the graph. Returns the number of records written."""
    recs = sorted(records, key=lambda r: (r.session_key, r.seq))
    rows = [{**asdict(r), "session_key": r.session_key, "call_key": r.call_key} for r in recs]
    _run(db, _CALLS, rows)
    _run(db, _COMMANDS, [r for r in rows if r["command"]])
    _run(db, _ERRORS, [r for r in rows if r["error_sig"]])

    links = []
    for _, group in groupby(recs, key=lambda r: r.session_key):
        calls = list(group)
        links += [{"prev": a.call_key, "next": b.call_key} for a, b in pairwise(calls)]
    _run(db, _NEXT, links)
    return len(rows)
