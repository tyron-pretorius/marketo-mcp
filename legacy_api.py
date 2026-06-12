"""
Environment-credential plumbing so the legacy MCP servers (mcp_server.py,
mcp_server_auth.py) can expose the same expanded tool set as the blended
server. The blended server resolves credentials from X-Marketo-* request
headers; the legacy servers resolve them from .env at call time.
"""

import os

import dotenv
from fastmcp.exceptions import ToolError

from credentials import MarketoCreds

dotenv.load_dotenv()


def env_creds() -> MarketoCreds:
    client_id = os.environ.get("MARKETO_CLIENT_ID", "")
    client_secret = os.environ.get("MARKETO_CLIENT_SECRET", "")
    munchkin_id = os.environ.get("MARKETO_MUNCHKIN_ID", "")
    base_url = os.environ.get("MARKETO_BASE_URL", "")
    if not (client_id and client_secret and (base_url or munchkin_id)):
        raise ToolError(
            "Marketo credentials missing from environment: set MARKETO_CLIENT_ID, "
            "MARKETO_CLIENT_SECRET, and MARKETO_BASE_URL (or MARKETO_MUNCHKIN_ID) in .env"
        )
    return MarketoCreds(
        client_id=client_id,
        client_secret=client_secret,
        munchkin_id=munchkin_id,
        endpoint=base_url or None,
    )
