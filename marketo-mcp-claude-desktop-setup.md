# Marketo MCP — Claude Desktop Setup (Agent Runbook)

This runbook installs Adobe's Marketo MCP server into the Claude Desktop application on macOS. It is written so an agent (or a human following commands) can execute it end-to-end.

**Tested:** macOS 15 (Apple Silicon), Claude Desktop v1.8555.2, Node.js v26.0.0, mcp-remote (latest from npm), 2026-05-26.

**Outcome on success:** ~131 Marketo tools available in Claude Desktop chats (forms, emails, programs, snippets, landing pages, lead lists, smart campaigns, smart lists, tokens, folders, activity reporting).

---

## Why this runbook exists

Adobe's published docs (`https://experienceleague.adobe.com/en/docs/marketo-developer/marketo/mcp-server`) instruct users to add this block to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "marketo": {
      "type": "http",
      "url": "https://marketo-mcp.adobe.io/mcp",
      "headers": { "...": "..." }
    }
  }
}
```

This configuration is **silently rejected** by Claude Desktop. The desktop app's MCP server schema only accepts stdio-transport entries (`command`, `args`, `env`, `extensionId`); it has no `type`/`url`/`headers` support. On every launch the app emits `Skipped invalid MCP server config entries: { invalidServers: [ 'marketo' ] }` to `~/Library/Logs/Claude/main.log`, shows a one-time warning dialog, and rewrites the config file with the `marketo` entry removed.

The fix is to bridge the remote HTTP server through `mcp-remote`, an npm package that exposes any remote MCP server as a stdio process.

---

## Inputs the agent needs

The user must supply three values from their Marketo instance:

| Value | Where to find it |
|---|---|
| `MARKETO_CLIENT_ID` | Marketo Admin → LaunchPoint → service → View Details |
| `MARKETO_CLIENT_SECRET` | Marketo Admin → LaunchPoint → service → View Details |
| `MARKETO_MUNCHKIN_ID` | Marketo Admin → Munchkin (format `nnn-AAA-nnn`) |

If the agent does not have these, stop and ask the user.

---

## Step 0 — Sanity-check the credentials

Before touching any configuration, confirm the credentials authenticate against the standard Marketo REST API:

```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  "https://MARKETO_MUNCHKIN_ID.mktorest.com/identity/oauth/token?grant_type=client_credentials&client_id=MARKETO_CLIENT_ID&client_secret=MARKETO_CLIENT_SECRET"
```

- `HTTP 200` → credentials are valid; proceed.
- `HTTP 401` → wrong Client ID or Secret. Stop and re-request from the user.
- Connection error → network issue or wrong Munchkin ID.

Now confirm the credentials are entitled to reach the **MCP gateway** specifically (not the same auth surface):

```bash
curl -sS -o /dev/null -w "HTTP %{http_code}\n" -X POST 'https://marketo-mcp.adobe.io/mcp' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'X-Marketo-Client-Id: MARKETO_CLIENT_ID' \
  -H 'X-Marketo-Client-Secret: MARKETO_CLIENT_SECRET' \
  -H 'X-Marketo-Munchkin-Id: MARKETO_MUNCHKIN_ID' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"setup-check","version":"0.1"}}}'
