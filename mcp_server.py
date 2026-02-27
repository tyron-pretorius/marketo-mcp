"""
MCP Server that exposes Marketo functions as tools.
"""

from fastmcp import FastMCP
import marketo_functions

# Create the MCP server
mcp = FastMCP("MarketoMCPServer")

# ============================================================================
# Activity Tools
# ============================================================================

@mcp.tool()
def get_activity_types() -> dict:
    """Get available activity types from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getActivityTypes(token)
    return result

@mcp.tool()
def get_lead_activities(lead_id: int, activity_type_ids: list = None, days_back: int = 7) -> dict:
    """Get recent activities for a lead from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getLeadActivities(token, lead_id, activity_type_ids, days_back)
    return result

@mcp.tool()
def get_lead_activities_by_email(email: str, activity_type_ids: list = None, days_back: int = 7) -> dict:
    """Get recent activities for a lead by email address from Marketo."""
    token = marketo_functions.getToken()
    lead_data = marketo_functions.lookupLead(token, "email", email)
    leads = lead_data.get("result", [])
    if not leads:
        return {"error": f"No lead found with email: {email}"}
    lead_id = leads[0].get("id")
    result = marketo_functions.getLeadActivities(token, lead_id, activity_type_ids, days_back)
    return result

@mcp.tool()
def get_lead_changes(lead_id: int, fields: list = None, days_back: int = 7) -> dict:
    """Get data value changes for a lead from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getLeadChanges(token, lead_id, fields, days_back)
    return result

# ============================================================================
# Lead Tools
# ============================================================================

@mcp.tool()
def get_lead_by_email(email: str) -> dict:
    """Get a lead by email address from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.lookupLead(token, "email", email)
    return result

@mcp.tool()
def describe_leads() -> dict:
    """Get lead field metadata and schema information from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.describeLeads(token)
    return result

# ============================================================================
# Email Tools
# ============================================================================

@mcp.tool()
def get_email_by_id(email_id: int) -> dict:
    """Get an email asset by its ID from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getEmailById(token, email_id)
    return result

@mcp.tool()
def get_email_by_name(name: str, folder_id: int = None) -> dict:
    """Get an email asset by its name from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getEmailByName(token, name, folder_id)
    return result

@mcp.tool()
def browse_emails(max_return: int = 20, offset: int = 0, status: str = None,
                  folder_id: int = None, earliest_updated_at: str = None,
                  latest_updated_at: str = None) -> dict:
    """Browse email assets in Marketo with optional filtering."""
    token = marketo_functions.getToken()
    result = marketo_functions.browseEmails(token, max_return, offset, status, folder_id,
                                           earliest_updated_at, latest_updated_at)
    return result

@mcp.tool()
def get_email_content(email_id: int, status: str = None) -> dict:
    """Get the content sections of an email asset from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getEmailContent(token, email_id, status)
    return result

@mcp.tool()
def get_email_cc_fields() -> dict:
    """Get the set of fields enabled for Email CC in the Marketo instance."""
    token = marketo_functions.getToken()
    result = marketo_functions.getEmailCcFields(token)
    return result

@mcp.tool()
def preview_email(email_id: int, status: str = None, content_type: str = "HTML",
                  lead_id: int = None) -> dict:
    """Get a live preview of an email as it would be sent to a recipient."""
    token = marketo_functions.getToken()
    result = marketo_functions.previewEmail(token, email_id, status, content_type, lead_id)
    return result

# ============================================================================
# Channel Tools
# ============================================================================

@mcp.tool()
def get_channels(max_return: int = 200, offset: int = 0) -> dict:
    """Get available program channels from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getChannels(token, max_return, offset)
    return result

# ============================================================================
# Folder Tools
# ============================================================================

@mcp.tool()
def get_folder_by_name(name: str) -> dict:
    """Get a folder by its name from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getFolderByName(token, name)
    return result

@mcp.tool()
def browse_folders(max_return: int = 20, offset: int = 0, folder_type: str = "Folder") -> dict:
    """Browse folders in Marketo to find valid folder IDs."""
    token = marketo_functions.getToken()
    result = marketo_functions.browseFolders(token, max_return, offset, folder_type)
    return result

# ============================================================================
# Smart Campaign Tools
# ============================================================================

@mcp.tool()
def get_smart_campaign_by_id(campaign_id: int) -> dict:
    """Get a smart campaign by its ID from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getSmartCampaignById(token, campaign_id)
    return result

@mcp.tool()
def get_smart_campaign_by_name(name: str) -> dict:
    """Get a smart campaign by its name from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getSmartCampaignByName(token, name)
    return result

@mcp.tool()
def browse_smart_campaigns(max_return: int = 20, offset: int = 0, is_active: bool = None,
                           folder_id: int = None, earliest_updated_at: str = None,
                           latest_updated_at: str = None) -> dict:
    """Browse smart campaigns in Marketo with optional filtering."""
    token = marketo_functions.getToken()
    result = marketo_functions.browseSmartCampaigns(token, max_return, offset, is_active,
                                                   folder_id, earliest_updated_at,
                                                   latest_updated_at)
    return result

@mcp.tool()
def create_smart_campaign(name: str, folder_id: int, description: str = None) -> dict:
    """Create a new smart campaign in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.createSmartCampaign(token, name, folder_id, description)
    return result

@mcp.tool()
def update_smart_campaign(campaign_id: int, name: str = None, description: str = None,
                          folder_id: int = None) -> dict:
    """Update an existing smart campaign in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.updateSmartCampaign(token, campaign_id, name, description, folder_id)
    return result

