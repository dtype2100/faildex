"""Adapter for Codex CLI session files on the user's machine.

Codex writes one jsonl file per session (`~/.codex/sessions/**/*.jsonl`). The
model's own tool call is a JavaScript snippet, which is awkward to parse, but
Codex also logs each shell command it actually ran:

    {"type": "event_msg", "timestamp": ...,
     "payload": {"type": "item_completed",
                 "item": {"type": "CommandExecution", "command": ["/bin/zsh", "-lc", "<script>"],
                          "exit_code": 1, "status": "failed", "aggregated_output": "..."}}}

Those records are the calls. The session id comes from the `session_meta`
record, or from the file name when there is none. As everywhere else, only the
command template, the failure signature and a pointer leave this module.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from faildex.normalize import command_template, error_signature, is_compound
from faildex.schema import CallRecord

AGENT = "codex"
TOOL = "exec"


def _script(command: object) -> str | None:
    """The shell script of a logged command: the last element of [shell, flag, script]."""
    if isinstance(command, str):
        return command
    if isinstance(command, list) and command and isinstance(command[-1], str):
        return command[-1]
    return None


def read_session(path: str | Path) -> list[CallRecord]:
    """One record per executed command, in file order."""
    session_id = None
    found: list[tuple[int, str | None, dict]] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line, text in enumerate(handle, start=1):
            try:
                record = json.loads(text)
            except ValueError:
                continue
            payload = record.get("payload") if isinstance(record, dict) else None
            if not isinstance(payload, dict):
                continue
            if record.get("type") == "session_meta":
                named = payload.get("session_id") or payload.get("id")
                session_id = session_id or (named if isinstance(named, str) else None)
            item = payload.get("item") if payload.get("type") == "item_completed" else None
            if isinstance(item, dict) and item.get("type") == "CommandExecution":
                ts = record.get("timestamp")
                found.append((line, ts if isinstance(ts, str) else None, item))

    session_id = session_id or Path(path).stem
    records = []
    for seq, (line, ts, item) in enumerate(found):
        script = _script(item.get("command"))
        code = item.get("exit_code")
        code = code if isinstance(code, int) and not isinstance(code, bool) else None
        ok = code == 0 if code is not None else item.get("status") != "failed"
        output = item.get("aggregated_output")
        records.append(
            CallRecord(
                agent=AGENT,
                session_id=session_id,
                seq=seq,
                tool=TOOL,
                ok=ok,
                ts=ts,
                command=command_template(script) if script else None,
                error_sig=None if ok or not isinstance(output, str) else error_signature(output),
                source_path=str(path),
                source_line=line,
                exit_code=None if ok else code,
                compound=is_compound(script) if script else False,
            )
        )
    return records


def read_dir(root: str | Path) -> Iterator[CallRecord]:
    """Yield the records of every `*.jsonl` file under root, in path order."""
    for path in sorted(Path(root).rglob("*.jsonl")):
        yield from read_session(path)