```

- `HTTP 200` → entitled, proceed.
- `HTTP 401` → credentials not recognized by gateway (different from Step 0's 401 — that one is Marketo REST). Re-check values.
- `HTTP 403` → credentials valid but **not allowlisted** for the MCP service. The bridge will install fine but every tool call will return 403. Stop and have the user contact Adobe support to request MCP entitlement for their instance. Do not proceed.

---

## Step 1 — Ensure Node.js / npx is installed

```bash
which npx
```

If this prints a path (e.g. `/opt/homebrew/bin/npx` or `/usr/local/bin/npx`), skip to Step 2.

If `npx` is not found, install it. On macOS:

```bash
# Install Homebrew if needed
which brew || /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Node.js (includes npx)
brew install node
```

Verify:

```bash
node --version   # expect v18 or higher
npx --version
```

Record the absolute path to `npx` — it is needed in Step 2:

```bash
NPX_PATH="$(which npx)"
echo "$NPX_PATH"
```

**Common values:**
- Apple Silicon Macs: `/opt/homebrew/bin/npx`
- Intel Macs: `/usr/local/bin/npx`
- Windows: `C:\Program Files\nodejs\npx.cmd`

---

## Step 2 — Smoke-test mcp-remote

Confirm npx can fetch and execute `mcp-remote`:

```bash
"$NPX_PATH" --yes mcp-remote@latest --help 2>&1 | head -5
```

This will print a `Fatal error: TypeError: Invalid URL` because the package treats `--help` as a URL. **That is expected and indicates success** — the package downloaded and ran. If you instead see `command not found` or `npm` install errors, fix the Node installation before continuing.

---

## Step 3 — Edit `claude_desktop_config.json`

**File location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

If the file does not exist, create it with `{}` as initial content.

Merge the following `marketo` entry into the existing `mcpServers` object. **Do not delete other keys** (`preferences`, `coworkUserFilesPath`, etc.) — they are user settings and removing them will reset the app's UI state.

```json
{
  "mcpServers": {
    "marketo": {
      "command": "ABSOLUTE_PATH_TO_NPX",
      "args": [
        "-y",
        "mcp-remote",
        "https://marketo-mcp.adobe.io/mcp",
        "--header",
        "X-Marketo-Client-Id: MARKETO_CLIENT_ID",
        "--header",
        "X-Marketo-Client-Secret: MARKETO_CLIENT_SECRET",
        "--header",
        "X-Marketo-Munchkin-Id: MARKETO_MUNCHKIN_ID"
      ]
    }
  }
}
```

**Critical:** `command` must be the **absolute path** to `npx`. Claude Desktop is launched by macOS LaunchServices with a minimal `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`) that does not include Homebrew. Specifying `"command": "npx"` will fail with `spawn npx ENOENT` and no Marketo tools will load. Use the value captured in `$NPX_PATH` from Step 1.

Validate the final file is well-formed JSON:

```bash
python3 -m json.tool "$HOME/Library/Application Support/Claude/claude_desktop_config.json" > /dev/null && echo "JSON valid"
```

If invalid, fix syntax before continuing.

---

## Step 4 — Restart Claude Desktop

Fully quit the app. **Closing the window is not enough**; the process must end so it re-reads the config file on next launch.

```bash
osascript -e 'quit app "Claude"'
sleep 2
open -a "Claude"
```

First launch after this change may take 10–30 seconds while npx populates `~/.npm/_npx/` with the `mcp-remote` package. Subsequent launches are immediate.

---

## Step 5 — Verify

Wait at least 30 seconds after launch, then check the log:

```bash
grep -iE "marketo|mcp.*error|mcp-remote|Skipped invalid MCP" ~/Library/Logs/Claude/main.log | tail -20
```

**Success indicators:**
- No `Skipped invalid MCP server config entries` line referencing `marketo` after the restart timestamp.
- Lines showing the marketo MCP server being initialized and tools being registered.

**In the Claude Desktop UI:**
- The MCP/tools indicator shows `marketo` connected.
- A new chat exposes ~131 Marketo tools (verify by typing `/` or asking Claude what Marketo tools it has).

---

## Troubleshooting

### `spawn npx ENOENT` in the log
The `command` field is not an absolute path, or the path is wrong. Re-run `which npx` and update the config.

### Warning dialog: "Some MCP servers could not be loaded… marketo… skipped"
The config still has the unsupported `type: "http"` shape. Replace it with the `command`/`args` shape from Step 3.

### Tools register but every call returns 403
Adobe gateway entitlement issue. The bridge is working but the account is not allowlisted for the MCP service. Re-run Step 0's second check and contact Adobe support.

### Tools register but every call returns 401
Wrong Client ID / Client Secret. Re-verify in Marketo Admin → LaunchPoint.

### First launch hangs for more than 60 seconds
Check network access to `registry.npmjs.org`. Try running the npx command from Step 2 manually to see the actual install output.

### Config file gets rewritten with `mcpServers: {}` on restart
The entry failed schema validation. Confirm the entry uses `command`/`args` and not `type`/`url`/`headers`. Validate JSON with `python3 -m json.tool`.

---

## Notes for the Adobe documentation team

Issues with the current public docs at `https://experienceleague.adobe.com/en/docs/marketo-developer/marketo/mcp-server`:

1. The `type: "http"` JSON block under the Claude Desktop section does not work with the desktop app. It is silently rejected. That block is valid only for the **Claude Code CLI** (`claude mcp add --transport http …`). The two clients use different MCP configuration schemas and should be documented separately with distinct examples.
2. The Node.js / npx prerequisite for Claude Desktop is undocumented; users without Node will see no clear error.
3. The absolute-path-to-`npx` requirement is undocumented; this is the most common failure mode for stdio-bridge MCP configs on macOS and Windows.
4. The distinction between credentials being valid (Marketo REST returns 200) and credentials being entitled to the MCP gateway (returns 403) is undocumented. If allowlisting is required, the entitlement step should appear as Step 0 of the setup.
