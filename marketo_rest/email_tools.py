"""
Custom MCP tools for Marketo Asset v1 email gaps, email templates, and files.

EDITOR VERSIONS — every email and email-template tool in this module targets
the Asset *v1* API, which serves Email Editor 1.0 and 2.0 assets (classic,
section- and module-based). They do NOT work on emails built in the new Email
Designer (informally "Editor 3.0", internally "Acrite"), which is block-based
and served by the Asset *v2* API — those are the same tool names WITHOUT the
_legacy suffix, plus the custom_*_fragment tools, in
marketo_rest/v2_admin_tools.py. Calling a tool here
on a Designer email returns 709 "Cannot access content for Acrite Email asset".
File tools are editor-agnostic.

Covers email operations missing from Adobe's native Marketo MCP (update/clone/
delete/unapprove/discard, header + module + dynamic-content + variable editing,
full-content replacement), the entire email template domain, and file
browse/upload/replace. All tools carry the `custom_` prefix and [CUSTOM]
docstring marker so clients can tell they hit the Marketo REST API directly.

Tool bodies delegate to the single-source API library (marketo_functions.py)
through marketo_rest.bridge.invoke, which resolves credentials, takes a cached
token, routes to the right instance, and retries once on 601/602.
"""

from fastmcp import FastMCP

import marketo_functions as mf
from marketo_rest.bridge import invoke


