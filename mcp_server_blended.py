"""
Blended Marketo MCP Server.

Proxies Adobe's native Marketo MCP server (https://marketo-mcp.adobe.io/mcp)
for every tool it exposes, and adds custom_* tools for the capabilities the
native server lacks (lead create/update/merge, send sample email, landing
pages, bulk lead import, and destructive operations).

Authentication matches the native server: clients must send these headers on
every request, which are forwarded upstream for proxied tools and used to mint
Marketo REST tokens for custom tools:

    X-Marketo-Client-Id
    X-Marketo-Client-Secret
    X-Marketo-Munchkin-Id
    X-Marketo-Endpoint   (optional REST base URL override, without /rest)

Tool naming: unprefixed tools are mirrored live from the native server;
custom_* tools call the Marketo REST API directly from this server. On any
name conflict, local custom tools win.

Run:  python mcp_server_blended.py   ->  http://0.0.0.0:8000/mcp
"""

import os

from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.proxy import FastMCPProxy, ProxyClient

from credentials import extract_marketo_headers
from custom_tools import register_custom_tools

# Overridable so the proxy path can be tested against a local stub upstream.
NATIVE_MCP_URL = os.environ.get("NATIVE_MARKETO_MCP_URL", "https://marketo-mcp.adobe.io/mcp")


def upstream_client_factory() -> ProxyClient:
    # Called per request by the proxy managers, so the HTTP request context is
    # active and the caller's X-Marketo-* headers can be forwarded upstream.
    forward_headers = extract_marketo_headers()
    return ProxyClient(StreamableHttpTransport(NATIVE_MCP_URL, headers=forward_headers))


mcp = FastMCPProxy(client_factory=upstream_client_factory, name="MarketoBlendedMCP")

register_custom_tools(mcp)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