@mcp.tool()
def clone_smart_campaign(campaign_id: int, name: str, folder_id: int,
                         description: str = None) -> dict:
    """Clone an existing smart campaign in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.cloneSmartCampaign(token, campaign_id, name, folder_id, description)
    return result

@mcp.tool()
def schedule_batch_campaign(campaign_id: int, run_at: str = None, tokens: list = None,
                            clone_to_program: str = None) -> dict:
    """Schedule a batch smart campaign to run at a specific time."""
    token = marketo_functions.getToken()
    result = marketo_functions.scheduleBatchCampaign(token, campaign_id, run_at, tokens, clone_to_program)
    return result

@mcp.tool()
def request_campaign(campaign_id: int, lead_ids: list = None, tokens: list = None) -> dict:
    """Request a smart campaign for specific leads."""
    token = marketo_functions.getToken()
    result = marketo_functions.requestCampaign(token, campaign_id, lead_ids, tokens)
    return result

@mcp.tool()
def activate_smart_campaign(campaign_id: int) -> dict:
    """Activate a smart campaign in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.activateSmartCampaign(token, campaign_id)
    return result

@mcp.tool()
def deactivate_smart_campaign(campaign_id: int) -> dict:
    """Deactivate a smart campaign in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.deactivateSmartCampaign(token, campaign_id)
    return result

@mcp.tool()
def delete_smart_campaign(campaign_id: int) -> dict:
    """Delete a smart campaign in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.deleteSmartCampaign(token, campaign_id)
    return result

# ============================================================================
# Program Tools
# ============================================================================

@mcp.tool()
def get_program_by_id(program_id: int) -> dict:
    """Get a program by its ID from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getProgramById(token, program_id)
    return result

@mcp.tool()
def get_program_by_name(name: str, include_tags: bool = False, include_costs: bool = False) -> dict:
    """Get a program by its name from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getProgramByName(token, name, include_tags, include_costs)
    return result

@mcp.tool()
def browse_programs(max_return: int = 20, offset: int = 0, status: str = None,
                    earliest_updated_at: str = None, latest_updated_at: str = None) -> dict:
    """Browse programs in Marketo with optional filtering."""
    token = marketo_functions.getToken()
    result = marketo_functions.browsePrograms(token, max_return, offset, status,
                                             earliest_updated_at, latest_updated_at)
    return result

@mcp.tool()
def create_program(name: str, folder_id: int, program_type: str, channel: str,
                   description: str = None, costs: list = None, tags: list = None,
                   start_date: str = None, end_date: str = None) -> dict:
    """Create a new program in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.createProgram(token, name, folder_id, program_type, channel,
                                            description, costs, tags, start_date, end_date)
    return result

@mcp.tool()
def update_program(program_id: int, name: str = None, description: str = None,
                   costs: list = None, costs_destructive_update: bool = False,
                   tags: list = None, start_date: str = None, end_date: str = None) -> dict:
    """Update an existing program in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.updateProgram(token, program_id, name, description, costs,
                                            costs_destructive_update, tags, start_date, end_date)
    return result

@mcp.tool()
def clone_program(program_id: int, name: str, folder_id: int,
                  description: str = None) -> dict:
    """Clone an existing program in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.cloneProgram(token, program_id, name, folder_id, description)
    return result

@mcp.tool()
def approve_email_program(program_id: int) -> dict:
    """Approve an Email Program in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.approveEmailProgram(token, program_id)
    return result

@mcp.tool()
def unapprove_email_program(program_id: int) -> dict:
    """Unapprove an Email Program in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.unapproveEmailProgram(token, program_id)
    return result

@mcp.tool()
def delete_program(program_id: int) -> dict:
    """Delete a program and all its child contents in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.deleteProgram(token, program_id)
    return result

# ============================================================================
# Program Member Tools
# ============================================================================

@mcp.tool()
def describe_program_members() -> dict:
    """Get program member field metadata and schema information from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.describeProgramMembers(token)
    return result

@mcp.tool()
def query_program_members(program_id: int, filter_type: str, filter_values: str,
                          fields: str = None, start_at: str = None,
                          end_at: str = None) -> dict:
    """Query program members from Marketo with filtering options."""
    token = marketo_functions.getToken()
    result = marketo_functions.queryProgramMembers(token, program_id, filter_type, filter_values,
                                                  fields, start_at, end_at)
    return result

# ============================================================================
# Token Management Tools
# ============================================================================

@mcp.tool()
def get_tokens_by_folder(folder_id: int, folder_type: str = "Folder") -> dict:
    """Get tokens by folder ID from Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.getTokensByFolder(token, folder_id, folder_type)
    return result

@mcp.tool()
def create_token(folder_id: int, name: str, token_type: str, value: str,
                 folder_type: str = "Folder") -> dict:
    """Create a new token in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.createToken(token, folder_id, name, token_type, value, folder_type)
    return result

@mcp.tool()
def update_token(folder_id: int, name: str, token_type: str, value: str,
                 folder_type: str = "Folder") -> dict:
    """Update an existing token in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.updateToken(token, folder_id, name, token_type, value, folder_type)
    return result

@mcp.tool()
def delete_token(folder_id: int, name: str, token_type: str,
                 folder_type: str = "Folder") -> dict:
    """Delete a token from a folder or program in Marketo."""
    token = marketo_functions.getToken()
    result = marketo_functions.deleteToken(token, folder_id, name, token_type, folder_type)
    return result

# ============================================================================
# Run the server
# ============================================================================

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
