# Marketo MCP Server

An MCP (Model Context Protocol) server that exposes Adobe Marketo REST API operations as tools. Built with [FastMCP](https://github.com/jlowin/fastmcp), it allows AI assistants and MCP clients to interact with your Marketo instance.

## Prerequisites

- Python 3.10+
- A Marketo instance with API access (client ID, client secret, and REST API base URL)

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd MarketoMCP
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the template and fill in your Marketo API credentials:

```bash
cp .env_template .env
```

Edit `.env` with your values:

```
MARKETO_CLIENT_ID="your-client-id"
MARKETO_CLIENT_SECRET="your-client-secret"
MARKETO_BASE_URL="https://your-instance.mktorest.com"
```

You can find these in **Marketo Admin > LaunchPoint** (for client ID/secret) and **Admin > Web Services** (for the REST API base URL).

### 4. Start the server

```bash
python mcp_server.py
```

The server starts on `http://0.0.0.0:8000` using the Streamable HTTP transport. The MCP endpoint is available at `http://localhost:8000/mcp`.

## Available Tools

### Activities

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_activity_types` | Get all available activity types | — |
| `get_lead_activities` | Get recent activities for a lead by ID | `lead_id`, `activity_type_ids?`, `days_back?` (default: 7) |
| `get_lead_activities_by_email` | Get recent activities for a lead by email | `email`, `activity_type_ids?`, `days_back?` (default: 7) |
| `get_lead_changes` | Get data value changes for a lead | `lead_id`, `fields?`, `days_back?` (default: 7) |

### Leads

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_lead_by_email` | Look up a lead by email address | `email` |
| `describe_leads` | Get lead field metadata and schema | — |

### Emails

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_email_by_id` | Get an email asset by ID | `email_id` |
| `get_email_by_name` | Get an email asset by name | `name`, `folder_id?` |
| `browse_emails` | Browse email assets with filtering | `max_return?`, `offset?`, `status?`, `folder_id?`, `earliest_updated_at?`, `latest_updated_at?` |
| `get_email_content` | Get content sections of an email | `email_id`, `status?` |
| `get_email_cc_fields` | Get fields enabled for Email CC | — |
| `preview_email` | Get a live preview of an email | `email_id`, `status?`, `content_type?`, `lead_id?` |

### Channels

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_channels` | Get available program channels | `max_return?`, `offset?` |

### Folders

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_folder_by_name` | Get a folder by name | `name` |
| `browse_folders` | Browse folders | `max_return?`, `offset?`, `folder_type?` |

### Smart Campaigns

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_smart_campaign_by_id` | Get a smart campaign by ID | `campaign_id` |
| `get_smart_campaign_by_name` | Get a smart campaign by name | `name` |
| `browse_smart_campaigns` | Browse smart campaigns with filtering | `max_return?`, `offset?`, `is_active?`, `folder_id?`, `earliest_updated_at?`, `latest_updated_at?` |
| `create_smart_campaign` | Create a new smart campaign | `name`, `folder_id`, `description?` |
| `update_smart_campaign` | Update an existing smart campaign | `campaign_id`, `name?`, `description?`, `folder_id?` |
| `clone_smart_campaign` | Clone a smart campaign | `campaign_id`, `name`, `folder_id`, `description?` |
| `schedule_batch_campaign` | Schedule a batch campaign to run | `campaign_id`, `run_at?`, `tokens?`, `clone_to_program?` |
| `request_campaign` | Trigger a campaign for specific leads | `campaign_id`, `lead_ids?`, `tokens?` |
| `activate_smart_campaign` | Activate a smart campaign | `campaign_id` |
| `deactivate_smart_campaign` | Deactivate a smart campaign | `campaign_id` |
| `delete_smart_campaign` | Delete a smart campaign | `campaign_id` |

### Programs

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_program_by_id` | Get a program by ID | `program_id` |
| `get_program_by_name` | Get a program by name | `name`, `include_tags?`, `include_costs?` |
| `browse_programs` | Browse programs with filtering | `max_return?`, `offset?`, `status?`, `earliest_updated_at?`, `latest_updated_at?` |
| `create_program` | Create a new program | `name`, `folder_id`, `program_type`, `channel`, `description?`, `costs?`, `tags?`, `start_date?`, `end_date?` |
| `update_program` | Update an existing program | `program_id`, `name?`, `description?`, `costs?`, `costs_destructive_update?`, `tags?`, `start_date?`, `end_date?` |
| `clone_program` | Clone a program | `program_id`, `name`, `folder_id`, `description?` |
| `approve_email_program` | Approve an email program | `program_id` |
| `unapprove_email_program` | Unapprove an email program | `program_id` |
| `delete_program` | Delete a program and all child contents | `program_id` |

### Program Members

| Tool | Description | Parameters |
|------|-------------|------------|
| `describe_program_members` | Get program member field metadata | — |
| `query_program_members` | Query program members with filtering | `program_id`, `filter_type`, `filter_values`, `fields?`, `start_at?`, `end_at?` |

### Tokens

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_tokens_by_folder` | Get tokens for a folder | `folder_id`, `folder_type?` |
| `create_token` | Create a new token | `folder_id`, `name`, `token_type`, `value`, `folder_type?` |
| `update_token` | Update an existing token | `folder_id`, `name`, `token_type`, `value`, `folder_type?` |
| `delete_token` | Delete a token | `folder_id`, `name`, `token_type`, `folder_type?` |

> Parameters marked with `?` are optional.

## Testing

Two test suites are provided — one tests the Marketo functions directly, the other tests through the MCP server protocol.

### Test the underlying functions directly

This calls `marketo_functions.py` without the MCP layer. Requires a valid `.env` configuration.

```bash
python test_marketo_functions.py
```

### Test via the MCP server

This connects to the running MCP server as an MCP client. Start the server first, then run the tests in a separate terminal.

```bash
# Terminal 1 - start the server
python mcp_server.py

# Terminal 2 - run the tests
python test_mcp_server.py
```

### Test modes

Both test scripts offer three modes when run:

1. **Read-only tests** — Safe, no modifications to your Marketo instance. Browses emails, campaigns, programs, folders, and looks up leads.
2. **Write-only tests** — Creates, updates, clones, and deletes test assets (prefixed with `MCPTEST_`). Prompts for confirmation before destructive operations. Offers cleanup at the end.
3. **Full tests** — Runs read-only tests followed by write tests.

### Test configuration

Test inputs (email addresses, folder IDs, campaign names, etc.) are saved to `test_config.json` after the first run so you don't have to re-enter them. Delete or edit this file to reset test inputs.

## Project Structure

```
MarketoMCP/
├── mcp_server.py               # MCP server — registers tools with FastMCP
├── marketo_functions.py         # Marketo REST API wrapper functions
├── test_mcp_server.py           # MCP protocol-level test suite
├── test_marketo_functions.py    # Direct function test suite
├── test_config.json             # Saved test inputs (auto-generated)
├── requirements.txt             # Python dependencies
├── .env_template                # Environment variable template
└── .env                         # Your credentials (not committed)
```
