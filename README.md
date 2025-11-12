# Marketo MCP Server - Complete Marketo Integration

A comprehensive FastMCP server for integrating with Adobe Marketo Engage's REST API, providing access to leads, activities, campaigns, programs, emails, and more with full Marketo API compliance.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

Set the following environment variables with your Marketo credentials:

```bash
# Your Marketo Client ID from LaunchPoint
export MARKETO_CLIENT_ID="your_client_id_here"

# Your Marketo Client Secret from LaunchPoint  
export MARKETO_CLIENT_SECRET="your_client_secret_here"

# Your Marketo instance base URL (found in Admin > Web Services)
# Format: https://<instance>.mktorest.com
export MARKETO_BASE_URL="https://your-instance.mktorest.com"
```

### 3. Test Authentication

Run the authentication test to verify your credentials:

```bash
python server.py
```

You should see output like:
```
Testing Marketo OAuth Authentication...
INFO:__main__:Attempting to authenticate with Marketo API...
INFO:__main__:Successfully obtained Marketo access token
INFO:__main__:Token expires in 3600 seconds
INFO:__main__:✅ Marketo authentication test PASSED
Authentication successful! Ready to proceed with MCP server setup.
```

## Features

- **OAuth 2.0 Authentication**: Implements 2-legged OAuth with Marketo
- **Lead Management**: Get leads by email, track activities and changes
- **Email Asset Management**: Browse, create, and manage email templates
- **Smart Campaign Management**: Create, update, clone, and manage smart campaigns
- **Program Management**: Full program lifecycle management including approval workflows
- **Token Management**: Create, update, and manage Marketo tokens
- **Folder Management**: Browse and organize Marketo folders
- **Comprehensive API Coverage**: 36+ MCP tools covering all major Marketo operations
- **Environment Variable Security**: All credentials stored securely in environment variables
- **Error Handling**: Comprehensive error handling and logging
- **FastMCP Integration**: Complete MCP server with extensive toolset

## Testing

### 1. Test Authentication and Activities
```bash
python server.py
```

This will test both authentication and lead activities retrieval.

### 2. Start the MCP Server
```bash
python server.py --server
```

This starts the FastMCP server with the Marketo integration.

## MCP Tools

The server provides 36+ MCP tools organized into the following categories:

### Lead Management
- **`get_lead_by_email(email)`** - Get a lead by email address
- **`get_lead_activities(lead_id, activity_type_ids, days_back)`** - Get recent activities for a lead
- **`get_lead_activities_by_email(email, activity_type_ids, days_back)`** - Get lead activities by email
- **`get_lead_changes(lead_id, fields, days_back)`** - Get data value changes for a lead
- **`describe_leads()`** - Get lead field metadata and schema information

### Activity Management
- **`get_activity_types()`** - Get available activity types from Marketo

### Email Asset Management
- **`get_email_by_id(email_id)`** - Get an email asset by its ID
- **`get_email_by_name(name, folder_id)`** - Get an email asset by name
- **`browse_emails(max_return, offset, status, folder_id, etc.)`** - Browse email assets with filtering
- **`get_email_content(email_id, status)`** - Get email content sections
- **`get_email_cc_fields()`** - Get available CC fields
- **`preview_email(email_id, status, content_type, lead_id)`** - Preview email content

### Smart Campaign Management
- **`get_smart_campaign_by_id(campaign_id)`** - Get smart campaign by ID
- **`get_smart_campaign_by_name(name)`** - Get smart campaign by name
- **`browse_smart_campaigns(max_return, offset, is_active, etc.)`** - Browse smart campaigns
- **`create_smart_campaign(name, folder_id, description)`** - Create new smart campaign
- **`update_smart_campaign(campaign_id, name, description, folder_id)`** - Update smart campaign
- **`clone_smart_campaign(campaign_id, name, folder_id, description)`** - Clone smart campaign
- **`schedule_batch_campaign(campaign_id, run_at, tokens, clone_to_program)`** - Schedule batch campaign
- **`trigger_campaign(campaign_id, lead_ids, tokens)`** - Trigger campaign for leads
- **`activate_smart_campaign(campaign_id)`** - Activate smart campaign
- **`deactivate_smart_campaign(campaign_id)`** - Deactivate smart campaign

