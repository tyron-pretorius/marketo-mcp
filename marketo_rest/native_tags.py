"""
Editor-version tags for Adobe's native Marketo MCP tools.

Adobe names its classic email tools `legacy_email_*` but never says legacy to
*what*: their descriptions mention no editor version, and "Legacy" reads as
"deprecated, avoid me". It is not deprecated — for an Email Editor 1.0/2.0
email these are the correct tools, and `legacy_email_create` is the only way to
create one through this server at all.

This transform prepends an editor tag to those tools' descriptions as they pass
through the proxy, matching the tags the custom_* tools carry, so an agent gets
the same signal from both halves of the blended server. Names are left exactly
as Adobe ships them: they are Adobe's public interface, they match Adobe's
docs, and renaming them would strand any prompt or script already using them.

The tag is prepended to whatever description upstream returns, so Adobe's own
wording stays intact and improvements to it flow through untouched. Native
tools not listed in TAGS pass through unchanged — including any email tools
Adobe adds later, which will arrive untagged until they are added here.
"""

from collections.abc import Sequence

from fastmcp.server.transforms import Transform
from fastmcp.tools import Tool

# The shared vocabulary. Keep in step with the bracket tags in
# marketo_rest/email_tools.py, marketo_rest/v2_admin_tools.py and the snippet
# tools in marketo_rest/landing_page_tools.py.
_LEGACY_EMAIL = (
    "[EMAIL EDITOR 1.0/2.0 EMAILS ONLY — \"Legacy\" here means Email Editor "
    "1.0/2.0, NOT deprecated: this is the correct tool for a classic email. "
    "It fails with 709 'Cannot access content for Acrite Email asset' on new "
    "Email Designer (Editor 3.0) emails — for those use the unsuffixed "
    "custom_*_email tools.]"
)

# Snippets are asset-level: none of these tools name a consuming email or
# landing page, and the snippet lives in its own Design Studio folder. They
# are not editor-specific, but the email side of "both" only reaches classic
# emails — the Designer has no snippets at all, it has fragments.
_SNIPPET = (
    "[ASSET-LEVEL — a snippet is a reusable-content mechanism available in "
    "Email Editor 1.0/2.0 emails AND in "
    "landing pages. New Email Designer (Editor 3.0) emails do not use snippets "
    "at all; their reusable content is fragments (custom_*_fragment). Landing "
    "pages are unaffected by the editor distinction.]"
)

TAGS: dict[str, str] = {
    "legacy_email_create": _LEGACY_EMAIL,
    "legacy_email_get_by_id": _LEGACY_EMAIL,
    "legacy_email_get_by_name": _LEGACY_EMAIL,
    "legacy_email_get_content": _LEGACY_EMAIL,
    "legacy_email_update_content": _LEGACY_EMAIL,
    "legacy_email_approve": _LEGACY_EMAIL,
    "browse_snippets": _SNIPPET,
    "facet_snippets": _SNIPPET,
    "get_snippet_by_id": _SNIPPET,
    "get_snippet_content": _SNIPPET,
    "get_snippet_dynamic_content": _SNIPPET,
    "create_snippet": _SNIPPET,
    "update_snippet": _SNIPPET,
    "update_snippet_content": _SNIPPET,
    "update_snippet_dynamic_content": _SNIPPET,
    "clone_snippet": _SNIPPET,
    "approve_snippet": _SNIPPET,
}


def _tag(tool: Tool) -> Tool:
    """Return tool with its editor tag prepended, or unchanged if untagged."""
    tag = TAGS.get(tool.name)
    if not tag:
        return tool
    description = f"{tag}\n{tool.description}" if tool.description else tag
    return tool.model_copy(update={"description": description})


class EditorVersionTags(Transform):
    """Prepend editor-version tags to Adobe's native email tools."""

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [_tag(t) for t in tools]

    async def get_tool(self, name, call_next, *, version=None):
        # Names are not rewritten, so the downstream lookup needs no reversal.
        tool = await call_next(name, version=version)
        return _tag(tool) if tool else None
