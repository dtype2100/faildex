"""Read Claude Code session transcripts (`.jsonl`) into `CallRecord`s.

A transcript holds one JSON object per line. An `assistant` record carries
`tool_use` blocks (the calls); a later `user` record carries the matching
`tool_result` block. Everything else is ignored, and a line that is not valid
JSON or not shaped as expected is skipped rather than raised.

Only normalized values leave this module: the command template and the error
signature. Raw command text and raw output are never put into a record.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from faildex.normalize import command_template, error_signature, is_compound
from faildex.schema import CallRecord

AGENT = "claude-code"
SHELL_TOOL = "Bash"
_EXIT_CODE = re.compile(r"(?:<error>)?\s*Exit code:? (-?\d+)")


@dataclass
class _Call:
    seq: int
    tool_use_id: object
    tool: str
    command: str | None
    compound: bool
    ts: str | None
    line: int


def _records(path: Path) -> Iterator[tuple[int, dict]]:
    """Yield (1-based line number, record) for every line that is a JSON object."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(record, dict):
                yield number, record


def _blocks(record: dict, record_type: str, block_type: str) -> Iterator[dict]:
    """Yield the content blocks of one kind from a record of one type."""
    if record.get("type") != record_type:
        return
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == block_type:
            yield block


def _text(content: object) -> str:
    """Flatten a tool_result content (a string or a list of text blocks) to text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _session_id(record: dict) -> str | None:
    """Session id of a record; a subagent transcript gets its own id under the parent."""
    session_id = record.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return None
    agent_id = record.get("agentId")
    if record.get("isSidechain") is True and isinstance(agent_id, str) and agent_id:
        return f"{session_id}/agent-{agent_id}"
    return session_id


def _command(tool: str, tool_input: object) -> tuple[str | None, bool]:
    """(template, compound) of a shell call; (None, False) for other tools."""
    if tool != SHELL_TOOL or not isinstance(tool_input, dict):
        return None, False
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None, False
    return command_template(command), is_compound(command)


def count_tool_uses(path: str | Path) -> int:
    """Number of tool_use blocks in the file, with or without a result."""
    return sum(
        1 for _, record in _records(Path(path)) for _ in _blocks(record, "assistant", "tool_use")
    )


def read_session(path: str | Path) -> list[CallRecord]:
    """Return one record per tool call that has a result, in file order.

    `seq` numbers every tool_use block of the file from 0, so a call that never
    got a result leaves a gap in `seq` instead of shifting the calls after it.
    """
    session_id = None
    calls: list[_Call] = []
    # tool_use_id -> (failed, error signature, exit code, time the result arrived);
    # the first result of an id wins.
    results: dict[object, tuple[bool, str | None, int | None, str | None]] = {}
    tools: dict[object, str] = {}

    for number, record in _records(Path(path)):
        session_id = session_id or _session_id(record)
        for block in _blocks(record, "assistant", "tool_use"):
            name = block.get("name")
            tool = name if isinstance(name, str) and name else "unknown"
            ts = record.get("timestamp")
            command, compound = _command(tool, block.get("input"))
            call = _Call(
                seq=len(calls),
                tool_use_id=block.get("id"),
                tool=tool,
                command=command,
                compound=compound,
                ts=ts if isinstance(ts, str) else None,
                line=number,
            )
            calls.append(call)
            if isinstance(call.tool_use_id, str):
                tools.setdefault(call.tool_use_id, tool)
        for block in _blocks(record, "user", "tool_result"):
            tool_use_id = block.get("tool_use_id")
            if not isinstance(tool_use_id, str) or tool_use_id in results:
                continue
            failed = bool(block.get("is_error"))
            sig = code = None
            if failed:
                text = _text(block.get("content"))
                sig = error_signature(text)
                found = _EXIT_CODE.match(text) if tools.get(tool_use_id) == SHELL_TOOL else None
                code = int(found.group(1)) if found else None
            arrived = record.get("timestamp")
            results[tool_use_id] = (
                failed,
                sig,
                code,
                arrived if isinstance(arrived, str) else None,
            )

    session_id = session_id or Path(path).stem
    out = []
    for call in calls:
        if not isinstance(call.tool_use_id, str) or call.tool_use_id not in results:
            continue
        failed, sig, code, arrived = results[call.tool_use_id]
        out.append(
            CallRecord(
                agent=AGENT,
                session_id=session_id,
                seq=call.seq,
                tool=call.tool,
                ok=not failed,
                # When the outcome became known: a call may return long after it was made.
                ts=arrived or call.ts,
                command=call.command,
                error_sig=sig,
                source_path=str(path),
                source_line=call.line,
                exit_code=code,
                compound=call.compound,
            )
        )
    return out


def read_dir(root: str | Path) -> Iterator[CallRecord]:
    """Yield the records of every `*.jsonl` file under root, in path order."""
    for path in sorted(Path(root).rglob("*.jsonl")):
        try:
            yield from read_session(path)
        except OSError:
            continue