### Program Management
- **`get_program_by_id(program_id)`** - Get program by ID
- **`get_program_by_name(name, include_tags, include_costs)`** - Get program by name
- **`browse_programs(max_return, offset, status, etc.)`** - Browse programs
- **`create_program(name, folder_id, program_type, channel, etc.)`** - Create new program
- **`update_program(program_id, name, description, costs, etc.)`** - Update program
- **`clone_program(program_id, name, folder_id, description)`** - Clone program
- **`approve_email_program(program_id)`** - Approve email program
- **`unapprove_email_program(program_id)`** - Unapprove email program

### Program Members
- **`describe_program_members()`** - Get program member schema and field metadata
- **`query_program_members(program_id, filter_type, filter_values, fields, start_at, end_at)`** - Query program members

### Token Management
- **`get_tokens_by_folder(folder_id, folder_type)`** - Get tokens by folder or program ID
- **`create_token(folder_id, name, token_type, value, folder_type)`** - Create a new token
- **`update_token(folder_id, name, token_type, value, folder_type)`** - Update an existing token

### Folder Management
- **`browse_folders(max_return, offset, folder_type)`** - Browse folders to find valid folder IDs

## API Endpoints Implemented

- **OAuth Authentication**: 2-legged OAuth 2.0 with Marketo
- **Lead Database API**: Lead retrieval, activities, and field changes
- **Asset API**: Email assets, smart campaigns, programs, folders
- **Campaign API**: Campaign scheduling, triggering, and management
- **Program API**: Program lifecycle management and member queries
- **Token API**: Token creation, updates, and management
- **Activities API**: Activity types and lead activity tracking

## Usage Examples

### 1. Lead Management
```python
# Get a lead by email
lead = get_lead_by_email("user@example.com")

# Get lead activities
activities = get_lead_activities(
    lead_id=12345,
    activity_type_ids=[1, 2, 6],  # Visit Webpage, Fill Form, Send Email
    days_back=7
)

# Get lead changes
changes = get_lead_changes(
    lead_id=12345,
    fields=["firstName", "lastName", "email"],
    days_back=30
)
```

### 2. Email Management
```python
# Browse emails
emails = browse_emails(max_return=20, status="approved")

# Get email content
content = get_email_content(email_id=12345, status="approved")

# Preview email
preview = preview_email(email_id=12345, content_type="HTML", lead_id=67890)
```

### 3. Campaign Management
```python
# Create a smart campaign
campaign = create_smart_campaign(
    name="Welcome Campaign",
    folder_id=123,
    description="New user welcome flow"
)

# Schedule a batch campaign
schedule_batch_campaign(
    campaign_id=456,
    run_at="2024-01-15T10:00:00Z"
)

# Trigger a campaign
trigger_campaign(
    campaign_id=456,
    lead_ids=[12345, 67890]
)
```

### 4. Program Management
```python
# Create a program
program = create_program(
    name="Q1 Campaign",
    folder_id=123,
    program_type="Email",
    channel="Email"
)

# Approve email program
approve_email_program(program_id=789)
```

## Common Activity Type IDs

Based on the [Marketo Activities API documentation](https://experienceleague.adobe.com/en/docs/marketo-developer/marketo/rest/lead-database/activities):

- **1**: Visit Webpage
- **2**: Fill Out Form  
- **6**: Send Email
- **13**: Data Value Change
- **37**: Deleted Lead

## License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0). See the [LICENSE](LICENSE) file for the full license text.

**Copyright © 2025 Inflection.io, Inc**

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
