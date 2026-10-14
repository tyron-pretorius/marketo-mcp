"""
Per-request Marketo credential handling for the blended MCP server.

Clients send three headers on every request (plus one optional override):

    client-id        REST API client ID (LaunchPoint service)
    client-secret    REST API client secret
    munchkin         Instance Munchkin ID, e.g. 123-ABC-456
    endpoint         (optional) REST base URL override, without /rest

These short names are what Claude Desktop's "Add custom connector" form asks
for, so a connector can be set up by typing the same three values Marketo shows
in Admin, with no vendor-prefixed header names to get wrong.

Adobe's native MCP server still expects its own X-Marketo-* header names, so
extract_marketo_headers() translates on the way upstream. That translation is
one-way: this server accepts only the short names from clients.

No credentials are read from the environment.
"""

import hashlib
import threading
import time
from dataclasses import dataclass

import requests
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

# Hyphens, not underscores: nginx and several other reverse proxies drop
# headers containing underscores by default, which would strip the credentials
# before they ever reached this server.
HEADER_CLIENT_ID = "client-id"
HEADER_CLIENT_SECRET = "client-secret"
HEADER_MUNCHKIN_ID = "munchkin"
HEADER_ENDPOINT = "endpoint"

REQUIRED_HEADERS = (HEADER_CLIENT_ID, HEADER_CLIENT_SECRET, HEADER_MUNCHKIN_ID)

_MISSING_HEADERS_HELP = (
    "Send client-id, client-secret, and munchkin (and optionally endpoint) "
    "on every MCP request."
)


def extract_marketo_headers() -> dict:
    """Read the credential headers from the current HTTP request and return
    them under the X-Marketo-* names the native Marketo MCP expects.

    Raises ToolError naming any missing header.
    """
    headers = get_http_headers()  # lowercased keys; {} outside HTTP context
    missing = [h for h in REQUIRED_HEADERS if not headers.get(h)]
    if missing:
        pretty = ", ".join(missing)
        raise ToolError(f"Missing Marketo auth headers: {pretty}. {_MISSING_HEADERS_HELP}")

    forward = {
        "X-Marketo-Client-Id": headers[HEADER_CLIENT_ID],
        "X-Marketo-Client-Secret": headers[HEADER_CLIENT_SECRET],
        "X-Marketo-Munchkin-Id": headers[HEADER_MUNCHKIN_ID],
    }
    if headers.get(HEADER_ENDPOINT):
        forward["X-Marketo-Endpoint"] = headers[HEADER_ENDPOINT]
    return forward


@dataclass(frozen=True)
class MarketoCreds:
    client_id: str
    client_secret: str
    munchkin_id: str
    endpoint: str = None

    @property
    def base_url(self) -> str:
        url = self.endpoint or f"https://{self.munchkin_id}.mktorest.com"
        url = url.rstrip("/")
        if url.endswith("/rest"):
            url = url[: -len("/rest")]
        return url


def get_marketo_creds() -> MarketoCreds:
    """Build MarketoCreds from the current request's headers (custom-tool path)."""
    headers = get_http_headers()
    missing = [h for h in REQUIRED_HEADERS if not headers.get(h)]
    if missing:
        pretty = ", ".join(missing)
        raise ToolError(f"Missing Marketo auth headers: {pretty}. {_MISSING_HEADERS_HELP}")

    return MarketoCreds(
        client_id=headers[HEADER_CLIENT_ID],
        client_secret=headers[HEADER_CLIENT_SECRET],
        munchkin_id=headers[HEADER_MUNCHKIN_ID],
        endpoint=headers.get(HEADER_ENDPOINT) or None,
    )


class TokenManager:
    """Caches Marketo REST OAuth tokens per credential set until near expiry."""

    EXPIRY_SKEW_SECONDS = 120

    def __init__(self):
        self._cache = {}  # key -> (token, expires_at)
        self._lock = threading.Lock()

    @staticmethod
    def _key(creds: MarketoCreds) -> str:
        raw = f"{creds.base_url}|{creds.client_id}|{creds.client_secret}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_token(self, creds: MarketoCreds) -> str:
        key = self._key(creds)
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[1] - self.EXPIRY_SKEW_SECONDS > now:
                return cached[0]

        token, expires_at = self._fetch_token(creds)
        with self._lock:
            self._cache[key] = (token, expires_at)
        return token

    def invalidate(self, creds: MarketoCreds):
        with self._lock:
            self._cache.pop(self._key(creds), None)

    @staticmethod
    def _fetch_token(creds: MarketoCreds):
        try:
            response = requests.get(
                creds.base_url + "/identity/oauth/token",
                params={
                    "grant_type": "client_credentials",
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                },
                timeout=30,
            )
            data = response.json()
        except requests.RequestException as exc:
            raise ToolError(
                f"Could not reach Marketo identity endpoint at {creds.base_url}: {type(exc).__name__}"
            ) from exc
        except ValueError as exc:
            raise ToolError(
                f"Marketo identity endpoint at {creds.base_url} returned a non-JSON response "
                f"(HTTP {response.status_code})."
            ) from exc

        if "access_token" not in data:
            # Marketo returns {"error": ..., "error_description": ...} on bad creds
            detail = data.get("error_description") or data.get("error") or "unknown error"
            raise ToolError(f"Marketo authentication failed: {detail}")

        return data["access_token"], time.time() + float(data.get("expires_in", 3599))


TOKENS = TokenManager()
