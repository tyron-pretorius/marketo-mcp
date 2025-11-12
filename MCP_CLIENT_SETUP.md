# Marketo MCP Server - Client Setup Guide

Your Marketo MCP server is now ready! This comprehensive server provides 36+ tools for managing leads, campaigns, programs, emails, and more in Adobe Marketo Engage.

## ✅ Server Status
- **Authentication**: ✅ Working
- **Lead Management**: ✅ Working  
- **Campaign Management**: ✅ Working
- **Program Management**: ✅ Working
- **Email Asset Management**: ✅ Working
- **Token Management**: ✅ Working
- **MCP Protocol**: ✅ Working
- **FastMCP Server**: ✅ Ready

## 🚀 Starting the Server

### Method 1: Direct FastMCP Command
```bash
fastmcp run server.py
```

### Method 2: Python Script
```bash
python server.py --server
```

## 📱 MCP Client Configuration

### For Cursor IDE

1. **Open Cursor Settings**
   - Go to `Cursor > Preferences` (or `Cmd/Ctrl + ,`)

2. **Find MCP Configuration**
   - Look for "MCP" or "Model Context Protocol" settings

3. **Add Server Configuration**
   ```json
   {
     "mcpServers": {
       "marketo": {
         "command": "fastmcp",
         "args": ["run", "server.py"],
         "cwd": "/path/to/your/MarketoMCP"
       }
     }
   }
   ```

### For Claude Desktop

1. **Edit Configuration File**
   - Open `~/.config/claude-desktop/config.json`

2. **Add Marketo Server**
   ```json
   {
     "mcpServers": {
       "marketo": {
         "command": "fastmcp",
         "args": ["run", "server.py"],
         "cwd": "/Users/inflection/Documents/MarketoMCP"
       }
     }
   }
   ```

### For Other MCP Clients

Most MCP clients follow a similar pattern:

```json
{
  "mcpServers": {
    "marketo": {
      "command": "fastmcp",
      "args": ["run", "server.py"],
      "cwd": "/path/to/your/MarketoMCP/directory"
    }
  }
}
```

## 🔧 Environment Variables

Make sure these are set in your environment or `.env` file:

```bash
MARKETO_CLIENT_ID=your_client_id
MARKETO_CLIENT_SECRET=your_client_secret
MARKETO_BASE_URL=https://019-OIW-252.mktorest.com
```

## 📋 Available Tools

Once connected, your MCP client can access 36+ tools organized into these categories:

### Lead Management (5 tools)
- `get_lead_by_email` - Get lead by email address
- `get_lead_activities` - Get lead activities by ID
- `get_lead_activities_by_email` - Get lead activities by email
- `get_lead_changes` - Get lead data changes
- `describe_leads` - Get lead field schema

### Email Asset Management (6 tools)
- `get_email_by_id` - Get email by ID
- `get_email_by_name` - Get email by name
- `browse_emails` - Browse email assets
- `get_email_content` - Get email content
- `get_email_cc_fields` - Get CC fields
- `preview_email` - Preview email content

### Smart Campaign Management (10 tools)
- `get_smart_campaign_by_id` - Get campaign by ID
- `get_smart_campaign_by_name` - Get campaign by name
- `browse_smart_campaigns` - Browse campaigns
- `create_smart_campaign` - Create campaign
- `update_smart_campaign` - Update campaign
- `clone_smart_campaign` - Clone campaign
- `schedule_batch_campaign` - Schedule batch campaign
- `trigger_campaign` - Trigger campaign
- `activate_smart_campaign` - Activate campaign
- `deactivate_smart_campaign` - Deactivate campaign

### Program Management (8 tools)
- `get_program_by_id` - Get program by ID
- `get_program_by_name` - Get program by name
- `browse_programs` - Browse programs
- `create_program` - Create program
- `update_program` - Update program
- `clone_program` - Clone program
- `approve_email_program` - Approve program
- `unapprove_email_program` - Unapprove program

### Program Members (2 tools)
- `describe_program_members` - Get member schema
- `query_program_members` - Query program members

### Token Management (3 tools)
- `get_tokens_by_folder` - Get tokens by folder
- `create_token` - Create token
- `update_token` - Update token

### Other Tools (2 tools)
- `get_activity_types` - Get activity types
- `browse_folders` - Browse folders

## 🧪 Testing the Connection

1. **Start the server**:
   ```bash
   fastmcp run server.py
   ```

2. **In your MCP client**, try these example requests:
   ```
   get_lead_by_email("user@example.com")
   get_activity_types()
   browse_emails(max_return=10)
   browse_folders(max_return=5)
   ```

3. **Expected responses**: JSON data from Marketo API

## 🔍 Troubleshooting

### Server won't start
- Check environment variables are set
- Verify Python 3.12+ is installed
- Ensure all dependencies are installed: `pip install -r requirements.txt`

### Authentication fails
- Verify your Marketo credentials
- Check the base URL format (should end with `.mktorest.com`)
- Ensure your LaunchPoint app has the correct permissions

### MCP client can't connect
- Verify the server is running
- Check the `cwd` path in your client configuration
- Ensure the `fastmcp` command is available in your PATH

## 📚 Next Steps

1. **Test with real data** from your Marketo instance
2. **Explore folder structure** using `browse_folders` to find valid folder IDs
3. **Create test campaigns** using `create_smart_campaign`
4. **Manage email assets** using the email management tools
5. **Set up program workflows** using program management tools
6. **Implement token management** for dynamic content

## 🎯 Common Use Cases

- **Lead Management**: Track lead activities and changes
- **Campaign Automation**: Create and manage smart campaigns
- **Email Marketing**: Browse, create, and preview email assets
- **Program Management**: Set up and manage marketing programs
- **Token Management**: Create dynamic content tokens
- **Data Analysis**: Query program members and lead data

Your Marketo MCP server is now ready for production use! 🎉
