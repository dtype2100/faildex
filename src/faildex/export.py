"""Export the store for the browser demo.

Relate's WebAssembly build is in-memory and cannot read the parquet parts of a
directory store, so the demo page rebuilds the same graph from this JSON with
the same Cypher the Python side uses. The file holds exactly what the store
holds: templates, failure keys and pointers, no raw text.
"""

from __future__ import annotations

import json
from pathlib import Path

_SOURCES = """
MATCH (d:Source)
RETURN d.name AS name, d.repo AS repo, d.revision AS revision, d.license AS license, d.url AS url
ORDER BY name
"""

_SESSIONS = """
MATCH (s:Session)
OPTIONAL MATCH (s)-[:FROM]->(d:Source)
RETURN s.id AS id, s.agent AS agent, s.started_at AS started_at, d.name AS source
ORDER BY id
"""

_CALLS = """
MATCH (s:Session)-[:HAS_CALL]->(c:Call)
OPTIONAL MATCH (c)-[:RAN]->(k:Command)
OPTIONAL MATCH (c)-[:FAILED_WITH]->(e:ErrorSig)
RETURN s.id AS session, c.seq AS seq, c.tool AS tool, c.ok AS ok, c.ts AS ts,
       c.compound AS compound, c.source_path AS path, c.source_line AS line,
       k.template AS command, e.sig AS failure, e.kind AS kind
ORDER BY session, seq
"""

CALL_FIELDS = ("seq", "tool", "ok", "ts", "compound", "path", "line", "command", "failure", "kind")


def export(db) -> dict:
    """The whole graph as plain data. Strings repeat a lot, so they are interned."""
    strings: list[str | None] = [None]
    index: dict[str, int] = {}

    def intern(value: str | None) -> int:
        if value is None:
            return 0
        if value not in index:
            index[value] = len(strings)
            strings.append(value)
        return index[value]

    sessions = [dict(row) for row in db.execute(_SESSIONS)]
    position = {s["id"]: i for i, s in enumerate(sessions)}
    calls = []
    for row in db.execute(_CALLS):
        calls.append(
            [
                position[row["session"]],
                row["seq"],
                intern(row["tool"]),
                1 if row["ok"] else 0,
                row["ts"],
                1 if row["compound"] else 0,
                intern(row["path"]),
                row["line"],
                intern(row["command"]),
                intern(row["failure"]),
                intern(row["kind"]),
            ]
        )
    return {
        "sources": [dict(row) for row in db.execute(_SOURCES)],
        "sessions": sessions,
        "strings": strings,
        "call_fields": ["session", *CALL_FIELDS],
        "calls": calls,
    }


def write(db, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(export(db), separators=(",", ":"))
    out.write_text(text)
    return len(text)
