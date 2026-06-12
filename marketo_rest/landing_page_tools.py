"""
Custom MCP tools for Marketo landing page gaps, landing page templates,
redirect rules/domains, segmentation, form gaps, and remaining asset deletes.

Tool bodies delegate to the single-source API library (marketo_functions.py)
through marketo_rest.bridge.invoke, which resolves credentials, takes a cached
token, routes to the right instance, and retries once on 601/602.
Browse/get/update landing page tools that already exist in custom_tools.py are
intentionally NOT recreated here.
"""

import json

from fastmcp import FastMCP

import marketo_functions as mf
from marketo_rest.bridge import invoke


def register(mcp: FastMCP, creds_provider=None):
    def _call(fn, *args, **kwargs):
        return invoke(creds_provider, fn, *args, **kwargs)

    # ========================================================================
    # Landing pages (gaps)
    # ========================================================================

    @mcp.tool()
    def custom_create_landing_page(name: str, folder_id: int, template_id: int,
                                   folder_type: str = "Folder", description: str = None,
                                   title: str = None, url_page_name: str = None,
                                   mobile_enabled: bool = None, prefill_form: bool = None,
                                   custom_head_html: str = None, facebook_og_tags: str = None,
                                   keywords: str = None, robots: str = None,
                                   workspace: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create a new landing page from a landing page template in the given
        folder. url_page_name sets the page's URL path segment."""
        return _call(mf.createLandingPage, name, folder_id, template_id,
                     folder_type, description, title, url_page_name,
                     mobile_enabled, prefill_form, custom_head_html,
                     facebook_og_tags, keywords, robots, workspace)

    @mcp.tool()
    def custom_clone_landing_page(landing_page_id: int, name: str, folder_id: int,
                                  folder_type: str = "Folder", description: str = None,
                                  template_id: int = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Clone a landing page into the given folder, optionally switching to a
        different landing page template."""
        return _call(mf.cloneLandingPage, landing_page_id, name, folder_id,
                     folder_type, description, template_id)

    @mcp.tool()
    def custom_delete_landing_page(landing_page_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a landing page. The page must be unapproved first (use
        custom_unapprove_landing_page)."""
        return _call(mf.deleteLandingPage, landing_page_id)

    @mcp.tool()
    def custom_add_landing_page_content_section(landing_page_id: int, content_id: str,
                                                content_type: str, value: str = None,
                                                layout: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Add a content section to a landing page draft. content_type is the
        section type (e.g. HTML, RichText, Form, Image, Snippet). layout is an
        optional dict of positioning attributes: left, top, width, height,
        opacity, zIndex, hideDesktop, hideMobile."""
        return _call(mf.addLandingPageContentSection, landing_page_id, content_id,
                     content_type, value, layout)

    @mcp.tool()
    def custom_delete_landing_page_content_section(landing_page_id: int,
                                                   content_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a content section from a landing page draft."""
        return _call(mf.deleteLandingPageContentSection, landing_page_id, content_id)

    @mcp.tool()
    def custom_get_landing_page_dynamic_content(landing_page_id: int,
                                                dynamic_content_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the dynamic content (per-segment variations) of a landing page
        content section."""
        return _call(mf.getLandingPageDynamicContent, landing_page_id,
                     dynamic_content_id)

    @mcp.tool()
    def custom_update_landing_page_dynamic_content(landing_page_id: int,
                                                   dynamic_content_id: str,
                                                   segment: str = None,
                                                   content_type: str = None,
                                                   value: str = None,
                                                   layout: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a segment variation of a dynamic content section on a landing
        page draft. segment is the segment name; layout is an optional dict of
        positioning attributes (left, top, width, height, opacity, zIndex,
        hideDesktop, hideMobile)."""
        return _call(mf.updateLandingPageDynamicContent, landing_page_id,
                     dynamic_content_id, segment, content_type, value, layout)

    @mcp.tool()
    def custom_get_landing_page_variables(landing_page_id: int, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the variables of a landing page built on a guided template."""
        return _call(mf.getLandingPageVariables, landing_page_id, status)

    @mcp.tool()
    def custom_update_landing_page_variable(landing_page_id: int, variable_id: str,
                                            value: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update the value of a guided landing page variable on the page's draft."""
        return _call(mf.updateLandingPageVariable, landing_page_id, variable_id, value)

    # ========================================================================
    # Landing page templates
    # ========================================================================

    @mcp.tool()
    def custom_browse_landing_page_templates(status: str = None, folder_id: int = None,
                                             folder_type: str = "Folder",
                                             max_return: int = 20, offset: int = 0) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Browse landing page templates with optional folder/status filtering."""
        return _call(mf.browseLandingPageTemplates, status, folder_id, folder_type,
                     max_return, offset)

    @mcp.tool()
    def custom_get_landing_page_template_by_id(template_id: int, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a landing page template by its ID."""
        return _call(mf.getLandingPageTemplateById, template_id, status)

    @mcp.tool()
    def custom_get_landing_page_template_by_name(name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a landing page template by its name."""
        return _call(mf.getLandingPageTemplateByName, name)

    @mcp.tool()
    def custom_get_landing_page_template_content(template_id: int, status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the HTML content of a landing page template."""
        return _call(mf.getLandingPageTemplateContent, template_id, status)

    @mcp.tool()
    def custom_create_landing_page_template(name: str, folder_id: int,
                                            folder_type: str = "Folder",
                                            description: str = None,
                                            enable_munchkin: bool = None,
                                            template_type: str = "freeForm") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create a new landing page template. template_type is "freeForm" or
        "guided". Set its HTML afterwards with
        custom_update_landing_page_template_content."""
        return _call(mf.createLandingPageTemplate, name, folder_id, folder_type,
                     description, enable_munchkin, template_type)

    @mcp.tool()
    def custom_update_landing_page_template(template_id: int, name: str = None,
                                            description: str = None,
                                            enable_munchkin: bool = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update landing page template metadata (name, description, Munchkin
        tracking)."""
        return _call(mf.updateLandingPageTemplate, template_id, name, description,
                     enable_munchkin)

    @mcp.tool()
    def custom_update_landing_page_template_content(template_id: int,
                                                    html_content: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Replace the HTML content of a landing page template's draft. Approve
        the draft afterwards to publish."""
        return _call(mf.updateLandingPageTemplateContent, template_id, html_content)

    @mcp.tool()
    def custom_approve_landing_page_template(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Approve a landing page template draft, publishing the changes."""
        return _call(mf.approveLandingPageTemplate, template_id)

    @mcp.tool()
    def custom_unapprove_landing_page_template(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Unapprove a landing page template, reverting it to draft-only."""
        return _call(mf.unapproveLandingPageTemplate, template_id)

    @mcp.tool()
    def custom_discard_landing_page_template_draft(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Discard the draft version of a landing page template."""
        return _call(mf.discardLandingPageTemplateDraft, template_id)

    @mcp.tool()
    def custom_clone_landing_page_template(template_id: int, name: str, folder_id: int,
                                           folder_type: str = "Folder",
                                           description: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Clone a landing page template into the given folder."""
        return _call(mf.cloneLandingPageTemplate, template_id, name, folder_id,
                     folder_type, description)

    @mcp.tool()
    def custom_delete_landing_page_template(template_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a landing page template. Fails if any landing pages still use it."""
        return _call(mf.deleteLandingPageTemplate, template_id)

    # ========================================================================
    # Redirect rules & domains
    # ========================================================================

    @mcp.tool()
    def custom_browse_redirect_rules(redirect_to_path: str = None,
                                     redirect_to_landing_page_id: int = None,
                                     earliest_updated_at: str = None,
                                     latest_updated_at: str = None,
                                     max_return: int = 20, offset: int = 0) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Browse landing page redirect rules with optional filtering by redirect
        target or update-date window (ISO 8601 datetimes)."""
        return _call(mf.browseRedirectRules, redirect_to_path,
                     redirect_to_landing_page_id, earliest_updated_at,
                     latest_updated_at, max_return, offset)

    @mcp.tool()
    def custom_get_redirect_rule_by_id(rule_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get a landing page redirect rule by its ID."""
        return _call(mf.getRedirectRuleById, rule_id)

    @mcp.tool()
    def custom_create_redirect_rule(hostname: str, from_type: str, from_value: str,
                                    to_type: str, to_value: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create a landing page redirect rule. from_type/to_type are
        "landingPageId" or "path"; from_value/to_value are the matching
        landing page ID (as a string) or URL path."""
        return _call(mf.createRedirectRule, hostname, from_type, from_value,
                     to_type, to_value)

    @mcp.tool()
    def custom_update_redirect_rule(rule_id: int, hostname: str = None,
                                    from_type: str = None, from_value: str = None,
                                    to_type: str = None, to_value: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a landing page redirect rule. To change the redirect source or
        target, supply both the type ("landingPageId" or "path") and value."""
        return _call(mf.updateRedirectRule, rule_id, hostname, from_type,
                     from_value, to_type, to_value)

    @mcp.tool()
    def custom_delete_redirect_rule(rule_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a landing page redirect rule."""
        return _call(mf.deleteRedirectRule, rule_id)

    @mcp.tool()
    def custom_get_landing_page_domains(max_return: int = 20, offset: int = 0) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the landing page domains (CNAMEs) configured for the instance."""
        return _call(mf.getLandingPageDomains, max_return, offset)

    # ========================================================================
    # Segmentation
    # ========================================================================

    @mcp.tool()
    def custom_browse_segmentations(status: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Browse the segmentations defined in the instance."""
        return _call(mf.browseSegmentations, status)

    @mcp.tool()
    def custom_get_segments(segmentation_id: int, status: str = None,
                            max_return: int = 20, offset: int = 0) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the segments of a segmentation (use the segment names for dynamic
        content)."""
        return _call(mf.getSegments, segmentation_id, status, max_return, offset)

    # ========================================================================
    # Forms (gaps)
    # ========================================================================

    @mcp.tool()
    def custom_delete_form(form_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a form. The form must not be in use by any landing pages."""
        return _call(mf.deleteForm, form_id)

    @mcp.tool()
    def custom_discard_form_draft(form_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Discard the draft version of a form."""
        return _call(mf.discardFormDraft, form_id)

    @mcp.tool()
    def custom_delete_form_field(form_id: int, field_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a field from a form draft. field_id is the field's API name
        (from get_form_fields)."""
        return _call(mf.deleteFormField, form_id, field_id)

    @mcp.tool()
    def custom_delete_form_fieldset_field(form_id: int, field_set_id: str,
                                          field_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a field from a fieldset on a form draft."""
        return _call(mf.deleteFormFieldsetField, form_id, field_set_id, field_id)

    @mcp.tool()
    def custom_update_form_submit_button(form_id: int, label: str = None,
                                         waiting_label: str = None,
                                         button_position: str = None,
                                         button_style: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update the submit button of a form draft (label, waiting label,
        position, style)."""
        return _call(mf.updateFormSubmitButton, form_id, label, waiting_label,
                     button_position, button_style)

    @mcp.tool()
    def custom_update_form_thank_you_pages(form_id: int, rules: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Replace the thank-you page rules of a form draft. rules is a list of
        rule dicts, e.g. [{"default": true, "followupType": "url",
        "followupValue": "https://example.com/thanks"}]. Exactly one rule
        should have default true."""
        return _call(mf.updateFormThankYouPages, form_id, rules)

    # ========================================================================
    # Remaining asset gaps
    # ========================================================================

    @mcp.tool()
    def custom_clone_smart_campaign(campaign_id: int, name: str, folder_id: int,
                                    folder_type: str = "Folder",
                                    description: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Clone a smart campaign into the given folder (the native MCP has no
        smart campaign clone)."""
        return _call(mf.cloneSmartCampaign, campaign_id, name, folder_id,
                     description, folder_type)

    @mcp.tool()
    def custom_delete_smart_list(smart_list_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a smart list."""
        return _call(mf.deleteSmartList, smart_list_id)

    @mcp.tool()
    def custom_delete_snippet(snippet_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a snippet. The snippet must not be in use by other assets."""
        return _call(mf.deleteSnippet, snippet_id)

    @mcp.tool()
    def custom_discard_snippet_draft(snippet_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Discard the draft version of a snippet."""
        return _call(mf.discardSnippetDraft, snippet_id)

    @mcp.tool()
    def custom_unapprove_snippet(snippet_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Unapprove a snippet, reverting it to draft-only."""
        return _call(mf.unapproveSnippet, snippet_id)

    @mcp.tool()
    def custom_delete_folder(folder_id: int, folder_type: str = "Folder") -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Delete a folder or program shell. folder_type is "Folder" or "Program".
        The folder must be empty."""
        return _call(mf.deleteFolder, folder_id, folder_type)
