"""
Custom MCP tools covering Marketo Lead Database gaps: lead CRUD/lookup,
lead schema (custom field management), static-list membership, activities,
and custom activity type management.

Every tool name carries a `custom_` prefix and its description starts with
[CUSTOM] so clients can tell at a glance the call goes directly to the
Marketo REST API rather than through Adobe's native MCP.
"""

from fastmcp import FastMCP

import marketo_functions as mf
from marketo_rest.bridge import invoke


def register(mcp: FastMCP, creds_provider=None):
    def _call(fn, *args, **kwargs):
        return invoke(creds_provider, fn, *args, **kwargs)

    # ========================================================================
    # Leads
    # ========================================================================

    @mcp.tool()
    def custom_get_lead_by_id(lead_id: int, fields: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a single lead by its Marketo lead id. fields is an optional
        comma-separated string of field API names to return."""
        return _call(mf.getLeadById, lead_id, fields)

    @mcp.tool()
    def custom_delete_leads(lead_ids: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete leads by id. Max 300 lead ids per call."""
        return _call(mf.deleteLeads, lead_ids)

    @mcp.tool()
    def custom_describe_lead2() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe the lead object using the newer describe2 endpoint, which
        includes searchableFields and richer field metadata."""
        return _call(mf.describeLead2)

    @mcp.tool()
    def custom_get_lead_partitions() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List all lead partitions in the instance."""
        return _call(mf.getLeadPartitions)

    @mcp.tool()
    def custom_update_lead_partitions(assignments: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Move leads between partitions. assignments is a list of dicts, each
        with id (lead id) and partitionName."""
        return _call(mf.updateLeadPartitions, assignments)

    @mcp.tool()
    def custom_get_leads_by_program(program_id: int, fields: str = None,
                                    batch_size: int = None,
                                    next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get leads that are members of a program, including their program
        membership status. fields is a comma-separated string; paginate with
        next_page_token."""
        return _call(mf.getLeadsByProgram, program_id, fields, batch_size,
                     next_page_token)

    @mcp.tool()
    def custom_change_lead_program_status(program_id: int, lead_ids: list,
                                          status: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Change the program status of leads in a program (adds them as members
        if not already). status must be a valid status for the program's
        channel."""
        return _call(mf.changeLeadProgramStatus, program_id, lead_ids, status)

    @mcp.tool()
    def custom_push_leads(leads: list, lookup_field: str = None,
                          partition_name: str = None, program_name: str = None,
                          program_status: str = None, reason: str = None,
                          source: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Upsert leads and fire the "Lead is Pushed to Marketo" trigger. Each
        lead is a dict of field/value pairs. Max 300 leads per call."""
        return _call(mf.pushLeads, leads, lookup_field, partition_name,
                     program_name, program_status, reason, source)

    @mcp.tool()
    def custom_submit_form(form_id: int, lead_form_fields: dict,
                           visitor_data: dict = None, cookie: str = None,
                           program_id: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Submit a Marketo form programmatically for exactly one lead record
        (the input array is limited to 1). lead_form_fields is a dict keyed
        by the form's field names; visitor_data may include pageURL,
        queryString, leadClientIpAddress, userAgentString; cookie is the
        Munchkin _mch-... value to associate web activity."""
        return _call(mf.submitForm, form_id, lead_form_fields, visitor_data,
                     cookie, program_id)

    @mcp.tool()
    def custom_associate_lead(lead_id: int, cookie: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Associate a Munchkin web cookie (the _mch-... value) with a known
        lead, linking their anonymous web activity to the lead record."""
        return _call(mf.associateLead, lead_id, cookie)

    @mcp.tool()
    def custom_get_lead_list_membership(lead_id: int, batch_size: int = None,
                                        next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List the static lists a lead is a member of."""
        return _call(mf.getLeadListMembership, lead_id, batch_size,
                     next_page_token)

    @mcp.tool()
    def custom_get_lead_program_membership(lead_id: int, filter_type: str = None,
                                           filter_values: str = None,
                                           earliest_updated_at: str = None,
                                           latest_updated_at: str = None,
                                           batch_size: int = None,
                                           next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List the programs a lead is a member of, with optional filterType/
        filterValues and updatedAt datetime range filters."""
        return _call(mf.getLeadProgramMembership, lead_id, filter_type,
                     filter_values, earliest_updated_at, latest_updated_at,
                     batch_size, next_page_token)

    @mcp.tool()
    def custom_get_lead_smart_campaign_membership(lead_id: int,
                                                  earliest_updated_at: str = None,
                                                  latest_updated_at: str = None,
                                                  batch_size: int = None,
                                                  next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List the smart campaigns a lead is a member of, with optional
        updatedAt datetime range filters."""
        return _call(mf.getLeadSmartCampaignMembership, lead_id,
                     earliest_updated_at, latest_updated_at, batch_size,
                     next_page_token)

    # ========================================================================
    # Lead schema (custom field management)
    # ========================================================================

    @mcp.tool()
    def custom_get_lead_fields(batch_size: int = None,
                               next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List the lead object's field schema (all standard and custom
        fields)."""
        return _call(mf.getLeadFields, batch_size, next_page_token)

    @mcp.tool()
    def custom_create_lead_fields(fields: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create custom lead fields. fields is a list of dicts, each requiring
        displayName, name, and dataType (plus optional description, isHidden,
        isHtmlEncodingInEmail, isSensitive)."""
        return _call(mf.createLeadFields, fields)

    @mcp.tool()
    def custom_get_lead_field_by_name(field_api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the schema of a single lead field by its API name."""
        return _call(mf.getLeadFieldByName, field_api_name)

    @mcp.tool()
    def custom_update_lead_field(field_api_name: str, updates: dict) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a lead field's metadata (e.g. displayName, description,
        isHidden). updates is a dict of the attributes to change."""
        return _call(mf.updateLeadField, field_api_name, updates)

    # ========================================================================
    # Static list membership
    # ========================================================================

    @mcp.tool()
    def custom_remove_leads_from_list(list_id: int, lead_ids: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Remove leads from a static list by lead id. Max 300 lead ids per
        call."""
        return _call(mf.removeLeadsFromList, list_id, lead_ids)

    @mcp.tool()
    def custom_is_member_of_list(list_id: int, lead_ids: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Check whether the given lead ids are members of a static list."""
        return _call(mf.isMemberOfList, list_id, lead_ids)

    @mcp.tool()
    def custom_delete_static_list(list_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a static list (Asset API)."""
        return _call(mf.deleteStaticList, list_id)

    # ========================================================================
    # Activities
    # ========================================================================

    @mcp.tool()
    def custom_get_deleted_leads(next_page_token: str = None,
                                 since_datetime: str = None,
                                 batch_size: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get lead-deletion activities. Requires a paging token: pass
        next_page_token (e.g. from the native get_paging_token tool), or pass
        since_datetime (ISO 8601) and one will be fetched automatically."""
        return _call(mf.getDeletedLeads, next_page_token, since_datetime,
                     batch_size)

    @mcp.tool()
    def custom_add_custom_activities(activities: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Add custom activity records to leads. Each activity dict requires
        leadId, activityTypeId, activityDate, and primaryAttributeValue
        (plus an optional attributes list of {name, value} dicts). Max 300
        activities per call."""
        return _call(mf.addCustomActivities, activities)

    # ========================================================================
    # Custom activity type management
    # ========================================================================

    @mcp.tool()
    def custom_get_custom_activity_types() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List all custom activity types defined in the instance."""
        return _call(mf.getCustomActivityTypes)

    @mcp.tool()
    def custom_describe_custom_activity_type(api_name: str,
                                             draft: bool = False) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe a custom activity type by API name, including its attributes.
        Set draft=True to describe the draft version instead of approved."""
        return _call(mf.describeCustomActivityType, api_name, draft)

    @mcp.tool()
    def custom_create_custom_activity_type(api_name: str, name: str,
                                           filter_name: str, trigger_name: str,
                                           primary_attribute: dict,
                                           description: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create a custom activity type as a draft (approve it separately).
        primary_attribute is a dict with apiName, name, dataType."""
        return _call(mf.createCustomActivityType, api_name, name, filter_name,
                     trigger_name, primary_attribute, description)

    @mcp.tool()
    def custom_update_custom_activity_type(api_name: str, name: str = None,
                                           filter_name: str = None,
                                           trigger_name: str = None,
                                           primary_attribute: dict = None,
                                           description: str = None,
                                           new_api_name: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a custom activity type's draft. All body fields are optional;
        use new_api_name to rename the apiName itself."""
        return _call(mf.updateCustomActivityType, api_name, name, filter_name,
                     trigger_name, primary_attribute, description, new_api_name)

    @mcp.tool()
    def custom_approve_custom_activity_type(api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Approve the draft of a custom activity type, making it live."""
        return _call(mf.approveCustomActivityType, api_name)

    @mcp.tool()
    def custom_discard_custom_activity_type_draft(api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Discard the draft of a custom activity type."""
        return _call(mf.discardCustomActivityTypeDraft, api_name)

    @mcp.tool()
    def custom_delete_custom_activity_type(api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a custom activity type. It must first be removed from use by
        any assets and have no recent activity records."""
        return _call(mf.deleteCustomActivityType, api_name)

    @mcp.tool()
    def custom_add_custom_activity_type_attributes(api_name: str,
                                                   attributes: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Add secondary attributes to a custom activity type's draft. Each
        attribute dict requires apiName, name, and dataType."""
        return _call(mf.addCustomActivityTypeAttributes, api_name, attributes)

    @mcp.tool()
    def custom_update_custom_activity_type_attributes(api_name: str,
                                                      attributes: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update secondary attributes on a custom activity type's draft.
        attributes is a list of attribute dicts keyed by apiName."""
        return _call(mf.updateCustomActivityTypeAttributes, api_name, attributes)

    @mcp.tool()
    def custom_delete_custom_activity_type_attributes(api_name: str,
                                                      attributes: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete secondary attributes from a custom activity type's draft.
        attributes is a list of {"apiName": ...} dicts."""
        return _call(mf.deleteCustomActivityTypeAttributes, api_name, attributes)