def register(mcp: FastMCP, creds_provider=None):
    def _call(fn, *args, **kwargs):
        return invoke(creds_provider, fn, *args, **kwargs)

    # ========================================================================
    # Emails (Asset v1 gaps)
    # ========================================================================

    @mcp.tool()
    def custom_update_email_legacy(email_id: int, name: str = None, description: str = None,
                            pre_header: str = None, operational: bool = None,
                            published: bool = None, text_only: bool = None,
                            web_view: bool = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Update an email's metadata: name, description, preHeader, and the
        operational/published/textOnly/webView flags. Only provided fields
        are changed."""
        return _call(mf.updateEmail, email_id, name, description, pre_header,
                     operational, published, text_only, web_view)

    @mcp.tool()
    def custom_clone_email_legacy(email_id: int, name: str, folder_id: int,
                           folder_type: str = "Folder", description: str = None,
                           operational: bool = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Clone an email into a folder or program. folder_type is "Folder" or
        "Program"."""
        return _call(mf.cloneEmail, email_id, name, folder_id, folder_type,
                     description, operational)

    @mcp.tool()
    def custom_delete_email_legacy(email_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Delete an email. The email must be unapproved and not in use."""
        return _call(mf.deleteEmail, email_id)

    @mcp.tool()
    def custom_unapprove_email_legacy(email_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Unapprove an email, reverting it to draft-only state. Fails if the
        email is in use by an active asset (e.g. a running campaign)."""
        return _call(mf.unapproveEmail, email_id)

    @mcp.tool()
    def custom_discard_email_draft_legacy(email_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Discard an email's draft version, leaving the approved version
        untouched."""
        return _call(mf.discardEmailDraft, email_id)

    @mcp.tool()
    def custom_update_email_headers_legacy(email_id: int, subject: str = None,
                                    from_name: str = None, from_email: str = None,
                                    reply_to: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Update an email's header fields: subject, fromName, fromEmail, and
        replyTo. Each provided value is sent as a Text-type content JSON
        string. Changes apply to the email's draft."""
        return _call(mf.updateEmailHeaders, email_id, subject, from_name,
                     from_email, reply_to)

    @mcp.tool()
    def custom_rearrange_email_modules_legacy(email_id: int, positions: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Rearrange the modules within an email (modular editor only). positions
        is an ordered list describing the modules, e.g.
        [{"index": 0, "moduleId": "module-a"}, {"index": 1, "moduleId": "module-b"}].
        Changes apply to the email's draft."""
        return _call(mf.rearrangeEmailModules, email_id, positions)

    @mcp.tool()
    def custom_add_email_module_legacy(email_id: int, module_id: str, name: str, index: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Add a copy of an existing module to an email at the given position
        (modular editor only). module_id is the source module to copy, name is
        the new module's name, index is the zero-based insert position."""
        return _call(mf.addEmailModule, email_id, module_id, name, index)

    @mcp.tool()
    def custom_delete_email_module_legacy(email_id: int, module_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Delete a module from an email (modular editor only). Changes apply to
        the email's draft."""
        return _call(mf.deleteEmailModule, email_id, module_id)

    @mcp.tool()
    def custom_duplicate_email_module_legacy(email_id: int, module_id: str, name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Duplicate a module within an email (modular editor only), giving the
        copy the provided name."""
        return _call(mf.duplicateEmailModule, email_id, module_id, name)

    @mcp.tool()
    def custom_rename_email_module_legacy(email_id: int, module_id: str, name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Rename a module within an email (modular editor only)."""
        return _call(mf.renameEmailModule, email_id, module_id, name)

    @mcp.tool()
    def custom_get_email_dynamic_content_legacy(email_id: int, dynamic_content_id: str,
                                         status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Get the dynamic content (per-segment variations) for a dynamic content
        section of an email. status filters by 'approved' or 'draft'."""
        return _call(mf.getEmailDynamicContent, email_id, dynamic_content_id, status)

    @mcp.tool()
    def custom_update_email_dynamic_content_legacy(email_id: int, dynamic_content_id: str,
                                            segment: str, type: str, value: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Update a segment's variation in a dynamic content section of an email.
        segment is the segment name, type is the content type (e.g. 'HTML' or
        'Text'), value is the content. Changes apply to the email's draft."""
        return _call(mf.updateEmailDynamicContent, email_id, dynamic_content_id,
                     segment, type, value)

    @mcp.tool()
    def custom_update_email_full_content_legacy(email_id: int, html_content: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Replace the entire HTML content of an email's draft. Only valid for
        emails NOT using the modular email editor (fullContent rejects
        module-based emails)."""
        return _call(mf.updateEmailFullContent, email_id, html_content)

    @mcp.tool()
    def custom_get_email_variables_legacy(email_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Get the variables defined for an email (modular editor emails based on
        templates with variables)."""
        return _call(mf.getEmailVariables, email_id)

    @mcp.tool()
    def custom_update_email_variable_legacy(email_id: int, variable_name: str, value: str,
                                     module_id: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 EMAILS ONLY — fails with 709 'Acrite Email'
        on new Email Designer assets; drop the _legacy suffix for those]
        Update the value of an email variable. Pass module_id for module-scoped
        variables. Changes apply to the email's draft."""
        return _call(mf.updateEmailVariable, email_id, variable_name, value, module_id)

    # ========================================================================
    # Email templates
    # ========================================================================

    @mcp.tool()
    def custom_browse_email_templates_legacy(status: str = None, max_return: int = 20,
                                      offset: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        List email templates. status filters by 'approved' or 'draft'.
        max_return caps at 200; use offset for paging."""
        return _call(mf.browseEmailTemplates, status, max_return, offset)

    @mcp.tool()
    def custom_get_email_template_by_id_legacy(template_id: int, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Get an email template's metadata by id. status selects the 'approved'
        or 'draft' version."""
        return _call(mf.getEmailTemplateById, template_id, status)

    @mcp.tool()
    def custom_get_email_template_by_name_legacy(name: str, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Get an email template's metadata by exact name. status selects the
        'approved' or 'draft' version."""
        return _call(mf.getEmailTemplateByName, name, status)

    @mcp.tool()
    def custom_get_email_template_content_legacy(template_id: int, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Get an email template's HTML content. status selects the 'approved' or
        'draft' version. Returns the standard JSON envelope with the content."""
        return _call(mf.getEmailTemplateContent, template_id, status)

    @mcp.tool()
    def custom_get_email_template_used_by_legacy(template_id: int, max_return: int = None,
                                          offset: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        List the emails that use an email template."""
        return _call(mf.getEmailTemplateUsedBy, template_id, max_return, offset)

    @mcp.tool()
    def custom_create_email_template_legacy(name: str, folder_id: int, html_content: str,
                                     description: str = None,
                                     folder_type: str = "Folder") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Create a new email template in a folder from HTML content. folder_type
        is "Folder" or "Program"."""
        return _call(mf.createEmailTemplate, name, folder_id, html_content,
                     description, folder_type)

    @mcp.tool()
    def custom_update_email_template_legacy(template_id: int, name: str = None,
                                     description: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Update an email template's name and/or description."""
        return _call(mf.updateEmailTemplate, template_id, name, description)

    @mcp.tool()
    def custom_update_email_template_content_legacy(template_id: int, html_content: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Replace an email template's HTML content. Changes apply to the
        template's draft; approve the draft to make it live."""
        return _call(mf.updateEmailTemplateContent, template_id, html_content)

    @mcp.tool()
    def custom_approve_email_template_legacy(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Approve an email template's draft, making it the live version."""
        return _call(mf.approveEmailTemplate, template_id)

    @mcp.tool()
    def custom_unapprove_email_template_legacy(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Unapprove an email template, reverting it to draft-only state."""
        return _call(mf.unapproveEmailTemplate, template_id)

    @mcp.tool()
    def custom_discard_email_template_draft_legacy(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Discard an email template's draft, leaving the approved version
        untouched."""
        return _call(mf.discardEmailTemplateDraft, template_id)

    @mcp.tool()
    def custom_clone_email_template_legacy(template_id: int, name: str, folder_id: int,
                                    folder_type: str = "Folder",
                                    description: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Clone an email template into a folder. folder_type is "Folder" or
        "Program"."""
        return _call(mf.cloneEmailTemplate, template_id, name, folder_id,
                     folder_type, description)

    @mcp.tool()
    def custom_delete_email_template_legacy(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        [EMAIL EDITOR 1.0/2.0 TEMPLATES ONLY — for new Email Designer
        templates drop the _legacy suffix; its reusable content lives in
        the custom_*_fragment tools, not snippets]
        Delete an email template. The template must be unapproved and not in
        use by any email."""
        return _call(mf.deleteEmailTemplate, template_id)

    # ========================================================================
    # Files
    # ========================================================================

    @mcp.tool()
    def custom_browse_files(folder_id: int = None, folder_type: str = "Folder",
                            max_return: int = None, offset: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List files in the Design Studio, optionally scoped to a folder."""
        return _call(mf.browseFiles, folder_id, folder_type, max_return, offset)

    @mcp.tool()
    def custom_get_file_by_id(file_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a file's metadata (including its public URL) by id."""
        return _call(mf.getFileById, file_id)

    @mcp.tool()
    def custom_get_file_by_name(name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a file's metadata (including its public URL) by exact name."""
        return _call(mf.getFileByName, name)

    @mcp.tool()
    def custom_upload_file(name: str, folder_id: int, file_content: str,
                           file_name: str = None, description: str = None,
                           insert_only: bool = False, is_base64: bool = False,
                           folder_type: str = "Folder") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Upload a file to the Design Studio. file_content is text content; for
        binary files (images, PDFs, etc.) pass base64-encoded content with
        is_base64=True and it will be decoded before upload. file_name defaults
        to name. insert_only=True fails instead of overwriting an existing
        file."""
        return _call(mf.uploadFile, name, folder_id, file_content, file_name,
                     description, insert_only, is_base64, folder_type)

    @mcp.tool()
    def custom_replace_file_content(file_id: int, file_content: str,
                                    file_name: str = None,
                                    is_base64: bool = False) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Replace the content of an existing Design Studio file (the file keeps
        its URL). file_content is text content; for binary files pass
        base64-encoded content with is_base64=True and it will be decoded
        before upload."""
        return _call(mf.replaceFileContent, file_id, file_content, file_name, is_base64)
