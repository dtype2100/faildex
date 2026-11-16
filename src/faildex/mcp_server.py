"""faildex as MCP tools, so an agent can ask the graph before it acts.

Relate's own MCP server exposes raw Cypher. These tools answer the two
questions an agent has in the moment, using the same queries as the hook and
`faildex rules`:

    preflight(command)   what has gone wrong with this command before, and
                         how earlier sessions got past it
    evidence(failure)    where a failure was seen: sessions, agents, pointers
    recurring(top)       the failures that span the most sessions

The store is opened read-only for each call; the tools never write.
"""

from __future__ import annotations

from pathlib import Path

from faildex.insight import Failure, failures, proposals, warnings_for
from faildex.normalize import command_template
from faildex.store import open_store


def _summary(item: Failure) -> dict:
    return {
        "failure": item.sig,
        "command": item.command,
        "sessions": len(item.sessions),
        "calls": item.calls,
        "agents": sorted(item.agents),
        "recoveries": item.recovered,
        "usual_fix": item.fix,
        "share_of_runs": round(item.calls / item.runs, 3) if item.runs else None,
        "rule": item.rule(),
        "evidence": item.evidence,
    }


def preflight(store: Path, command: str, min_sessions: int = 2) -> dict:
    template = command_template(command)
    if not template:
        return {"command": None, "known_failures": []}
    db = open_store(store)
    try:
        found = warnings_for(db, template, min_sessions)
    finally:
        db.close()
    return {"command": template, "known_failures": [_summary(item) for item in found[:5]]}


def evidence(store: Path, failure: str) -> dict:
    db = open_store(store)
    try:
        item = failures(db).get(failure.strip().lower()) or failures(db).get(failure)
    finally:
        db.close()
    if item is None:
        return {"failure": failure, "found": False}
    return {**_summary(item), "found": True, "fixes": dict(item.fixes.most_common())}


def recurring(store: Path, top: int = 10, min_sessions: int = 2) -> list[dict]:
    db = open_store(store)
    try:
        return [_summary(item) for item in proposals(db, min_sessions)[:top]]
    finally:
        db.close()


def serve(store: Path) -> None:
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        "faildex",
        instructions="Failures coding agents repeated in earlier sessions, and how they were "
        "fixed. Call preflight before running a shell command that may fail.",
    )

    @server.tool(name="preflight", description="Known recurring failures of a shell command.")
    def _preflight(command: str) -> dict:
        return preflight(store, command)

    @server.tool(name="evidence", description="Sessions and log pointers for one failure key.")
    def _evidence(failure: str) -> dict:
        return evidence(store, failure)

    @server.tool(name="recurring", description="Failures that span the most sessions.")
    def _recurring(top: int = 10) -> list[dict]:
        return recurring(store, top)

    server.run("stdio")
