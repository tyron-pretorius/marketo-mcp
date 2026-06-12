"""
MCP tools for the Marketo Asset v2 API ("Emails 2.0": emails, email templates,
fragments) and the User Management API.

Asset v2 endpoints live under /rest/asset/v2 (no .json suffix) and require the
Emails 2.0 experience to be enabled on the Marketo instance. User Management
endpoints live under /userservice/management/v1 and require an API role with
the "Access User Management" permission. Tool bodies delegate to the
single-source API library (marketo_functions.py) through
marketo_rest.bridge.invoke, which resolves credentials, takes a cached token,
routes to the right instance, and retries once on 601/602.

Every tool name carries a `custom_` prefix and its description starts with
[CUSTOM] so clients can tell at a glance that the call goes directly to the
Marketo REST API rather than through Adobe's native MCP.
"""

from fastmcp import FastMCP

import marketo_functions as mf
from marketo_rest.bridge import invoke


def _wrap(resp):
    """User Management endpoints may return raw arrays; wrap them so the
    tool return type stays dict."""
    if isinstance(resp, list):
        return {"result": resp}
    return resp


def register(mcp: FastMCP, creds_provider=None):
    def _call(fn, *args, **kwargs):
        return _wrap(invoke(creds_provider, fn, *args, **kwargs))

    # ========================================================================
    # Asset v2 — Emails (Emails 2.0)
    # ========================================================================

    @mcp.tool()
    def custom_get_email2_by_id(email_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get an Emails 2.0 email by id (Asset v2). Requires the Emails 2.0
        experience to be enabled on the instance."""
        return _call(mf.getEmail2ById, email_id)

    @mcp.tool()
    def custom_create_email2(name: str, app_data: dict, headers: dict,
                             description: str = None, template_id: int = None,
                             theme_id: str = None, data: dict = None,
                             settings: dict = None, status: str = None,
                             editor_context: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create an Emails 2.0 email (Asset v2). app_data maps to appData (folder
        placement etc.), headers carries subject/fromName/fromEmail/replyTo.
        Requires the Emails 2.0 experience to be enabled on the instance."""
        # mf.createEmail2 names the Marketo `headers` body field `emailHeaders`.
        return _call(mf.createEmail2, name, app_data, headers, description,
                     template_id, theme_id, data, settings, status,
                     editor_context)

    @mcp.tool()
    def custom_update_email2(email_id: int, name: str = None, description: str = None,
                             data: dict = None, headers: dict = None,
                             settings: dict = None, template_id: int = None,
                             theme_id: str = None, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update an Emails 2.0 email (Asset v2): name, description, data, headers,
        settings, templateId, themeId and/or status. Requires the Emails 2.0
        experience to be enabled on the instance."""
        # mf.updateEmail2 names the Marketo `headers` body field `emailHeaders`.
        return _call(mf.updateEmail2, email_id, name, description, data,
                     headers, settings, template_id, theme_id, status)

    @mcp.tool()
    def custom_delete_email2(email_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete an Emails 2.0 email (Asset v2). Requires the Emails 2.0
        experience to be enabled on the instance."""
        return _call(mf.deleteEmail2, email_id)

    @mcp.tool()
    def custom_clone_email2(email_id: int, name: str, folder_id: int,
                            extra: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Clone an Emails 2.0 email (Asset v2) into a folder under a new name.
        extra merges additional fields into the newAsset object. Requires the
        Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.cloneEmail2, email_id, name, folder_id, extra)

    @mcp.tool()
    def custom_transition_email2_state(email_id: int, action: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Transition an Emails 2.0 email's approval state (Asset v2). action is
        e.g. approve, unapprove, or discard (discard draft). Requires the
        Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.transitionEmail2State, email_id, action)

    @mcp.tool()
    def custom_get_email2_used_by(email_id: int, page_index: int = None,
                                  page_size: int = None, type: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List assets that use an Emails 2.0 email (Asset v2 usedby). Requires the
        Emails 2.0 experience to be enabled on the instance."""
        # mf.getEmail2UsedBy exposes the Marketo `type` body field as `assetType`.
        return _call(mf.getEmail2UsedBy, email_id, page_index, page_size, type)

    # ========================================================================
    # Asset v2 — Email templates (Emails 2.0)
    # ========================================================================

    @mcp.tool()
    def custom_browse_email_templates2(workspace_id: int, folder_id: int = None,
                                       status: str = None, name: str = None,
                                       page_index: int = None, page_size: int = None,
                                       sort_key: str = None, sort_order: str = None,
                                       include_archived: bool = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Browse Emails 2.0 email templates (Asset v2) in a workspace, optionally
        filtered by folder, status or name. Requires the Emails 2.0 experience
        to be enabled on the instance."""
        return _call(mf.browseEmailTemplates2, workspace_id, folder_id, status,
                     name, page_index, page_size, sort_key, sort_order,
                     include_archived)

    @mcp.tool()
    def custom_get_email_template2_by_id(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get an Emails 2.0 email template by id (Asset v2). Requires the
        Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.getEmailTemplate2ById, template_id)

    @mcp.tool()
    def custom_create_email_template2(name: str, app_data: dict, description: str = None,
                                      data: dict = None, theme_id: str = None,
                                      status: str = None, editor_context: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create an Emails 2.0 email template (Asset v2). app_data maps to appData
        (folder placement etc.). Requires the Emails 2.0 experience to be
        enabled on the instance."""
        return _call(mf.createEmailTemplate2, name, app_data, description, data,
                     theme_id, status, editor_context)

    @mcp.tool()
    def custom_update_email_template2(template_id: int, name: str = None,
                                      description: str = None, data: dict = None,
                                      theme_id: str = None, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update an Emails 2.0 email template (Asset v2): name, description, data,
        themeId and/or status. Requires the Emails 2.0 experience to be enabled
        on the instance."""
        return _call(mf.updateEmailTemplate2, template_id, name, description,
                     data, theme_id, status)

    @mcp.tool()
    def custom_delete_email_template2(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete an Emails 2.0 email template (Asset v2). Requires the Emails 2.0
        experience to be enabled on the instance."""
        return _call(mf.deleteEmailTemplate2, template_id)

    @mcp.tool()
    def custom_clone_email_template2(template_id: int, name: str, folder_id: int,
                                     extra: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Clone an Emails 2.0 email template (Asset v2) into a folder under a new
        name. extra merges additional fields into the newAsset object. Requires
        the Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.cloneEmailTemplate2, template_id, name, folder_id, extra)

    @mcp.tool()
    def custom_transition_email_template2_state(template_id: int, action: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Transition an Emails 2.0 email template's approval state (Asset v2).
        action is e.g. approve, unapprove, or discard (discard draft). Requires
        the Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.transitionEmailTemplate2State, template_id, action)

    @mcp.tool()
    def custom_get_email_template2_used_by(template_id: int, page_index: int = None,
                                           page_size: int = None, type: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List assets that use an Emails 2.0 email template (Asset v2 usedby).
        Requires the Emails 2.0 experience to be enabled on the instance."""
        # mf.getEmailTemplate2UsedBy exposes the Marketo `type` body field as `assetType`.
        return _call(mf.getEmailTemplate2UsedBy, template_id, page_index,
                     page_size, type)

    # ========================================================================
    # Asset v2 — Fragments (Emails 2.0)
    # ========================================================================

    @mcp.tool()
    def custom_browse_fragments(workspace_id: int, folder_id: int = None,
                                status: str = None, name: str = None,
                                fragment_type: str = None, page_index: int = None,
                                page_size: int = None, sort_key: str = None,
                                sort_order: str = None,
                                include_archived: bool = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Browse Emails 2.0 fragments (Asset v2) in a workspace, optionally
        filtered by folder, status, name or fragment type. Requires the
        Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.browseFragments, workspace_id, folder_id, status, name,
                     fragment_type, page_index, page_size, sort_key, sort_order,
                     include_archived)

    @mcp.tool()
    def custom_get_fragment_by_id(fragment_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get an Emails 2.0 fragment by id (Asset v2). Requires the Emails 2.0
        experience to be enabled on the instance."""
        return _call(mf.getFragmentById, fragment_id)

    @mcp.tool()
    def custom_create_fragment(name: str, app_data: dict, settings: dict,
                               description: str = None, data: dict = None,
                               theme_id: str = None, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create an Emails 2.0 fragment (Asset v2). app_data maps to appData
        (folder placement etc.); settings is required. Requires the Emails 2.0
        experience to be enabled on the instance."""
        return _call(mf.createFragment, name, app_data, settings, description,
                     data, theme_id, status)

    @mcp.tool()
    def custom_update_fragment(fragment_id: int, name: str = None,
                               description: str = None, data: dict = None,
                               settings: dict = None, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update an Emails 2.0 fragment (Asset v2): name, description, data,
        settings and/or status. Requires the Emails 2.0 experience to be
        enabled on the instance."""
        return _call(mf.updateFragment, fragment_id, name, description, data,
                     settings, status)

    @mcp.tool()
    def custom_delete_fragment(fragment_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete an Emails 2.0 fragment (Asset v2). Requires the Emails 2.0
        experience to be enabled on the instance."""
        return _call(mf.deleteFragment, fragment_id)

    @mcp.tool()
    def custom_clone_fragment(fragment_id: int, name: str, folder_id: int,
                              extra: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Clone an Emails 2.0 fragment (Asset v2) into a folder under a new name.
        extra merges additional fields into the newAsset object. Requires the
        Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.cloneFragment, fragment_id, name, folder_id, extra)

    @mcp.tool()
    def custom_transition_fragment_state(fragment_id: int, action: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Transition an Emails 2.0 fragment's approval state (Asset v2). action is
        e.g. approve, unapprove, or discard (discard draft). Requires the
        Emails 2.0 experience to be enabled on the instance."""
        return _call(mf.transitionFragmentState, fragment_id, action)

    @mcp.tool()
    def custom_get_fragment_used_by(fragment_id: int, page_index: int = None,
                                    page_size: int = None, type: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List assets that use an Emails 2.0 fragment (Asset v2 usedby). Requires
        the Emails 2.0 experience to be enabled on the instance."""
        # mf.getFragmentUsedBy exposes the Marketo `type` body field as `assetType`.
        return _call(mf.getFragmentUsedBy, fragment_id, page_index, page_size, type)

    # ========================================================================
    # User Management
    # ========================================================================

    @mcp.tool()
    def custom_list_users(page_size: int = None, page_offset: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List all users on the instance (User Management API). Requires an API
        role with the "Access User Management" permission."""
        return _call(mf.listUsers, page_size, page_offset)

    @mcp.tool()
    def custom_get_user_by_id(user_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a user by id (the user's email-format id, e.g. jane@acme.com)
        (User Management API). Requires an API role with the "Access User
        Management" permission."""
        return _call(mf.getUserById, user_id)

    @mcp.tool()
    def custom_list_user_roles() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List all user roles defined on the instance (User Management API).
        Requires an API role with the "Access User Management" permission."""
        return _call(mf.listUserRoles)

    @mcp.tool()
    def custom_list_workspaces() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List all workspaces on the instance (User Management API). Requires an
        API role with the "Access User Management" permission."""
        return _call(mf.listWorkspaces)

    @mcp.tool()
    def custom_get_user_roles(user_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the role/workspace assignments for a user (id is the user's
        email-format id) (User Management API). Requires an API role with the
        "Access User Management" permission."""
        return _call(mf.getUserRoles, user_id)

    @mcp.tool()
    def custom_add_user_roles(user_id: str, role_workspaces: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Add role/workspace assignments to a user (User Management API).
        role_workspaces is a list of {"accessRoleId": int, "workspaceId": int}
        dicts. Requires an API role with the "Access User Management"
        permission."""
        return _call(mf.addUserRoles, user_id, role_workspaces)

    @mcp.tool()
    def custom_remove_user_roles(user_id: str, role_workspaces: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Remove role/workspace assignments from a user (User Management API).
        role_workspaces is a list of {"accessRoleId": int, "workspaceId": int}
        dicts. Requires an API role with the "Access User Management"
        permission."""
        return _call(mf.removeUserRoles, user_id, role_workspaces)

    @mcp.tool()
    def custom_invite_user(email_address: str, first_name: str, last_name: str,
                           user_role_workspaces: list, api_only: bool = None,
                           expires_at: str = None, reason: str = None,
                           userid: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Invite a new user to the instance (User Management API).
        user_role_workspaces is a list of {"accessRoleId": int,
        "workspaceId": int} dicts; expires_at is an ISO 8601 datetime; set
        api_only=True for an API-only user. Requires an API role with the
        "Access User Management" permission."""
        return _call(mf.inviteUser, email_address, first_name, last_name,
                     user_role_workspaces, api_only, expires_at, reason, userid)

    @mcp.tool()
    def custom_get_user_invite(user_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the pending invite status for a user (id is the user's email-format
        id) (User Management API). Requires an API role with the "Access User
        Management" permission."""
        return _call(mf.getUserInvite, user_id)

    @mcp.tool()
    def custom_delete_user_invite(user_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete (revoke) a pending user invite (id is the user's email-format
        id) (User Management API). Requires an API role with the "Access User
        Management" permission."""
        return _call(mf.deleteUserInvite, user_id)

    @mcp.tool()
    def custom_update_user(user_id: str, first_name: str = None, last_name: str = None,
                           email_address: str = None, api_only: bool = None,
                           expires_at: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a user's attributes (id is the user's email-format id):
        firstName, lastName, emailAddress, apiOnly and/or expiresAt
        (User Management API). Requires an API role with the "Access User
        Management" permission."""
        return _call(mf.updateUser, user_id, first_name, last_name,
                     email_address, api_only, expires_at)

    @mcp.tool()
    def custom_delete_user(user_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a user from the instance (id is the user's email-format id)
        (User Management API). Requires an API role with the "Access User
        Management" permission."""
        return _call(mf.deleteUser, user_id)
