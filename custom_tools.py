"""
Custom tools for the blended Marketo MCP server.

Every tool here covers a capability Adobe's native Marketo MCP server lacks.
All names carry a `custom_` prefix and descriptions start with [CUSTOM] so
clients (and their accept/reject prompts) can tell at a glance whether a call
goes through Adobe's native MCP (unprefixed) or directly to the Marketo REST
API (custom_*).
"""

from fastmcp import FastMCP

import marketo_functions
from marketo_rest.bridge import invoke
from marketo_rest import (
    crm_tools,
    email_tools,
    landing_page_tools,
    leads_tools,
    program_bulk_tools,
    v2_admin_tools,
)


def register_custom_tools(mcp: FastMCP, creds_provider=None):
    """Register every custom tool. By default credentials come from the
    current request's X-Marketo-* headers (blended server). The legacy
    env-credential servers pass creds_provider=legacy_api.env_creds instead.
    All tools delegate to the single-source API library (marketo_functions)
    via marketo_rest.bridge.invoke."""

    def _call(fn, *args, **kwargs):
        return invoke(creds_provider, fn, *args, **kwargs)

    # Expanded domain modules (leads/schema, CRM objects, program members +
    # bulk, emails/templates/files, landing pages/forms, Asset v2 + users).
    leads_tools.register(mcp, creds_provider=creds_provider)
    crm_tools.register(mcp, creds_provider=creds_provider)
    program_bulk_tools.register(mcp, creds_provider=creds_provider)
    email_tools.register(mcp, creds_provider=creds_provider)
    landing_page_tools.register(mcp, creds_provider=creds_provider)
    v2_admin_tools.register(mcp, creds_provider=creds_provider)

    # ========================================================================
    # Leads
    # ========================================================================

    @mcp.tool()
    def custom_sync_leads(leads: list, action: str = "createOrUpdate",
                          lookup_field: str = "email", async_processing: bool = False,
                          partition_name: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update leads. Each lead is a dict of field/value pairs
        (e.g. {"email": "a@b.com", "firstName": "Ann"}). action is one of
        createOnly, updateOnly, createOrUpdate, or createDuplicate (intentionally
        create a duplicate record, e.g. to test merging). Max 300 leads per call."""
        if len(leads) > 300:
            return {"error": f"Marketo allows at most 300 leads per sync call (got {len(leads)})."}
        return _call(marketo_functions.syncLeads, leads, action, lookup_field,
                     async_processing, partition_name)

    @mcp.tool()
    def custom_merge_leads(winning_lead_id: int, losing_lead_ids: list,
                           merge_in_crm: bool = False) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Merge duplicate leads into a winning lead. The winning lead retains its
        data; losing leads are merged into it and removed."""
        return _call(marketo_functions.mergeLeads, winning_lead_id, losing_lead_ids, merge_in_crm)

    @mcp.tool()
    def custom_get_lead_changes(lead_id: int, fields: list = None, days_back: int = 7) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get data value changes for a lead over the past days_back days."""
        return _call(marketo_functions.getLeadChanges, lead_id, fields, days_back)

    @mcp.tool()
    def custom_get_lead_activities_by_email(email: str, activity_type_ids: list = None,
                                            days_back: int = 7) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Look up a lead by email, then get its recent activities."""
        lead_data = _call(marketo_functions.lookupLead, "email", email)
        leads = lead_data.get("result", [])
        if not leads:
            return {"error": f"No lead found with email: {email}"}
        return _call(marketo_functions.getLeadActivities, leads[0].get("id"),
                     activity_type_ids, days_back)

    # ========================================================================
    # Emails
    # ========================================================================

    @mcp.tool()
    def custom_send_sample_email(email_id: int, email_address: str, text_only: bool = False,
                                 lead_id: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Send a sample of an email asset to an email address. Optionally
        impersonate a lead for token/dynamic-content rendering via lead_id."""
        return _call(marketo_functions.sendSampleEmail, email_id, email_address, text_only, lead_id)

    @mcp.tool()
    def custom_preview_email(email_id: int, status: str = None, content_type: str = "HTML",
                             lead_id: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the full rendered content of an email as it would be sent."""
        return _call(marketo_functions.previewEmail, email_id, status, content_type, lead_id)

    @mcp.tool()
    def custom_get_email_cc_fields() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the set of fields enabled for Email CC in the instance."""
        return _call(marketo_functions.getEmailCcFields)

    # ========================================================================
    # Landing Pages (native MCP has no landing page tools)
    # ========================================================================

    @mcp.tool()
    def custom_browse_landing_pages(max_return: int = 20, offset: int = 0,
                                    folder_id: int = None, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Browse landing pages with optional folder/status filtering."""
        return _call(marketo_functions.browseLandingPages, max_return, offset, folder_id, status)

    @mcp.tool()
    def custom_get_landing_page_by_id(landing_page_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a landing page by its ID."""
        return _call(marketo_functions.getLandingPageById, landing_page_id)

    @mcp.tool()
    def custom_get_landing_page_by_name(name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a landing page by its name."""
        return _call(marketo_functions.getLandingPageByName, name)

    @mcp.tool()
    def custom_get_landing_page_content(landing_page_id: int, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the content sections of a landing page (use to find content IDs
        before updating a section)."""
        return _call(marketo_functions.getLandingPageContent, landing_page_id, status)

    @mcp.tool()
    def custom_get_landing_page_full_content(landing_page_id: int, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the full rendered HTML of a landing page (preview)."""
        return _call(marketo_functions.getLandingPageFullContent, landing_page_id, status)

    @mcp.tool()
    def custom_update_landing_page(landing_page_id: int, name: str = None,
                                   description: str = None, title: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update landing page metadata (name, description, title)."""
        return _call(marketo_functions.updateLandingPage, landing_page_id, name, description, title)

    @mcp.tool()
    def custom_update_landing_page_content_section(landing_page_id: int, content_id: str,
                                                   content_type: str, value: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a content section of a landing page draft. content_id comes from
        custom_get_landing_page_content; content_type is the section type
        (e.g. HTML, RichText). Approve the draft afterwards to publish."""
        return _call(marketo_functions.updateLandingPageContentSection, landing_page_id,
                     content_id, content_type, value)

    @mcp.tool()
    def custom_approve_landing_page(landing_page_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Approve a landing page draft, publishing the changes."""
        return _call(marketo_functions.approveLandingPage, landing_page_id)

    @mcp.tool()
    def custom_unapprove_landing_page(landing_page_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Unapprove a landing page, taking it offline."""
        return _call(marketo_functions.unapproveLandingPage, landing_page_id)

    @mcp.tool()
    def custom_discard_landing_page_draft(landing_page_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Discard the draft version of a landing page."""
        return _call(marketo_functions.discardLandingPageDraft, landing_page_id)

    # ========================================================================
    # Bulk Lead Import
    # ========================================================================

    @mcp.tool()
    def custom_import_leads_csv(csv_content: str, lookup_field: str = "email",
                                list_id: int = None, partition_name: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Start a bulk lead import from CSV content (first row = field API names,
        e.g. 'email,firstName,lastName'). Returns a batchId — check progress
        with the native get_import_status tool, and failures/warnings with the
        custom_get_lead_import_* tools. Max 10MB."""
        if len(csv_content.encode()) > 10 * 1024 * 1024:
            return {"error": "CSV content exceeds Marketo's 10MB bulk import limit."}
        return _call(marketo_functions.importLeadsCsv, csv_content, lookup_field,
                     list_id, partition_name)

    @mcp.tool()
    def custom_get_lead_import_failures(batch_id: int) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the failures file for a bulk lead import batch (returns CSV text)."""
        return _call(marketo_functions.getLeadImportFailures, batch_id)

    @mcp.tool()
    def custom_get_lead_import_warnings(batch_id: int) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the warnings file for a bulk lead import batch (returns CSV text)."""
        return _call(marketo_functions.getLeadImportWarnings, batch_id)

    # ========================================================================
    # Program Members
    # ========================================================================

    @mcp.tool()
    def custom_query_program_members(program_id: int, filter_type: str, filter_values: str,
                                     fields: str = None, start_at: str = None,
                                     end_at: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query program members with filtering options."""
        return _call(marketo_functions.queryProgramMembers, program_id, filter_type,
                     filter_values, fields, start_at, end_at)

    # ========================================================================
    # Destructive / deactivation operations the native MCP omits
    # ========================================================================

    @mcp.tool()
    def custom_deactivate_smart_campaign(campaign_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Deactivate a smart campaign."""
        return _call(marketo_functions.deactivateSmartCampaign, campaign_id)

    @mcp.tool()
    def custom_delete_smart_campaign(campaign_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Permanently delete a smart campaign."""
        return _call(marketo_functions.deleteSmartCampaign, campaign_id)

    @mcp.tool()
    def custom_delete_program(program_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Permanently delete a program and all its child contents."""
        return _call(marketo_functions.deleteProgram, program_id)

    @mcp.tool()
    def custom_unapprove_email_program(program_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Unapprove an Email Program."""
        return _call(marketo_functions.unapproveEmailProgram, program_id)

    @mcp.tool()
    def custom_delete_token(folder_id: int, name: str, token_type: str,
                            folder_type: str = "Folder") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a token from a folder or program."""
        return _call(marketo_functions.deleteToken, folder_id, name, token_type, folder_type)
