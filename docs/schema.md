# Graph schema

| Node | Key | Other properties |
|---|---|---|
| `Session` | `id` = `<agent>:<session_id>` | `agent`, `session_id` |
| `Call` | `id` = `<agent>:<session_id>:<seq>` | `seq`, `tool`, `ok`, `ts`, `source_path`, `source_line` |
| `Command` | `template` | — |
| `ErrorSig` | `sig` | — |

| Relationship | Meaning |
|---|---|
| `(Session)-[:HAS_CALL]->(Call)` | the call belongs to the session |
| `(Call)-[:NEXT]->(Call)` | the next call of the same session, in the order the calls happened |
| `(Call)-[:RAN]->(Command)` | the normalized command the call ran |
| `(Call)-[:FAILED_WITH]->(ErrorSig)` | the normalized failure the call ended with |

`Command` and `ErrorSig` are shared across sessions and agents. That sharing is what
turns separate session logs into one graph: a failure seen by one agent is one hop
away from every other session that hit it, and two hops from how it was fixed.

Writes are `MERGE`s on the key, so re-ingesting the same logs changes nothing.
The graph stores pointers (`source_path`, `source_line`), never the raw text.

The single write path is `faildex.schema.ingest(db, records)`.
