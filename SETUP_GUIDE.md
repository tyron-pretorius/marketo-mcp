# Connecting Marketo MCP to Claude

Here's a quick guide to get Claude Desktop connected up to your Marketo MCP server

## **Prerequisites**

Before you start, you'll need your Marketo API credentials:
- **Client ID** and **Client Secret** from Marketo LaunchPoint (Admin > LaunchPoint > View Details)
- **Base URL** from Marketo Admin > Web Services (format: `https://your-instance.mktorest.com`)

## **Step 1: Install Claude Desktop**

1. Head over to the [Claude Desktop download page](https://claude.ai/download)
2. Download and install the Mac/Windows version based on your computer.
3. Once it's installed, sign up with your account.
4. Check things are working, then quit the app.

## **Step 2: Install Python**

Next, you'll need Python:

1. Go to https://python.org/downloads
2. Download the Mac/Windows version based on your computer.
3. Run the installer and follow the instructions.
4. Open Terminal (Mac) or Command Prompt (Windows) and verify Python is installed:
   ```bash
   python3 --version
   ```
   You should see something like `Python 3.8.x` or higher.

## **Step 3: Download and Setup Marketo MCP**

1. Download or clone this repository to your computer (save it to your Documents folder)
2. Open Terminal (Mac) or Command Prompt (Windows) and navigate to the MarketoMCP folder:
   ```bash
   # Mac
   cd /Users/yourusername/Documents/MarketoMCP
   
   # Windows
   cd C:\Users\yourusername\Documents\MarketoMCP
   ```
3. Create a virtual environment and install the required dependencies:
   ```bash
   # Mac
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   
   # Windows
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. Set your Marketo credentials as environment variables and test:
   ```bash
   # Mac
   export MARKETO_CLIENT_ID="your_client_id_here"
   export MARKETO_CLIENT_SECRET="your_client_secret_here"
   export MARKETO_BASE_URL="https://your-instance.mktorest.com"
   python server.py
   
   # Windows
   set MARKETO_CLIENT_ID=your_client_id_here
   set MARKETO_CLIENT_SECRET=your_client_secret_here
   set MARKETO_BASE_URL=https://your-instance.mktorest.com
   python server.py
   ```
   You should see "✅ Marketo authentication test PASSED" if everything is working.

## **Step 4: Update Your Claude Config**

Now let's get Claude set up to talk to the Marketo MCP server.

1. Open Claude Desktop.
2. Go to:
   - **Settings**
   - Find the **Developer** section and click **Edit Config**
3. That'll open a config file in a text editor (TextEdit is fine).
4. In that file, paste this snippet:

**For Mac:**
```json
{
  "mcpServers": {
    "marketo-mcp-server": {
      "command": "/Users/yourusername/Documents/MarketoMCP/venv/bin/fastmcp",
      "args": [
        "run",
        "/Users/yourusername/Documents/MarketoMCP/server.py"
      ],
      "cwd": "/Users/yourusername/Documents/MarketoMCP",
      "env": {
        "MARKETO_CLIENT_ID": "your_client_id_here",
        "MARKETO_CLIENT_SECRET": "your_client_secret_here",
        "MARKETO_BASE_URL": "https://your-instance.mktorest.com",
        "PATH": "/Users/yourusername/Documents/MarketoMCP/venv/bin:/usr/local/bin:/usr/bin:/bin",
        "VIRTUAL_ENV": "/Users/yourusername/Documents/MarketoMCP/venv"
      }
    }
  }
}
```

**For Windows:**
```json
{
  "mcpServers": {
    "marketo-mcp-server": {
      "command": "C:\\Users\\yourusername\\Documents\\MarketoMCP\\venv\\Scripts\\fastmcp.exe",
      "args": [
        "run",
        "C:\\Users\\yourusername\\Documents\\MarketoMCP\\server.py"
      ],
      "cwd": "C:\\Users\\yourusername\\Documents\\MarketoMCP",
      "env": {
        "MARKETO_CLIENT_ID": "your_client_id_here",
        "MARKETO_CLIENT_SECRET": "your_client_secret_here",
        "MARKETO_BASE_URL": "https://your-instance.mktorest.com",
        "PATH": "C:\\Users\\yourusername\\Documents\\MarketoMCP\\venv\\Scripts;C:\\Windows\\System32",
        "VIRTUAL_ENV": "C:\\Users\\yourusername\\Documents\\MarketoMCP\\venv"
      }
    }
  }
}
```

> ✏️ Make sure to **replace the following with your actual information:**
> - `yourusername` with your actual username
> - `your_client_id_here` with your Marketo Client ID
> - `your_client_secret_here` with your Marketo Client Secret  
> - `https://your-instance.mktorest.com` with your actual Marketo Base URL

5. Save the file and close it.
6. Quit Claude and open it again to restart it.

## **Step 5: Test It Out**

1. In Claude, click the little "+" icon (where you'd usually start a new chat).
2. You should see something like **Marketo MCP Server** listed under tools.
3. Try a test prompt like:
   ```
   What activity types are available in my Marketo instance?
   ```
4. Approve any permission requests Claude might ask for.
5. That's it! You're connected.

## **Troubleshooting**

**If you see "FastMCP not available" error:**
- Make sure you activated the virtual environment before installing dependencies
- Make sure you ran `pip install -r requirements.txt` in Step 3
- Try running `pip install fastmcp` separately

**If authentication fails:**
- Double-check your Marketo credentials in the config file
- Make sure your Base URL is correct (should end with `.mktorest.com`)
- Verify your Client ID and Secret are from an active LaunchPoint service

**If Claude doesn't show the Marketo tools:**
- Make sure you restarted Claude Desktop after updating the config
- Check that the file paths in your config match where you actually downloaded the MarketoMCP folder
- Look for any error messages in Claude's developer console (if available)
