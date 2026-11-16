"""Adapter for Cursor agent chats on the user's machine.

Cursor keeps one SQLite file per chat (`~/.cursor/chats/<workspace>/<chat>/store.db`)
with two tables: `meta(key, value)` and `blobs(id, data)`. A blob that parses
as JSON is one message:

    {"role": "assistant", "content": [{"type": "tool-call", "toolCallId": "c1",
                                        "toolName": "Shell", "args": {"command": "..."}}]}
    {"role": "tool", "content": [{"type": "tool-result", "toolCallId": "c1",
                                   "toolName": "Shell", "result": "Exit code: 1\\n..."}]}

Other blobs are binary bookkeeping and are skipped. Messages carry no time, so
calls keep the order the blobs were written in (SQLite rowid) and are all
dated with the chat's creation time from `meta`. The file is opened read-only.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from faildex.normalize import command_template, error_signature, is_compound
from faildex.schema import CallRecord

AGENT = "cursor"
SHELL_TOOL = "Shell"

_EXIT_CODE = re.compile(r"Exit code: (-?\d+)")


def _meta(con) -> dict:
    """The chat's metadata: a JSON object, stored hex-encoded in recent versions."""
    for (value,) in con.execute("SELECT value FROM meta"):
        for decode in (lambda v: bytes.fromhex(v).decode("utf-8"), lambda v: v):
            try:
                found = json.loads(decode(value))
            except (ValueError, TypeError):
                continue
            if isinstance(found, dict):
                return found
    return {}


def _created(meta: dict) -> str | None:
    created = meta.get("createdAt")
    if isinstance(created, str):
        return created
    if isinstance(created, (int, float)) and not isinstance(created, bool):
        seconds = created / 1000 if created > 1e11 else created
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    return None


def _parts(con) -> Iterator[tuple[int, dict]]:
    """(rowid, content part) for every part of every JSON message, in write order."""
    for rowid, data in con.execute("SELECT rowid, data FROM blobs ORDER BY rowid"):
        try:
            text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
            message = json.loads(text)
        except (ValueError, AttributeError, TypeError):
            continue
        content = message.get("content") if isinstance(message, dict) else None
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict):
                yield rowid, part


def read_store(path: str | Path) -> list[CallRecord]:
    """One record per tool call that has a result, in the order the calls were made."""
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        meta = _meta(con)
        calls: dict[str, tuple[int, str, object]] = {}
        results: dict[str, object] = {}
        for rowid, part in _parts(con):
            call_id, tool = part.get("toolCallId"), part.get("toolName")
            if not isinstance(call_id, str):
                continue
            if part.get("type") == "tool-call" and isinstance(tool, str) and tool:
                calls.setdefault(call_id, (rowid, tool, part.get("args")))
            elif part.get("type") == "tool-result":
                results.setdefault(call_id, part.get("result"))
    except sqlite3.DatabaseError:
        return []
    finally:
        con.close()

    session = meta.get("agentId")
    session_id = session if isinstance(session, str) and session else Path(path).parent.name
    ts = _created(meta)
    records = []
    for seq, (call_id, (rowid, tool, args)) in enumerate(calls.items()):
        if call_id not in results:
            continue  # never answered; the gap in seq keeps later calls in place
        result = results[call_id]
        output = result if isinstance(result, str) else ""
        found = _EXIT_CODE.match(output)
        code = int(found.group(1)) if found else None
        failed = bool(code) or output.startswith("Error:")
        raw = args.get("command") if tool == SHELL_TOOL and isinstance(args, dict) else None
        raw = raw if isinstance(raw, str) else None
        records.append(
            CallRecord(
                agent=AGENT,
                session_id=session_id,
                seq=seq,
                tool=tool,
                ok=not failed,
                ts=ts,
                command=command_template(raw) if raw else None,
                error_sig=error_signature(output) if failed else None,
                source_path=str(path),
                source_line=rowid,
                exit_code=code if failed else None,
                compound=is_compound(raw) if raw else False,
            )
        )
    return records


def read_dir(root: str | Path) -> Iterator[CallRecord]:
    """Yield the records of every `store.db` under root, in path order."""
    for path in sorted(Path(root).rglob("store.db")):
        yield from read_store(path)
