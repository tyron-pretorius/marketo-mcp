"""
Custom MCP tools for Marketo CRM-style Lead Database objects:
companies, opportunities, opportunity roles, sales persons, custom objects,
custom object types (schema), and named accounts / named account lists (ABM).

Notes:
- The companies/opportunities/salespersons sync APIs are only usable when no
  native CRM sync (Salesforce/Microsoft Dynamics) is enabled in the instance.
- Named account and named account list APIs require an ABM-enabled subscription.
"""

from fastmcp import FastMCP

import marketo_functions as mf
from marketo_rest.bridge import invoke


def register(mcp: FastMCP, creds_provider=None):
    def _call(fn, *args, **kwargs):
        return invoke(creds_provider, fn, *args, **kwargs)

    # ========================================================================
    # Companies
    # ========================================================================

    @mcp.tool()
    def custom_query_companies(filter_type: str, filter_values: str, fields: str = None,
                               batch_size: int = None, next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query company records. filter_type is a searchable company field (see
        custom_describe_companies); filter_values is a comma-separated list of
        values. fields is an optional comma-separated list of fields to return."""
        return _call(mf.queryCompanies, filter_type, filter_values, fields,
                     batch_size, next_page_token)

    @mcp.tool()
    def custom_sync_companies(records: list, action: str = "createOrUpdate",
                              dedupe_by: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update company records (max 300). Each record is a dict
        of field/value pairs. action is one of createOnly, updateOnly,
        createOrUpdate. dedupe_by is dedupeFields (default) or idField.
        Only usable when no native CRM sync is enabled in the instance."""
        return _call(mf.syncCompanies, records, action, dedupe_by)

    @mcp.tool()
    def custom_delete_companies(records: list, delete_by: str = "dedupeFields") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete company records (max 300). Each record identifies a company by
        its dedupe fields or id, per delete_by (dedupeFields or idField).
        Only usable when no native CRM sync is enabled in the instance."""
        return _call(mf.deleteCompanies, records, delete_by)

    @mcp.tool()
    def custom_describe_companies() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe the company object: fields, dedupe fields, searchable fields."""
        return _call(mf.describeCompanies)

    @mcp.tool()
    def custom_get_company_fields(batch_size: int = None, next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get metadata for all fields on the company object."""
        return _call(mf.getCompanyFields, batch_size, next_page_token)

    @mcp.tool()
    def custom_get_company_field_by_name(field_api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get metadata for a single company field by its API name."""
        return _call(mf.getCompanyFieldByName, field_api_name)

    # ========================================================================
    # Opportunities
    # ========================================================================

    @mcp.tool()
    def custom_query_opportunities(filter_type: str, filter_values: str, fields: str = None,
                                   batch_size: int = None, next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query opportunity records. filter_type is a searchable opportunity
        field (see custom_describe_opportunities); filter_values is a
        comma-separated list of values."""
        return _call(mf.queryOpportunities, filter_type, filter_values, fields,
                     batch_size, next_page_token)

    @mcp.tool()
    def custom_sync_opportunities(records: list, action: str = "createOrUpdate",
                                  dedupe_by: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update opportunity records (max 300). action is one of
        createOnly, updateOnly, createOrUpdate. dedupe_by is dedupeFields
        (default) or idField. Only usable when no native CRM sync is enabled
        in the instance."""
        return _call(mf.syncOpportunities, records, action, dedupe_by)

    @mcp.tool()
    def custom_delete_opportunities(records: list, delete_by: str = "dedupeFields") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete opportunity records (max 300). delete_by is dedupeFields or
        idField. Only usable when no native CRM sync is enabled in the
        instance."""
        return _call(mf.deleteOpportunities, records, delete_by)

    @mcp.tool()
    def custom_describe_opportunities() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe the opportunity object: fields, dedupe fields, searchable
        fields."""
        return _call(mf.describeOpportunities)

    @mcp.tool()
    def custom_get_opportunity_fields(batch_size: int = None, next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get metadata for all fields on the opportunity object."""
        return _call(mf.getOpportunityFields, batch_size, next_page_token)

    @mcp.tool()
    def custom_get_opportunity_field_by_name(field_api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get metadata for a single opportunity field by its API name."""
        return _call(mf.getOpportunityFieldByName, field_api_name)

    # ========================================================================
    # Opportunity roles
    # ========================================================================

    @mcp.tool()
    def custom_query_opportunity_roles(filter_type: str, filter_values: str, fields: str = None,
                                       batch_size: int = None, next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query opportunity role records linking leads to opportunities.
        filter_type is a searchable role field (see
        custom_describe_opportunity_roles); filter_values is comma-separated."""
        return _call(mf.queryOpportunityRoles, filter_type, filter_values,
                     fields, batch_size, next_page_token)

    @mcp.tool()
    def custom_sync_opportunity_roles(records: list, action: str = "createOrUpdate",
                                      dedupe_by: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update opportunity roles (max 300). Each record needs
        externalOpportunityId, leadId, and role. action is one of createOnly,
        updateOnly, createOrUpdate. dedupe_by is dedupeFields (default) or
        idField. Only usable when no native CRM sync is enabled in the
        instance."""
        return _call(mf.syncOpportunityRoles, records, action, dedupe_by)

    @mcp.tool()
    def custom_delete_opportunity_roles(records: list, delete_by: str = "dedupeFields") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete opportunity role records (max 300). delete_by is dedupeFields
        or idField. Only usable when no native CRM sync is enabled in the
        instance."""
        return _call(mf.deleteOpportunityRoles, records, delete_by)

    @mcp.tool()
    def custom_describe_opportunity_roles() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe the opportunity role object: fields, dedupe fields,
        searchable fields."""
        return _call(mf.describeOpportunityRoles)

    # ========================================================================
    # Sales persons
    # ========================================================================

    @mcp.tool()
    def custom_query_sales_persons(filter_type: str, filter_values: str, fields: str = None,
                                   batch_size: int = None, next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query sales person records. filter_type is a searchable sales person
        field (see custom_describe_sales_persons); filter_values is
        comma-separated."""
        return _call(mf.querySalesPersons, filter_type, filter_values, fields,
                     batch_size, next_page_token)

    @mcp.tool()
    def custom_sync_sales_persons(records: list, action: str = "createOrUpdate",
                                  dedupe_by: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update sales person records (max 300). action is one of
        createOnly, updateOnly, createOrUpdate. dedupe_by is dedupeFields
        (default) or idField. Only usable when no native CRM sync is enabled
        in the instance."""
        return _call(mf.syncSalesPersons, records, action, dedupe_by)

    @mcp.tool()
    def custom_delete_sales_persons(records: list, delete_by: str = "dedupeFields") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete sales person records (max 300). delete_by is dedupeFields or
        idField. Only usable when no native CRM sync is enabled in the
        instance."""
        return _call(mf.deleteSalesPersons, records, delete_by)

    @mcp.tool()
    def custom_describe_sales_persons() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe the sales person object: fields, dedupe fields, searchable
        fields."""
        return _call(mf.describeSalesPersons)

    # ========================================================================
    # Custom objects (records)
    # ========================================================================

    @mcp.tool()
    def custom_list_custom_objects(names: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List custom object types available in the instance. names is an
        optional comma-separated list of API names to filter by."""
        return _call(mf.listCustomObjects, names)

    @mcp.tool()
    def custom_query_custom_objects(object_api_name: str, filter_type: str = None,
                                    filter_values: str = None, fields: str = None,
                                    batch_size: int = None, next_page_token: str = None,
                                    compound_filter: list = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query records of a custom object type. Standard mode: pass filter_type
        (a searchable field, see custom_describe_custom_object) and
        filter_values (comma-separated). Compound-key mode: for objects whose
        dedupe key spans multiple fields, pass compound_filter as a list of
        dicts (each dict gives the key field values for one record); the call
        is then sent as a POST with _method=GET and body
        {filterType, fields, input: compound_filter}."""
        return _call(mf.queryCustomObjects, object_api_name, filter_type,
                     filter_values, fields, batch_size, next_page_token,
                     compound_filter)

    @mcp.tool()
    def custom_sync_custom_objects(object_api_name: str, records: list,
                                   action: str = "createOrUpdate",
                                   dedupe_by: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update records of a custom object type (max 300). action
        is one of createOnly, updateOnly, createOrUpdate. dedupe_by is
        dedupeFields (default) or idField."""
        return _call(mf.syncCustomObjects, object_api_name, records, action,
                     dedupe_by)

    @mcp.tool()
    def custom_delete_custom_objects(object_api_name: str, records: list,
                                     delete_by: str = "dedupeFields") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete records of a custom object type (max 300). delete_by is
        dedupeFields or idField; each record identifies one object record."""
        return _call(mf.deleteCustomObjects, object_api_name, records, delete_by)

    @mcp.tool()
    def custom_describe_custom_object(object_api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe a custom object type: fields, dedupe fields, searchable
        fields, and relationships."""
        return _call(mf.describeCustomObject, object_api_name)

    # ========================================================================
    # Custom object types (schema)
    # ========================================================================

    @mcp.tool()
    def custom_list_custom_object_types(names: str = None, state: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List custom object type schemas. names is an optional comma-separated
        list of API names; state filters by draft, approved, or
        approvedWithDraft."""
        return _call(mf.listCustomObjectTypes, names, state)

    @mcp.tool()
    def custom_sync_custom_object_type(api_name: str, display_name: str, action: str = None,
                                       plural_name: str = None, description: str = None,
                                       show_in_lead_detail: bool = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create or update a custom object type as a draft. action is one of
        createOnly, updateOnly, createOrUpdate. The draft must be approved
        (custom_approve_custom_object_type) before records can be synced."""
        return _call(mf.syncCustomObjectType, api_name, display_name, action,
                     plural_name, description, show_in_lead_detail)

    @mcp.tool()
    def custom_describe_custom_object_type(api_name: str, state: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe a custom object type schema by API name. state selects which
        version to describe (draft or approved)."""
        return _call(mf.describeCustomObjectType, api_name, state)

    @mcp.tool()
    def custom_get_custom_object_field_types() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the list of data types available for custom object fields."""
        return _call(mf.getCustomObjectFieldTypes)

    @mcp.tool()
    def custom_get_custom_object_linkable_objects() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the objects (lead, company, etc.) that custom object link fields
        can relate to."""
        return _call(mf.getCustomObjectLinkableObjects)

    @mcp.tool()
    def custom_get_custom_object_type_dependents(api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get assets (smart lists, campaigns, etc.) that depend on a custom
        object type."""
        return _call(mf.getCustomObjectTypeDependents, api_name)

    @mcp.tool()
    def custom_add_custom_object_type_fields(api_name: str, fields: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Add fields to a custom object type draft. Each field dict needs name,
        displayName, and dataType, plus optional description, isDedupeField,
        and relatedTo ({field, name}) for link fields."""
        return _call(mf.addCustomObjectTypeFields, api_name, fields)

    @mcp.tool()
    def custom_update_custom_object_type_field(api_name: str, field_api_name: str,
                                               updates: dict) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a field on a custom object type draft. updates is a dict of
        attributes to change (e.g. displayName, description, isDedupeField)."""
        return _call(mf.updateCustomObjectTypeField, api_name, field_api_name,
                     updates)

    @mcp.tool()
    def custom_delete_custom_object_type_fields(api_name: str, field_names: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete fields from a custom object type draft. field_names is a list
        of field API names to remove."""
        return _call(mf.deleteCustomObjectTypeFields, api_name, field_names)

    @mcp.tool()
    def custom_approve_custom_object_type(api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Approve the draft of a custom object type, making it usable for
        records."""
        return _call(mf.approveCustomObjectType, api_name)

    @mcp.tool()
    def custom_discard_custom_object_type_draft(api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Discard the draft version of a custom object type."""
        return _call(mf.discardCustomObjectTypeDraft, api_name)

    @mcp.tool()
    def custom_delete_custom_object_type(api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a custom object type entirely. The type must have no dependent
        assets and no records."""
        return _call(mf.deleteCustomObjectType, api_name)

    # ========================================================================
    # Named accounts (ABM)
    # ========================================================================

    @mcp.tool()
    def custom_query_named_accounts(filter_type: str, filter_values: str, fields: str = None,
                                    batch_size: int = None, next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query named account records. Requires an ABM-enabled subscription.
        filter_type is a searchable named account field (see
        custom_describe_named_accounts); filter_values is comma-separated."""
        return _call(mf.queryNamedAccounts, filter_type, filter_values, fields,
                     batch_size, next_page_token)

    @mcp.tool()
    def custom_sync_named_accounts(records: list, action: str = "createOrUpdate",
                                   dedupe_by: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update named accounts (max 300). Requires an ABM-enabled
        subscription. action is one of createOnly, updateOnly, createOrUpdate.
        dedupe_by is dedupeFields (default) or idField."""
        return _call(mf.syncNamedAccounts, records, action, dedupe_by)

    @mcp.tool()
    def custom_delete_named_accounts(records: list, delete_by: str = "dedupeFields") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete named accounts (max 300). Requires an ABM-enabled subscription.
        delete_by is dedupeFields or idField."""
        return _call(mf.deleteNamedAccounts, records, delete_by)

    @mcp.tool()
    def custom_describe_named_accounts() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Describe the named account object: fields, dedupe fields, searchable
        fields. Requires an ABM-enabled subscription."""
        return _call(mf.describeNamedAccounts)

    @mcp.tool()
    def custom_get_named_account_fields(batch_size: int = None,
                                        next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get metadata for all fields on the named account object. Requires an
        ABM-enabled subscription."""
        return _call(mf.getNamedAccountFields, batch_size, next_page_token)

    @mcp.tool()
    def custom_get_named_account_field_by_name(field_api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get metadata for a single named account field by its API name.
        Requires an ABM-enabled subscription."""
        return _call(mf.getNamedAccountFieldByName, field_api_name)

    # ========================================================================
    # Named account lists (ABM)
    # ========================================================================

    @mcp.tool()
    def custom_query_named_account_lists(filter_type: str, filter_values: str,
                                         batch_size: int = None,
                                         next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Query named account lists. Requires an ABM-enabled subscription.
        filter_type is dedupeFields (list name) or idField; filter_values is
        comma-separated."""
        return _call(mf.queryNamedAccountLists, filter_type, filter_values,
                     batch_size, next_page_token)

    @mcp.tool()
    def custom_sync_named_account_lists(records: list, action: str = "createOrUpdate",
                                        dedupe_by: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create and/or update named account lists (max 300). Requires an
        ABM-enabled subscription. Each record is a dict with name (and id for
        updates). action is one of createOnly, updateOnly, createOrUpdate.
        dedupe_by is dedupeFields (default) or idField."""
        return _call(mf.syncNamedAccountLists, records, action, dedupe_by)

    @mcp.tool()
    def custom_delete_named_account_lists(records: list,
                                          delete_by: str = "dedupeFields") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete named account lists (max 300). Requires an ABM-enabled
        subscription. delete_by is dedupeFields or idField."""
        return _call(mf.deleteNamedAccountLists, records, delete_by)

    @mcp.tool()
    def custom_get_named_account_list_members(list_id: str, fields: str = None,
                                              batch_size: int = None,
                                              next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the named accounts that are members of a named account list.
        Requires an ABM-enabled subscription."""
        return _call(mf.getNamedAccountListMembers, list_id, fields, batch_size,
                     next_page_token)

    @mcp.tool()
    def custom_add_named_account_list_members(list_id: str, account_ids: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Add named accounts to a named account list by their marketoGUID ids
        (max 300). Requires an ABM-enabled subscription."""
        return _call(mf.addNamedAccountListMembers, list_id, account_ids)

    @mcp.tool()
    def custom_remove_named_account_list_members(list_id: str, account_ids: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Remove named accounts from a named account list by their marketoGUID
        ids (max 300). Requires an ABM-enabled subscription."""
        return _call(mf.removeNamedAccountListMembers, list_id, account_ids)
