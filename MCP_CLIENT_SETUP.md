# Marketo MCP Server - Client Setup Guide

Your Marketo MCP server is now ready! Here's how to configure it with different MCP clients.

## ✅ Server Status
- **Authentication**: ✅ Working
- **Activities API**: ✅ Working  
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

## 📋 Available Resources

Once connected, your MCP client can access:

- **`marketo://activities/{lead_id}`** - Fetch lead activities
  - Example: `marketo://activities/12345`
  - Returns activities from the last 7 days

## 🧪 Testing the Connection

1. **Start the server**:
   ```bash
   fastmcp run server.py
   ```

2. **In your MCP client**, try requesting:
   ```
   marketo://activities/12345
   ```

3. **Expected response**: JSON with Marketo activities data

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

1. **Test with a real lead ID** from your Marketo instance
2. **Add more resources** (leads, campaigns, etc.)
3. **Implement additional Marketo API endpoints**
4. **Add error handling and retry logic**

Your Marketo MCP server is now ready for production use! 🎉
