"""
Blended Marketo MCP Server.

Proxies Adobe's native Marketo MCP server (https://marketo-mcp.adobe.io/mcp)
for every tool it exposes, and adds custom_* tools for the capabilities the
native server lacks (lead create/update/merge, send sample email, landing
pages, bulk lead import, and destructive operations).

Authentication: clients send three headers on every request, which are
forwarded upstream for proxied tools and used to mint Marketo REST tokens for
custom tools:

    x-client-id       REST API client ID (Admin > LaunchPoint)
    x-client-secret   REST API client secret
    x-munchkin-id     Munchkin ID, e.g. 123-ABC-456 (Admin > Munchkin)
    x-endpoint        (optional) REST base URL override, without /rest

The first two are offered by name in Claude Desktop's "Add custom connector"
header dropdown, so setting up a connector is mostly picking from a list.
Adobe's native server is still addressed with its own X-Marketo-* names;
credentials.py translates on the way out.

Tool naming: unprefixed tools are mirrored live from the native server;
custom_* tools call the Marketo REST API directly from this server. On any
name conflict, local custom tools win.

Requires fastmcp >= 3.

Run:  python mcp_server_blended.py   ->  http://0.0.0.0:$PORT/mcp (default 8000)
"""

import os

from fastmcp import FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers.proxy import ProxyClient, ProxyProvider

from credentials import extract_marketo_headers
from custom_tools import register_custom_tools
from marketo_rest.native_tags import EditorVersionTags

# Overridable so the proxy path can be tested against a local stub upstream.
NATIVE_MCP_URL = os.environ.get("NATIVE_MARKETO_MCP_URL", "https://marketo-mcp.adobe.io/mcp")


def upstream_client_factory() -> ProxyClient:
    # Called per request by the proxy provider, so the HTTP request context is
    # active and the caller's credential headers can be forwarded upstream.
    # Cached proxy components store this factory (not a bound client), so every
    # native tool call re-runs it and uses the current caller's credentials.
    forward_headers = extract_marketo_headers()
    return ProxyClient(StreamableHttpTransport(NATIVE_MCP_URL, headers=forward_headers))


# A plain FastMCP with a ProxyProvider (rather than FastMCPProxy) keeps the
# MCP initialize handshake local: clients can always connect, and upstream
# failures (missing headers, un-allowlisted Munchkin ID, outage) degrade
# tools/list to the local custom_* tools with a warning — important for
# clients that import the tool list at session start (e.g. OpenAI agents).
# Native tool *calls* still surface upstream errors normally.
# Adobe's native email tools are named legacy_email_* but never say which
# editor that means; EditorVersionTags prepends the same editor tag the
# custom_* tools carry, so both halves of the server signal it identically.
_native = ProxyProvider(upstream_client_factory)
_native.add_transform(EditorVersionTags())

mcp = FastMCP(
    name="MarketoBlendedMCP",
    providers=[_native],
)

register_custom_tools(mcp)


if __name__ == "__main__":
    # Replit (and most PaaS) inject the listen port via $PORT.
    port = int(os.environ.get("PORT", 8000))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
