import asyncio
import sys

import relate
from test_insight import REJECTED, _records

from faildex import mcp_server
from faildex.schema import ingest


def _store(tmp_path):
    store = tmp_path / "store"
    db = relate.connect(str(store))
    ingest(db, _records())
    db.commit()
    db.flush()
    db.close()
    return store


def test_preflight_evidence_and_recurring(tmp_path):
    store = _store(tmp_path)
    known = mcp_server.preflight(store, "git push origin main")
    assert known["command"] == "git push"
    assert known["known_failures"][0]["usual_fix"] == "git pull"
    assert mcp_server.preflight(store, "ls -la")["known_failures"] == []

    seen = mcp_server.evidence(store, REJECTED)
    assert seen["found"] and seen["sessions"] == 3
    assert seen["evidence"][0] == "demo/s1.jsonl:1"
    assert mcp_server.evidence(store, "never seen")["found"] is False

    assert [r["failure"] for r in mcp_server.recurring(store)] == [REJECTED, "linker not found"]


def test_server_answers_a_real_mcp_client(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    store = _store(tmp_path)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "faildex.cli", "mcp", "--store", str(store)]
    )

    async def ask():
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(tool.name for tool in (await session.list_tools()).tools)
            result = await session.call_tool("preflight", {"command": "git push"})
            return tools, result

    tools, result = asyncio.run(ask())
    assert tools == ["evidence", "preflight", "recurring"]
    assert "git pull" in str(result)
