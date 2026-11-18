"""Adapter for Google Antigravity agent sessions (the app and its CLI).

Antigravity keeps one folder per conversation under `~/.gemini/antigravity/brain`
(the app) or `~/.gemini/antigravity-cli/brain` (the CLI), with a step log at
`<id>/.system_generated/logs/transcript_full.jsonl`. Each line is one step:

    {"type": "PLANNER_RESPONSE", "created_at": "...", "status": "DONE",
     "tool_calls": [{"name": "run_command", "args": {"CommandLine": "git status"}}]}
    {"type": "GENERIC", "created_at": "...", "status": "DONE",
     "content": "Created At: ...\\nCompleted At: ...\\nThe command exited with code 128.\\nOutput:\\nfatal: ..."}

A planner step announces tool calls; the steps after it answer them in order.
A call fails when its answer reports a non-zero exit code or the step itself
has status ERROR. Only the command template, the failure signature and a
pointer leave this module.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from faildex.normalize import command_template, error_signature, is_compound
from faildex.schema import CallRecord

AGENT = "antigravity"
SHELL_TOOL = "run_command"
LOG = Path(".system_generated") / "logs"

_EXIT = re.compile(r"exited with (?:exit )?code (-?\d+)|exit code[:\s]+(-?\d+)", re.IGNORECASE)
_OUTPUT = re.compile(r"^\s*(?:command output|output|stdout|stderr):\s*$", re.IGNORECASE)
# Steps that announce calls, and steps that never answer one.
_PLANNER = "PLANNER_RESPONSE"
_NOT_ANSWERS = {
    "USER_INPUT",
    "EPHEMERAL_MESSAGE",
    "SYSTEM_MESSAGE",
    "CHECKPOINT",
    "CONVERSATION_HISTORY",
    "ERROR_MESSAGE",
}


def _output(text: str) -> str:
    """The command's own output: whatever follows the "Output:" line."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _OUTPUT.match(line):
            return "\n".join(lines[i + 1 :])
    return text


def _answer(step: dict) -> tuple[bool, int | None, str]:
    """(failed, exit code, failure text) for the step that answers a call."""
    content = step.get("content") if isinstance(step.get("content"), str) else ""
    found = _EXIT.search(content)
    code = int(next(g for g in found.groups() if g is not None)) if found else None
    if step.get("status") == "ERROR":
        error = step.get("error")
        return True, code, error if isinstance(error, str) else content
    if code:
        return True, code, _output(content)
    return False, code, ""


def _log(folder: Path) -> Path | None:
    for name in ("transcript_full.jsonl", "transcript.jsonl"):
        path = folder / LOG / name
        if path.is_file():
            return path
    return None


def read_session(folder: str | Path) -> list[CallRecord]:
    """One record per answered tool call of one conversation folder."""
    folder = Path(folder)
    path = _log(folder)
    if path is None:
        return []
    pending: list[tuple[int, str, object]] = []
    records: list[CallRecord] = []
    seq = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line, text in enumerate(handle, start=1):
            try:
                step = json.loads(text)
            except ValueError:
                continue
            if not isinstance(step, dict):
                continue
            kind = step.get("type")
            if kind == _PLANNER:
                for call in step.get("tool_calls") or []:
                    if isinstance(call, dict) and isinstance(call.get("name"), str):
                        pending.append((seq, call["name"], call.get("args")))
                        seq += 1
                continue
            if kind == "USER_INPUT":
                pending.clear()  # calls the person interrupted get no answer
                continue
            if kind in _NOT_ANSWERS or not pending or step.get("status") == "RUNNING":
                continue
            number, tool, args = pending.pop(0)
            failed, code, failure = _answer(step)
            raw = args.get("CommandLine") if tool == SHELL_TOOL and isinstance(args, dict) else None
            raw = raw if isinstance(raw, str) else None
            ts = step.get("created_at")
            records.append(
                CallRecord(
                    agent=AGENT,
                    session_id=folder.name,
                    seq=number,
                    tool=tool,
                    ok=not failed,
                    ts=ts if isinstance(ts, str) else None,
                    command=command_template(raw) if raw else None,
                    error_sig=error_signature(failure) if failed and failure else None,
                    source_path=str(path),
                    source_line=line,
                    exit_code=code if failed else None,
                    compound=is_compound(raw) if raw else False,
                )
            )
    return records


def read_dir(root: str | Path) -> Iterator[CallRecord]:
    """Every conversation under an Antigravity data folder (or its `brain` folder)."""
    root = Path(root)
    brain = root / "brain" if (root / "brain").is_dir() else root
    for folder in sorted(p for p in brain.iterdir() if p.is_dir()) if brain.is_dir() else []:
        yield from read_session(folder)
