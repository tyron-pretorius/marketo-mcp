"""
Smoke tests for the blended Marketo MCP server (mcp_server_blended.py).

Two modes:

  python test_blended_server.py stub
      Self-contained, no real credentials needed. Starts a local stub
      "native" MCP server that echoes the headers it receives, starts the
      blended server pointed at the stub, then verifies:
        - tools/list merges custom_* tools with the stub's tools
        - the X-Marketo-* headers are forwarded to the upstream server
        - requests without headers fail with a clear error

  python test_blended_server.py live
      Requires real Marketo credentials (prompted, or set MARKETO_CLIENT_ID /
      MARKETO_CLIENT_SECRET / MARKETO_MUNCHKIN_ID env vars) and the blended
      server already running on http://localhost:8000/mcp. Lists tools and
      calls one custom tool (custom_browse_landing_pages). Calling proxied
      native tools end-to-end additionally requires your Munchkin ID to be
      allowlisted in Adobe's beta.
"""

import asyncio
import multiprocessing
import os
import sys
import time

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

BLENDED_URL = "http://localhost:8000/mcp"
STUB_URL = "http://localhost:8001/mcp"


# ============================================================================
# Stub mode
# ============================================================================

def _run_stub_upstream():
    """A fake 'native Marketo MCP' that echoes the headers it receives."""
    from fastmcp import FastMCP
    from fastmcp.server.dependencies import get_http_headers

    stub = FastMCP("StubNativeMarketoMCP")

    @stub.tool()
    def browse_forms() -> dict:
        """Stub native tool that returns the X-Marketo headers it received."""
        headers = get_http_headers()
        return {k: v for k, v in headers.items() if k.startswith("x-marketo-")}

    stub.run(transport="streamable-http", host="127.0.0.1", port=8001)


def _run_blended_against_stub():
    os.environ["NATIVE_MARKETO_MCP_URL"] = STUB_URL
    import mcp_server_blended
    mcp_server_blended.mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)


async def _stub_checks():
    headers = {
        "X-Marketo-Client-Id": "stub-client-id",
        "X-Marketo-Client-Secret": "stub-secret",
        "X-Marketo-Munchkin-Id": "123-STU-456",
    }

    async with Client(StreamableHttpTransport(BLENDED_URL, headers=headers)) as client:
        tools = {t.name for t in await client.list_tools()}

        custom = {t for t in tools if t.startswith("custom_")}
        native = tools - custom
        assert "browse_forms" in native, f"stub native tool missing from merged list: {sorted(tools)}"
        assert "custom_sync_leads" in custom and "custom_update_landing_page" in custom, \
            f"custom tools missing from merged list: {sorted(custom)}"
        print(f"PASS tools/list merges native ({len(native)}) + custom ({len(custom)}) tools")

        result = await client.call_tool("browse_forms", {})
        echoed = result.data if hasattr(result, "data") else result
        assert echoed.get("x-marketo-client-id") == "stub-client-id", f"headers not forwarded: {echoed}"
        assert echoed.get("x-marketo-munchkin-id") == "123-STU-456", f"headers not forwarded: {echoed}"
        print("PASS X-Marketo-* headers forwarded to the upstream server")

    async with Client(StreamableHttpTransport(BLENDED_URL)) as client:
        try:
            await client.list_tools()
            print("WARN tools/list without headers did not error (custom-only listing?)")
        except Exception as exc:
            assert "Missing Marketo auth headers" in str(exc), f"unexpected error: {exc}"
            print("PASS missing headers produce a clear error")


def run_stub_mode():
    procs = [
        multiprocessing.Process(target=_run_stub_upstream, daemon=True),
        multiprocessing.Process(target=_run_blended_against_stub, daemon=True),
    ]
    for p in procs:
        p.start()
    time.sleep(3)  # give both servers time to bind

    try:
        asyncio.run(_stub_checks())
        print("\nAll stub-mode checks passed.")
    finally:
        for p in procs:
            p.terminate()


# ============================================================================
# Live mode
# ============================================================================

def _get_live_headers() -> dict:
    client_id = os.environ.get("MARKETO_CLIENT_ID") or input("Marketo Client ID: ").strip()
    client_secret = os.environ.get("MARKETO_CLIENT_SECRET") or input("Marketo Client Secret: ").strip()
    munchkin_id = os.environ.get("MARKETO_MUNCHKIN_ID") or input("Marketo Munchkin ID (e.g. 123-ABC-456): ").strip()
    return {
        "X-Marketo-Client-Id": client_id,
        "X-Marketo-Client-Secret": client_secret,
        "X-Marketo-Munchkin-Id": munchkin_id,
    }


async def _live_checks(headers: dict):
    async with Client(StreamableHttpTransport(BLENDED_URL, headers=headers)) as client:
        tools = sorted(t.name for t in await client.list_tools())
        custom = [t for t in tools if t.startswith("custom_")]
        native = [t for t in tools if not t.startswith("custom_")]
        print(f"Tools listed: {len(native)} native, {len(custom)} custom")
        print("Custom tools:", ", ".join(custom))
        if not native:
            print("NOTE: no native tools listed — is your Munchkin ID allowlisted for Adobe's beta?")

        print("\nCalling custom_browse_landing_pages (direct REST path)...")
        result = await client.call_tool("custom_browse_landing_pages", {"max_return": 3})
        print(result.data if hasattr(result, "data") else result)

        if "browse_programs" in native:
            print("\nCalling browse_programs (proxied native path)...")
            result = await client.call_tool("browse_programs", {})
            print(result.data if hasattr(result, "data") else result)


def run_live_mode():
    headers = _get_live_headers()
    asyncio.run(_live_checks(headers))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "stub"
    if mode == "stub":
        run_stub_mode()
    elif mode == "live":
        run_live_mode()
    else:
        print(__doc__)
        sys.exit(1)
