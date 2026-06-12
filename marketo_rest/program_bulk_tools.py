"""
Custom MCP tools for Marketo program members, bulk import/export, and usage stats.

Covers the gaps in Adobe's native Marketo MCP server:
- Program member sync/status/delete and program-member field schema management
- Bulk lead export job management (list/cancel — native covers create/enqueue/status/file)
- Bulk activity, program member, and custom object export (full job lifecycle)
- Bulk custom object and program member import (CSV upload + status/failures/warnings)
- Daily/weekly API usage and error stats

All names carry a `custom_` prefix and descriptions start with [CUSTOM] so
clients can tell at a glance whether a call goes through Adobe's native MCP
(unprefixed) or directly to the Marketo REST API (custom_*).
"""

from fastmcp import FastMCP

import marketo_functions as mf
from marketo_rest.bridge import invoke


def register(mcp: FastMCP, creds_provider=None):
    def _call(fn, *args, **kwargs):
        return invoke(creds_provider, fn, *args, **kwargs)

    # ========================================================================
    # Program members
    # ========================================================================

    @mcp.tool()
    def custom_sync_program_member_data(program_id: int, members: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update custom program-member field values for leads in a program. Each
        member is a dict containing leadId plus program-member field values,
        e.g. {"leadId": 123, "registrationCode": "abc"}. The leads must already
        be members of the program. Max 300 members per call."""
        return _call(mf.syncProgramMemberData, program_id, members)

    @mcp.tool()
    def custom_sync_program_member_status(program_id: int, status_name: str,
                                          lead_ids: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Set the program membership status (by status name, e.g. 'Registered')
        for a list of lead IDs. Adds the leads to the program if they are not
        already members. Max 300 lead IDs per call."""
        return _call(mf.syncProgramMemberStatus, program_id, status_name, lead_ids)

    @mcp.tool()
    def custom_delete_program_members(program_id: int, lead_ids: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Remove leads from a program (deletes their program membership records).
        Max 300 lead IDs per call."""
        return _call(mf.deleteProgramMembers, program_id, lead_ids)

    @mcp.tool()
    def custom_create_program_member_fields(fields: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create custom program-member fields. Each field is a dict with
        displayName, name (API name), dataType (e.g. string, integer, date,
        boolean), and optional description."""
        return _call(mf.createProgramMemberFields, fields)

    @mcp.tool()
    def custom_get_program_member_field_by_name(field_api_name: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the metadata for a single program-member field by its API name."""
        return _call(mf.getProgramMemberFieldByName, field_api_name)

    @mcp.tool()
    def custom_update_program_member_field(field_api_name: str, updates: list) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Update a custom program-member field. updates is a list of update dicts
        (e.g. [{"displayName": "New Name"}, {"description": "..."}])."""
        return _call(mf.updateProgramMemberField, field_api_name, updates)

    # ========================================================================
    # Bulk lead export management
    # ========================================================================

    @mcp.tool()
    def custom_list_lead_export_jobs(status: str = None, batch_size: int = None,
                                     next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List bulk lead export jobs. status is an optional comma-separated
        filter of created/queued/processing/canceled/completed/failed."""
        return _call(mf.listLeadExportJobs, status, batch_size, next_page_token)

    @mcp.tool()
    def custom_cancel_lead_export_job(export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Cancel a bulk lead export job."""
        return _call(mf.cancelLeadExportJob, export_id)

    # ========================================================================
    # Bulk activity export
    # ========================================================================

    @mcp.tool()
    def custom_create_activity_export_job(start_at: str, end_at: str,
                                          activity_type_ids: list = None,
                                          fields: list = None, format: str = "CSV",
                                          column_header_names: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create a bulk activity export job filtered by createdAt date range
        (ISO 8601 timestamps, max 31-day range) and optional activity type IDs.
        Returns an exportId — enqueue it with custom_enqueue_activity_export_job."""
        return _call(mf.createActivityExportJob, start_at, end_at,
                     activity_type_ids, fields, format, column_header_names)

    @mcp.tool()
    def custom_enqueue_activity_export_job(export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Enqueue a created bulk activity export job for processing."""
        return _call(mf.enqueueActivityExportJob, export_id)

    @mcp.tool()
    def custom_get_activity_export_job_status(export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the status of a bulk activity export job."""
        return _call(mf.getActivityExportJobStatus, export_id)

    @mcp.tool()
    def custom_get_activity_export_file(export_id: str) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Download the file for a completed bulk activity export job (returns
        CSV/TSV text)."""
        return _call(mf.getActivityExportFile, export_id)

    @mcp.tool()
    def custom_cancel_activity_export_job(export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Cancel a bulk activity export job."""
        return _call(mf.cancelActivityExportJob, export_id)

    @mcp.tool()
    def custom_list_activity_export_jobs(status: str = None, batch_size: int = None,
                                         next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List bulk activity export jobs. status is an optional comma-separated
        filter of created/queued/processing/canceled/completed/failed."""
        return _call(mf.listActivityExportJobs, status, batch_size,
                     next_page_token)

    # ========================================================================
    # Bulk program member export
    # ========================================================================

    @mcp.tool()
    def custom_create_program_member_export_job(fields: list, program_id: int,
                                                format: str = "CSV",
                                                column_header_names: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create a bulk program member export job for a program. fields is the
        required list of field API names to export. Returns an exportId —
        enqueue it with custom_enqueue_program_member_export_job."""
        return _call(mf.createProgramMemberExportJob, fields, program_id,
                     format, column_header_names)

    @mcp.tool()
    def custom_enqueue_program_member_export_job(export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Enqueue a created bulk program member export job for processing."""
        return _call(mf.enqueueProgramMemberExportJob, export_id)

    @mcp.tool()
    def custom_get_program_member_export_job_status(export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the status of a bulk program member export job."""
        return _call(mf.getProgramMemberExportJobStatus, export_id)

    @mcp.tool()
    def custom_get_program_member_export_file(export_id: str) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Download the file for a completed bulk program member export job
        (returns CSV/TSV text)."""
        return _call(mf.getProgramMemberExportFile, export_id)

    @mcp.tool()
    def custom_cancel_program_member_export_job(export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Cancel a bulk program member export job."""
        return _call(mf.cancelProgramMemberExportJob, export_id)

    @mcp.tool()
    def custom_list_program_member_export_jobs(status: str = None, batch_size: int = None,
                                               next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List bulk program member export jobs. status is an optional
        comma-separated filter of created/queued/processing/canceled/
        completed/failed."""
        return _call(mf.listProgramMemberExportJobs, status, batch_size,
                     next_page_token)

    # ========================================================================
    # Bulk custom object export
    # ========================================================================

    @mcp.tool()
    def custom_create_custom_object_export_job(object_api_name: str, fields: list,
                                               filter: dict, format: str = "CSV",
                                               column_header_names: dict = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Create a bulk export job for a custom object. fields is the list of
        field API names to export. filter is a dict such as
        {"updatedAt": {"startAt": "...", "endAt": "..."}}, {"staticListId": N},
        or {"smartListId": N}. Returns an exportId — enqueue it with
        custom_enqueue_custom_object_export_job."""
        return _call(mf.createCustomObjectExportJob, object_api_name, fields,
                     filter, format, column_header_names)

    @mcp.tool()
    def custom_enqueue_custom_object_export_job(object_api_name: str, export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Enqueue a created bulk custom object export job for processing."""
        return _call(mf.enqueueCustomObjectExportJob, object_api_name, export_id)

    @mcp.tool()
    def custom_get_custom_object_export_job_status(object_api_name: str, export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the status of a bulk custom object export job."""
        return _call(mf.getCustomObjectExportJobStatus, object_api_name, export_id)

    @mcp.tool()
    def custom_get_custom_object_export_file(object_api_name: str, export_id: str) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Download the file for a completed bulk custom object export job
        (returns CSV/TSV text)."""
        return _call(mf.getCustomObjectExportFile, object_api_name, export_id)

    @mcp.tool()
    def custom_cancel_custom_object_export_job(object_api_name: str, export_id: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Cancel a bulk custom object export job."""
        return _call(mf.cancelCustomObjectExportJob, object_api_name, export_id)

    @mcp.tool()
    def custom_list_custom_object_export_jobs(object_api_name: str, status: str = None,
                                              batch_size: int = None,
                                              next_page_token: str = None) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        List bulk export jobs for a custom object. status is an optional
        comma-separated filter of created/queued/processing/canceled/
        completed/failed."""
        return _call(mf.listCustomObjectExportJobs, object_api_name, status,
                     batch_size, next_page_token)

    # ========================================================================
    # Bulk custom object import
    # ========================================================================

    @mcp.tool()
    def custom_import_custom_objects_csv(object_api_name: str, csv_content: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Start a bulk custom object import from CSV content (first row = field
        API names, including the dedupe/link fields). Returns a batchId — check
        progress with custom_get_custom_object_import_status. Max 10MB."""
        return _call(mf.importCustomObjectsCsv, object_api_name, csv_content)

    @mcp.tool()
    def custom_get_custom_object_import_status(object_api_name: str, batch_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the status of a bulk custom object import batch."""
        return _call(mf.getCustomObjectImportStatus, object_api_name, batch_id)

    @mcp.tool()
    def custom_get_custom_object_import_failures(object_api_name: str, batch_id: int) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the failures file for a bulk custom object import batch (returns
        CSV text)."""
        return _call(mf.getCustomObjectImportFailures, object_api_name, batch_id)

    @mcp.tool()
    def custom_get_custom_object_import_warnings(object_api_name: str, batch_id: int) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the warnings file for a bulk custom object import batch (returns
        CSV text)."""
        return _call(mf.getCustomObjectImportWarnings, object_api_name, batch_id)

    # ========================================================================
    # Bulk program member import
    # ========================================================================

    @mcp.tool()
    def custom_import_program_members_csv(program_id: int, program_member_status: str,
                                          csv_content: str) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Start a bulk program member import from CSV content (first row = field
        API names, e.g. 'email,firstName'). New leads are created and all rows
        are added to the program with the given program_member_status. Returns
        a batchId — check progress with custom_get_program_member_import_status.
        Max 10MB."""
        return _call(mf.importProgramMembersCsv, program_id,
                     program_member_status, csv_content)

    @mcp.tool()
    def custom_get_program_member_import_status(batch_id: int) -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the status of a bulk program member import batch."""
        return _call(mf.getProgramMemberImportStatus, batch_id)

    @mcp.tool()
    def custom_get_program_member_import_failures(batch_id: int) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the failures file for a bulk program member import batch (returns
        CSV text)."""
        return _call(mf.getProgramMemberImportFailures, batch_id)

    @mcp.tool()
    def custom_get_program_member_import_warnings(batch_id: int) -> str:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get the warnings file for a bulk program member import batch (returns
        CSV text)."""
        return _call(mf.getProgramMemberImportWarnings, batch_id)

    # ========================================================================
    # Usage / error stats
    # ========================================================================

    @mcp.tool()
    def custom_get_daily_usage() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get today's API usage (call counts per user) for the instance."""
        return _call(mf.getDailyUsage)

    @mcp.tool()
    def custom_get_weekly_usage() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get API usage (call counts per user) for the past 7 days."""
        return _call(mf.getWeeklyUsage)

    @mcp.tool()
    def custom_get_daily_errors() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get today's API error counts (by error code) for the instance."""
        return _call(mf.getDailyErrors)

    @mcp.tool()
    def custom_get_weekly_errors() -> dict:
        """[CUSTOM] Calls the Marketo REST API directly (not Adobe's native MCP).
        Get API error counts (by error code) for the past 7 days."""
        return _call(mf.getWeeklyErrors)
