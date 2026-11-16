"""Adapter for the public Codex trajectory dataset format.

Input is a jsonl file with one row per turn segment (for example
`trajectories.train.jsonl` of `israellaguan/codex-tool-use-trajectories`).
A row carries `session_id`, `timestamp`, `segment` and `messages` in OpenAI chat
format: assistant messages hold `tool_calls`, and each call is answered by one
`{"role": "tool", "tool_call_id": ...}` message whose content starts with
`Exit code: N` for shell calls.

Rows of one session may be anywhere in the file, so a session is collected
first and then numbered: rows by `timestamp`, then `segment`, then file line;
calls inside a row in message order. `seq` therefore follows real time.

Only derived values are kept while reading (tool name, ok flag, command
template, error signature, line number); the messages themselves are dropped
row by row and no raw command or output text reaches a record.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from os import PathLike
from typing import NamedTuple

from faildex.normalize import command_template, error_signature, is_compound
from faildex.schema import CallRecord

AGENT = "codex"
SHELL_TOOL = "shell_command"

_EXIT_CODE = re.compile(r"Exit code: (-?\d+)")


class _Call(NamedTuple):
    tool: str
    ok: bool
    command: str | None
    error_sig: str | None
    exit_code: int | None = None
    compound: bool = False
    call_id: str | None = None


class _Row(NamedTuple):
    order: tuple
    ts: str | None
    line: int
    calls: list[_Call]
    source_path: str = ""


def _text(content) -> str:
    """Tool message content as text; chat content may also be a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text") for p in content if isinstance(p, dict)]
        return "\n".join(p for p in parts if isinstance(p, str))
    return ""


def _exit_code(output: str) -> int | None:
    match = _EXIT_CODE.match(output)
    return int(match.group(1)) if match else None


def _shell_command(arguments) -> str | None:
    """The command string of a shell call, or None when the arguments are unusable."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    command = arguments.get("command") if isinstance(arguments, dict) else None
    return command if isinstance(command, str) else None


def _calls(messages) -> list[_Call]:
    if not isinstance(messages, list):
        return []
    messages = [m for m in messages if isinstance(m, dict)]
    outputs: dict[str, str] = {}
    for message in messages:
        call_id = message.get("tool_call_id")
        if message.get("role") == "tool" and isinstance(call_id, str):
            outputs.setdefault(call_id, _text(message.get("content")))

    calls = []
    for message in messages:
        tool_calls = message.get("tool_calls")
        for tool_call in tool_calls if isinstance(tool_calls, list) else []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            tool = function.get("name") if isinstance(function, dict) else None
            output = outputs.get(tool_call.get("id")) if tool_call.get("id") else None
            if not isinstance(tool, str) or not tool or output is None:
                continue
            code = _exit_code(output)
            ok = not code
            command = error_sig = None
            compound = False
            if tool == SHELL_TOOL:
                raw = _shell_command(function.get("arguments"))
                if raw is None:
                    continue
                command = command_template(raw)
                compound = is_compound(raw)
                error_sig = None if ok else error_signature(output)
            calls.append(
                _Call(tool, ok, command, error_sig, None if ok else code, compound, tool_call["id"])
            )
    return calls


def _order(timestamp, segment, line: int) -> tuple:
    """Sort key inside a session: time, then segment, then position in the file.

    Timestamps are compared as instants, so `Z` and `+00:00` spellings agree.
    Rows whose timestamp cannot be read keep their file order after the rest.
    """
    segment = segment if isinstance(segment, int) else 0
    if isinstance(timestamp, str):
        try:
            moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return (1, 0.0, segment, line)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return (0, moment.timestamp(), segment, line)
    return (2, 0.0, segment, line)


def _records(numbered: Iterable[tuple[str, int, object]]) -> Iterator[CallRecord]:
    sessions: dict[str, list[_Row]] = {}
    for source_path, line, row in numbered:
        if not isinstance(row, dict):
            continue
        session_id = row.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            continue
        calls = _calls(row.get("messages"))
        if not calls:
            continue
        timestamp = row.get("timestamp")
        ts = timestamp if isinstance(timestamp, str) else None
        order = _order(timestamp, row.get("segment"), line)
        sessions.setdefault(session_id, []).append(_Row(order, ts, line, calls, source_path))

    for session_id, rows in sessions.items():
        seq = 0
        seen: set[str] = set()
        for row in sorted(rows, key=lambda r: r.order):
            for call in row.calls:
                # The same event may be exported into two files; count it once.
                if call.call_id in seen:
                    continue
                seen.add(call.call_id)
                yield CallRecord(
                    agent=AGENT,
                    session_id=session_id,
                    seq=seq,
                    tool=call.tool,
                    ok=call.ok,
                    ts=row.ts,
                    command=call.command,
                    error_sig=call.error_sig,
                    source_path=row.source_path,
                    source_line=row.line,
                    exit_code=call.exit_code,
                    compound=call.compound,
                )
                seq += 1


def read_rows(rows: Iterable[object], source_path: str | PathLike[str]) -> Iterator[CallRecord]:
    """Yield records for already-parsed rows; row N of `rows` is reported as line N."""
    path = str(source_path)
    return _records((path, line, row) for line, row in enumerate(rows, start=1))


def _parsed_lines(path: str | PathLike[str]) -> Iterator[tuple[int, object]]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line, text in enumerate(handle, start=1):
            if not text.strip():
                continue
            try:
                yield line, json.loads(text)
            except ValueError:
                continue


def read_file(path: str | PathLike[str]) -> Iterator[CallRecord]:
    """Stream a trajectories jsonl file as records, skipping lines that do not parse."""
    return read_files([path])


def read_files(paths: Iterable[str | PathLike[str]]) -> Iterator[CallRecord]:
    """Read several files as one log.

    A session may be spread over files, so its calls are numbered once across
    all of them; numbering each file alone would give two calls the same key.
    """
    return _records((str(path), line, row) for path in paths for line, row in _parsed_lines(path))
