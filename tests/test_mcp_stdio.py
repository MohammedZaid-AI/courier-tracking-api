"""Start the real MCP server as a subprocess over stdio and talk to it with the official MCP
client library, like Claude Code or Claude Desktop would. Offline mode only: the server answers
from fixtures through an in-process transport, and every answer is checked to say so."""

import os
import sys

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _schema(tool):
    return tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema


def _structured(result):
    return getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)


def _is_error(result):
    return getattr(result, "is_error", None) or getattr(result, "isError", False)


async def _session(errlog):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "courier_tracking.mcp_server"],
        # Offline via the env var, the same switch documented for MCP clients.
        env={**os.environ, "COURIER_TRACKING_OFFLINE": "1"},
    )
    return stdio_client(params, errlog=errlog)


async def test_stdio_server_lists_one_read_only_tool_and_survives_bad_input(tmp_path):
    errlog_path = tmp_path / "server-stderr.txt"
    with open(errlog_path, "w", encoding="utf-8") as errlog:
        with anyio.fail_after(60):
            async with await _session(errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    tools = (await session.list_tools()).tools
                    assert [t.name for t in tools] == ["get_delivery_status"]  # the only tool
                    tool = tools[0]
                    assert tool.annotations.read_only_hint is True
                    assert tool.annotations.destructive_hint is False
                    assert "never refunds or cancels anything" in tool.description
                    schema = _schema(tool)
                    assert set(schema["required"]) == {"courier", "tracking_id"}
                    assert schema["properties"]["courier"].get("const") == "trackon"

                    # Bad input first: clear errors, server keeps running.
                    bad_courier = await session.call_tool(
                        "get_delivery_status", {"courier": "bluedart", "tracking_id": "12345678901"}
                    )
                    assert _is_error(bad_courier)
                    assert "trackon" in bad_courier.content[0].text

                    bad_id = _structured(
                        await session.call_tool("get_delivery_status", {"courier": "trackon", "tracking_id": "12AB"})
                    )
                    assert bad_id["ok"] is False and bad_id["error"] == "INVALID_TRACKING_ID"
                    assert bad_id["refund_hint"]["action"] == "check_manually"

                    # Same session, still answering: synthetic prepaid return, sent as a JSON number.
                    out = _structured(
                        await session.call_tool("get_delivery_status", {"courier": "trackon", "tracking_id": 999000000005})
                    )
                    assert out["ok"] is True
                    assert out["data_source"].startswith("offline fixtures")
                    assert out["status"] == "returned"
                    assert out["refund_hint"]["action"] == "consider_refund"
                    assert out["refund_hint"]["is_suggestion"] is True

    stderr = errlog_path.read_text(encoding="utf-8")
    assert "starting in OFFLINE" in stderr
    assert "HTTP Request" not in stderr  # no request-looking log lines in offline mode


@pytest.mark.parametrize(
    "argv, env, expected",
    [([], {}, False), (["--offline"], {}, True), ([], {"COURIER_TRACKING_OFFLINE": "1"}, True), ([], {"COURIER_TRACKING_OFFLINE": "true"}, True)],
)
def test_offline_switch(monkeypatch, argv, env, expected):
    from courier_tracking import mcp_server

    monkeypatch.delenv("COURIER_TRACKING_OFFLINE", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert mcp_server.offline_requested(argv) is expected
