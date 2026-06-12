"""
Bridge between MCP tool wrappers and the single-source API library
(marketo_functions.py).

Every MCP tool — in the blended server and both legacy servers — resolves
credentials through a provider, takes a cached OAuth token, routes the call to
the right Marketo instance via marketo_functions.base_url_override, and
retries once on Marketo 601/602 (invalid/expired token) errors.

The blended server's provider reads the request's X-Marketo-* headers
(credentials.get_marketo_creds); the legacy servers use legacy_api.env_creds.
"""

import marketo_functions
from credentials import TOKENS, get_marketo_creds


def _is_token_error(payload):
    return isinstance(payload, dict) and any(
        e.get('code') in ('601', '602') for e in (payload.get('errors') or []))


def invoke(creds_provider, fn, *args, **kwargs):
    """Run fn(token, *args, **kwargs) against the provider's instance."""
    creds = (creds_provider or get_marketo_creds)()
    result = None
    for attempt in (1, 2):
        token = TOKENS.get_token(creds)
        with marketo_functions.base_url_override(creds.base_url):
            result = fn(token, *args, **kwargs)
        if _is_token_error(result) and attempt == 1:
            TOKENS.invalidate(creds)
            continue
        return result
    return result
