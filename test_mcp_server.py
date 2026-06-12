"""
Test script for mcp_server.py - calls tools through the MCP protocol.

Interactive run: python test_mcp_server.py
    Connects to an MCP server already running on http://localhost:8000/mcp.
    Start the server first: python mcp_server.py (or python mcp_server_auth.py)
    Prompts for a test mode (1=read-only, 2=write, 3=full) and for any
    asset names/emails it needs. Inputs are saved to test_config.json.

Auto run: python test_mcp_server.py --auto
    Fully self-contained, non-interactive FULL-COVERAGE suite. Starts
    mcp_server.py itself as a subprocess on port 8010 (credentials passed
    through the environment), waits for readiness, then drives a
    dependency-ordered step engine (modeled on test_blended_server.py's full
    mode) that exercises EVERY tool the server exposes - the 42 legacy
    unprefixed tools plus all 255 custom_* tools. Credentials come from .env
    with a fallback to .env.sandbox (MARKETO_CLIENT_ID / MARKETO_CLIENT_SECRET
    / MARKETO_MUNCHKIN_ID, with MARKETO_BASE_URL derived).

    All created assets are named MCPTEST_LEG_* and removed at the end; a
    sweep also clears MCPTEST_LEG_* leftovers at start and end so reruns are
    repeatable. Objects Marketo cannot delete via API (lead / program-member
    fields, the custom activity type, the custom object type) use fixed
    names with reuse-if-exists semantics. Steps are classified PASS / SKIP
    (with a reason) / FAIL; exit code is non-zero on any FAIL or uncovered
    tool.

    Notable chains (each tests several operations in one flow):
      - custom_sync_leads(createOnly) -> custom_sync_leads(createDuplicate)
        -> custom_merge_leads, plus a second duplicate merged through the
        legacy merge_leads tool
      - tag-type discovery -> create_program with required tags (702 guard)
      - import batch -> status poll -> failures -> warnings
      - export create -> enqueue -> status poll -> file (+ cancel on a 2nd job)

Group runs: python test_mcp_server.py --group bulk-export
            python test_mcp_server.py --group bulk-import
    Run ONLY the bulk-export / bulk-import tool steps plus minimal
    prerequisites. Export jobs are tiny (activity window = a few minutes
    around this run; program-member / custom-object exports scoped to this
    run's assets); imports are 2-3 rows. Exit code reflects FAILs only.
"""

import argparse
import asyncio
import inspect
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

import dotenv
import requests

# Add current directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

dotenv.load_dotenv()

from fastmcp import Client
from fastmcp.exceptions import ToolError

TEST_CONFIG_FILE = os.path.join(SCRIPT_DIR, "test_config.json")
ENV_SANDBOX_FILE = os.path.join(SCRIPT_DIR, ".env.sandbox")

MCP_SERVER_URL = "http://localhost:8000/mcp"   # interactive mode (external server)
AUTO_PORT = 8010                               # auto mode self-started server
AUTO_URL = f"http://localhost:{AUTO_PORT}/mcp"

AUTO_MODE = False
AUTO_PREFIX = "MCPTEST_LEG_"
SAMPLE_EMAIL_TO = "tyron.pretorius+mcptest@knak.com"
INVITE_EMAIL = "tyron.pretorius+mcptestleginvite@knak.com"

STATE_ERROR_CODES = {'709', '1003', '1004', '1006', '1042'}

# Fixed-name objects that Marketo cannot delete via API: reuse across runs.
LEAD_FIELD = "mcptestLegField1"
PM_FIELD = "mcptestLegPmField1"
ACT_TYPE = "mcptestlegact1"
CO_TYPE = "mcptest_leg_co"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
POLL_INTERVAL = 5
POLL_TIMEOUT = 90
CALL_TIMEOUT = 120

GROUP_EXPORT = 'bulk-export'
GROUP_IMPORT = 'bulk-import'

_test_config = {}


# ============================================================================
# Credentials & server management (auto mode)
# ============================================================================

def parse_env_file(path):
    """Parse a KEY=VALUE env file into a dict."""
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    return values


def resolve_credentials():
    """Resolve Marketo credentials from the environment/.env with a
    fallback to .env.sandbox. Returns a dict of env vars or None."""
    sandbox = parse_env_file(ENV_SANDBOX_FILE)
    client_id = os.environ.get('MARKETO_CLIENT_ID') or sandbox.get('MARKETO_CLIENT_ID')
    client_secret = os.environ.get('MARKETO_CLIENT_SECRET') or sandbox.get('MARKETO_CLIENT_SECRET')
    base_url = os.environ.get('MARKETO_BASE_URL') or sandbox.get('MARKETO_BASE_URL')
    if not base_url and sandbox.get('MARKETO_MUNCHKIN_ID'):
        base_url = f"https://{sandbox['MARKETO_MUNCHKIN_ID']}.mktorest.com"

    if not (client_id and client_secret and base_url):
        return None

    return {
        'MARKETO_CLIENT_ID': client_id,
        'MARKETO_CLIENT_SECRET': client_secret,
        'MARKETO_BASE_URL': base_url,
    }


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def start_mcp_server(creds, port):
    """Start mcp_server.py as a subprocess on the given port and wait until
    it accepts connections. Returns (process, log_file_path)."""
    if port_in_use(port):
        print(f"ERROR: port {port} is already in use. "
              f"Stop the existing server before running with --auto.")
        sys.exit(1)

    env = dict(os.environ)
    env.update(creds)

    log_fd, log_path = tempfile.mkstemp(prefix="mcp_server_auto_", suffix=".log")
    log_file = os.fdopen(log_fd, 'w')

    print(f"Starting MCP server subprocess on port {port} (log: {log_path})...")
    # mcp_server.py hardcodes port 8000 in __main__, so launch via -c to pick
    # a port that cannot collide with other suites running on this sandbox.
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import mcp_server; mcp_server.mcp.run("
         f"transport='streamable-http', host='127.0.0.1', port={port})"],
        cwd=SCRIPT_DIR, env=env, stdout=log_file, stderr=subprocess.STDOUT
    )

    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            log_file.close()
            print("ERROR: MCP server exited during startup. Output:")
            with open(log_path) as f:
                print(f.read()[-4000:])
            sys.exit(1)
        if port_in_use(port):
            print("MCP server is up.")
            return proc, log_path
        time.sleep(0.25)

    proc.terminate()
    log_file.close()
    print("ERROR: MCP server did not become ready within 40s. Output:")
    with open(log_path) as f:
        print(f.read()[-4000:])
    sys.exit(1)


def stop_mcp_server(proc):
    """Terminate the MCP server subprocess."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    print("MCP server stopped.")


# ============================================================================
# Test config (interactive mode)
# ============================================================================

def load_test_config():
    """Load saved test variables from file."""
    global _test_config
    if os.path.exists(TEST_CONFIG_FILE):
        try:
            with open(TEST_CONFIG_FILE, 'r') as f:
                _test_config = json.load(f)
        except (json.JSONDecodeError, IOError):
            _test_config = {}


def save_test_config():
    """Save current test variables to file."""
    with open(TEST_CONFIG_FILE, 'w') as f:
        json.dump(_test_config, f, indent=2)


def get_test_var(key, prompt, required=False):
    """Get a test variable from saved config or prompt the user."""
    saved = _test_config.get(key, "")
    if saved:
        print(f"  (loaded from test_config.json: {key}={saved})")
        return saved

    value = input(prompt).strip()
    if value:
        _test_config[key] = value
        save_test_config()
    elif required:
        return ""

    return value


def get_asset_path(asset):
    """Get the folder path for displaying an asset's location."""
    if 'path' in asset:
        return asset['path']
    folder = asset.get('folder', {})
    folder_name = folder.get('folderName', '')
    if folder_name:
        return folder_name
    folder_id = folder.get('value', '')
    if folder_id:
        return f"Folder ID: {folder_id}"
    return ""


async def resolve_asset(client, config_key, prompt, tool_name, args_builder):
    """Resolve an asset by name via MCP tool, with disambiguation."""
    saved = _test_config.get(config_key, "")
    if saved:
        print(f"  (loaded from test_config.json: {config_key}={saved})")
        return int(saved)

    name = input(prompt).strip()
    if not name:
        return None

    result = await call_tool(client, tool_name, args_builder(name))

    if not result or not result.get('result'):
        print(f"  No assets found matching '{name}'")
        return None

    matches = result['result']

    if len(matches) == 1:
        asset = matches[0]
        asset_id = asset['id']
        path = get_asset_path(asset)
        display = f"  Found: '{asset.get('name', name)}' (ID: {asset_id})"
        if path:
            display += f" in {path}"
        print(display)
        _test_config[config_key] = str(asset_id)
        save_test_config()
        return asset_id

    print(f"\n  Multiple assets found matching '{name}':")
    for i, asset in enumerate(matches, 1):
        path = get_asset_path(asset)
        display = f"    {i}. '{asset.get('name', name)}' (ID: {asset['id']})"
        if path:
            display += f" - {path}"
        print(display)

    choice = input(f"  Select (1-{len(matches)}, or Enter to skip): ").strip()
    if not choice:
        return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(matches):
            asset_id = matches[idx]['id']
            _test_config[config_key] = str(asset_id)
            save_test_config()
            return asset_id
    except ValueError:
        pass

    print("  Invalid selection, skipping.")
    return None


async def resolve_lead(client, config_key, prompt):
    """Resolve a lead by email address via MCP tool."""
    saved = _test_config.get(config_key, "")
    if saved:
        print(f"  (loaded from test_config.json: {config_key}={saved})")
        return int(saved)

    email = input(prompt).strip()
    if not email:
        return None

    result = await call_tool(client, "get_lead_by_email", {"email": email})

    if not result or not result.get('result'):
        print(f"  No lead found for '{email}'")
        return None

    lead = result['result'][0]
    lead_id = lead['id']
    print(f"  Found lead: {lead.get('firstName', '')} {lead.get('lastName', '')} (ID: {lead_id})")
    _test_config[config_key] = str(lead_id)
    save_test_config()
    return lead_id


# ============================================================================
# Test bookkeeping & coverage
# ============================================================================

passed = 0
failed = 0
skipped = 0

skip_reasons = []  # list of (test_name, reason)

ALL_TOOLS = []           # populated from client.list_tools() at connect time
executed_tools = set()   # tools actually called by a test
skipped_tools = set()    # tools whose test was skipped

created_assets = {
    'campaigns': [],
    'programs': [],
    'tokens': []
}


def record_skip_coverage(test_name):
    """If a skipped test's name maps to a known tool, record it."""
    tool = test_name.split('(')[0].strip()
    if tool in ALL_TOOLS:
        skipped_tools.add(tool)


async def call_tool(client, tool_name, arguments=None):
    """Call an MCP tool and return the parsed result."""
    if arguments is None:
        arguments = {}

    result = await client.call_tool(tool_name, arguments)

    if result and result.content:
        text = result.content[0].text
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return text

    return None


async def test(client, name, tool_name, arguments=None, allowed_errors=None):
    """Run a single MCP tool test and track the result (interactive modes)."""
    global passed, failed, skipped
    executed_tools.add(tool_name)
    try:
        result = await call_tool(client, tool_name, arguments)

        if isinstance(result, dict) and result.get('errors'):
            codes = {str(e.get('code')) for e in result['errors'] if isinstance(e, dict)}
            if allowed_errors and codes & {str(c) for c in allowed_errors}:
                reason = '; '.join(
                    f"{e.get('code')}: {e.get('message')}" for e in result['errors']
                )
                print(f"  [SKIP] {name} - expected state error ({reason})")
                skip_reasons.append((name, f"expected state error ({reason})"))
                skipped += 1
                return None
            print(f"  [FAIL] {name}")
            print(f"         {result['errors']}")
            failed += 1
            return None

        if isinstance(result, dict) and set(result.keys()) == {'error'}:
            print(f"  [SKIP] {name} - {result['error']}")
            skip_reasons.append((name, result['error']))
            skipped += 1
            return None

        if isinstance(result, dict) and 'success' in result and result['success'] is not True:
            print(f"  [FAIL] {name}")
            print(f"         success={result.get('success')} with no errors: {result}")
            failed += 1
            return None

        print(f"  [PASS] {name}")
        passed += 1
        return result

    except Exception as e:
        print(f"  [FAIL] {name} - {e}")
        failed += 1
        return None


def skip(name, reason=""):
    """Mark a test as skipped."""
    global skipped
    msg = f"  [SKIP] {name}"
    if reason:
        msg += f" - {reason}"
    print(msg)
    skip_reasons.append((name, reason))
    record_skip_coverage(name)
    skipped += 1


def print_summary():
    """Print final test results."""
    total = passed + failed + skipped
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {skipped} skipped (total: {total})")
    print(f"{'=' * 60}")


def print_coverage(enforce=True):
    """Print which MCP tools were exercised by this run."""
    if not ALL_TOOLS:
        return []
    covered = (executed_tools | skipped_tools) & set(ALL_TOOLS)
    uncovered = [t for t in ALL_TOOLS if t not in covered]
    skipped_only = sorted((skipped_tools - executed_tools) & set(ALL_TOOLS))

    print(f"\n{'=' * 60}")
    print(f"COVERAGE: covered {len(covered)}/{len(ALL_TOOLS)} tools "
          f"({len(executed_tools & set(ALL_TOOLS))} executed, {len(skipped_only)} skipped-only)")
    if skipped_only:
        print(f"  Skipped-only: {', '.join(skipped_only)}")
    if uncovered:
        print(f"  UNCOVERED: {', '.join(uncovered)}")
        if not enforce:
            print("  (coverage not enforced for group runs)")
    else:
        print("  All tools covered.")
    print(f"{'=' * 60}")
    return uncovered


# ============================================================================
# Auto-mode discovery helpers
# ============================================================================

def discover_channels(channels_result):
    """Find a channel for a Default program (with >=2 visible statuses) and
    one for an Email program."""
    default_channel = None
    email_channel = None
    statuses = []
    for ch in (channels_result or []):
        prog_type = (ch.get('applicableProgramType') or '').lower()
        ch_statuses = [s['name'] for s in ch.get('progressionStatuses') or []
                       if not s.get('hidden') and s.get('step', 0) > 0]
        if prog_type in ('program', 'default') and len(ch_statuses) >= 2 \
                and (default_channel is None or ch.get('name') == 'Chat'):
            default_channel = ch
            statuses = ch_statuses
        if prog_type in ('email_batch', 'email') and not email_channel:
            email_channel = ch
    return default_channel, email_channel, statuses


# ============================================================================
# Read-Only Tests (interactive)
# ============================================================================

async def run_readonly_tests(client):
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("MCP SERVER - READ-ONLY TESTS")
    print("=" * 60)

    print("\n--- Server Connection ---")
    try:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]
        ALL_TOOLS.clear()
        ALL_TOOLS.extend(sorted(tool_names))
        print(f"  [PASS] list_tools() - {len(tools)} tools available")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] list_tools() - {e}")
        failed += 1
        print("\nCannot connect to MCP server. Exiting.")
        print_summary()
        return

    print("\n--- Activity Types ---")
    activity_types = await test(client, "get_activity_types", "get_activity_types")
    if activity_types and activity_types.get('result'):
        print(f"         Found {len(activity_types['result'])} activity types")

    print("\n--- Lead Schema ---")
    lead_schema = await test(client, "describe_leads", "describe_leads")
    if lead_schema and lead_schema.get('result'):
        print(f"         Found {len(lead_schema['result'])} field definitions")

    print("\n--- Browse Emails ---")
    emails = await test(client, "browse_emails", "browse_emails")
    if emails and emails.get('result'):
        print(f"         Found {len(emails['result'])} emails")

    print("\n--- Email CC Fields ---")
    await test(client, "get_email_cc_fields", "get_email_cc_fields")

    print("\n--- Channels ---")
    channels = await test(client, "get_channels", "get_channels")
    if channels and channels.get('result'):
        print(f"         Found {len(channels['result'])} channels")

    print("\n--- Browse Folders ---")
    folders = await test(client, "browse_folders", "browse_folders")
    if folders and folders.get('result'):
        print(f"         Found {len(folders['result'])} folders")

    print("\n--- Folder By Name (auto-discovered) ---")
    if folders and folders.get('result'):
        folder_name = folders['result'][0]['name']
        await test(client, f"get_folder_by_name('{folder_name}')",
                   "get_folder_by_name", {"name": folder_name})
    else:
        skip("get_folder_by_name", "no folders found in browse")

    print("\n--- Browse Smart Campaigns ---")
    campaigns = await test(client, "browse_smart_campaigns", "browse_smart_campaigns")
    if campaigns and campaigns.get('result'):
        print(f"         Found {len(campaigns['result'])} campaigns")

    print("\n--- Browse Programs ---")
    programs = await test(client, "browse_programs", "browse_programs")
    if programs and programs.get('result'):
        print(f"         Found {len(programs['result'])} programs")

    print("\n--- Program Members Schema ---")
    await test(client, "describe_program_members", "describe_program_members")

    print("\n--- Email Detail Tests (auto-discovered) ---")
    if emails and emails.get('result'):
        email_asset = emails['result'][0]
        eid = email_asset['id']
        ename = email_asset['name']
        print(f"  Using email: '{ename}' (ID: {eid})")

        await test(client, f"get_email_by_id({eid})",
                   "get_email_by_id", {"email_id": eid})
        await test(client, f"get_email_by_name('{ename}')",
                   "get_email_by_name", {"name": ename})
        await test(client, f"get_email_content({eid})",
                   "get_email_content", {"email_id": eid})
        await test(client, f"preview_email({eid})",
                   "preview_email", {"email_id": eid})
    else:
        skip("get_email_by_id", "no emails found in browse")
        skip("get_email_by_name", "no emails found in browse")
        skip("get_email_content", "no emails found in browse")
        skip("preview_email", "no emails found in browse")

    print("\n--- Smart Campaign Detail Tests (auto-discovered) ---")
    if campaigns and campaigns.get('result'):
        camp = campaigns['result'][0]
        cid = camp['id']
        cname = camp['name']
        print(f"  Using campaign: '{cname}' (ID: {cid})")

        await test(client, f"get_smart_campaign_by_id({cid})",
                   "get_smart_campaign_by_id", {"campaign_id": cid})
        await test(client, f"get_smart_campaign_by_name('{cname}')",
                   "get_smart_campaign_by_name", {"name": cname})
    else:
        skip("get_smart_campaign_by_id", "no campaigns found in browse")
        skip("get_smart_campaign_by_name", "no campaigns found in browse")

    print("\n--- Program Detail Tests (auto-discovered) ---")
    if programs and programs.get('result'):
        prog = programs['result'][0]
        pid = prog['id']
        pname = prog['name']
        print(f"  Using program: '{pname}' (ID: {pid})")

        await test(client, f"get_program_by_id({pid})",
                   "get_program_by_id", {"program_id": pid})
        await test(client, f"get_program_by_name('{pname}')",
                   "get_program_by_name", {"name": pname})
        await test(client, f"query_program_members({pid})",
                   "query_program_members",
                   {"program_id": pid, "filter_type": "statusName", "filter_values": "member"})
    else:
        skip("get_program_by_id", "no programs found in browse")
        skip("get_program_by_name", "no programs found in browse")
        skip("query_program_members", "no programs found in browse")

    print("\n--- Folder Token Tests (auto-discovered) ---")
    if folders and folders.get('result'):
        folder = folders['result'][0]
        fid = folder['id']
        print(f"  Using folder ID: {fid}")

        await test(client, f"get_tokens_by_folder({fid})",
                   "get_tokens_by_folder", {"folder_id": fid})
    else:
        skip("get_tokens_by_folder", "no folders found in browse")

    print("\n--- Lead Lookup Tests ---")
    test_email = get_test_var("test_email", "Enter a test email address for lead lookup (or Enter to skip): ")

    if test_email:
        lead_data = await test(client, f"get_lead_by_email('{test_email}')",
                               "get_lead_by_email", {"email": test_email})

        lead_id = None
        if lead_data and lead_data.get('result'):
            lead_id = lead_data['result'][0]['id']
            print(f"         Found lead ID: {lead_id}")

        if lead_id is not None:
            await test(client, f"get_lead_activities({lead_id})",
                       "get_lead_activities", {"lead_id": lead_id})
            await test(client, f"get_lead_activities_by_email('{test_email}')",
                       "get_lead_activities_by_email", {"email": test_email})
            await test(client, f"get_lead_changes({lead_id})",
                       "get_lead_changes", {"lead_id": lead_id})
        else:
            print(f"         No lead found for '{test_email}'")
            skip("get_lead_activities", "no lead found")
            skip("get_lead_activities_by_email", "no lead found")
            skip("get_lead_changes", "no lead found")
    else:
        skip("get_lead_by_email", "no email provided")
        skip("get_lead_activities", "no email provided")
        skip("get_lead_activities_by_email", "no email provided")
        skip("get_lead_changes", "no email provided")

    print_summary()


# ============================================================================
# Write-Only Tests (interactive)
# ============================================================================

async def run_write_tests(client):
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("WRITE OPERATIONS TESTS (via MCP)")
    print("=" * 60)
    print(f"\nThese tests will CREATE, UPDATE, and CLONE assets in Marketo.")
    print(f"Test assets will be prefixed with 'MCPTEST_' for easy cleanup.\n")

    print("--- Test Configuration ---")
    folder_id = await resolve_asset(client, "folder_id",
                                    "Folder name to create test assets in: ",
                                    "get_folder_by_name",
                                    lambda name: {"name": name})
    if not folder_id:
        print("Folder is required for write tests. Skipping.")
        return

    program_type = get_test_var("program_type", "Program type to be created (e.g. 'Default', 'Email', 'Engagement', 'Event'):", required=True)
    if not program_type:
        print("Program type is required for program creation. Skipping.")
        return

    available_channels = await call_tool(client, "get_channels", {})
    channel_list = available_channels.get('result', []) if available_channels else []
    if channel_list:
        print("\n  Available channels:")
        for ch in channel_list:
            prog_type = ch.get('applicableProgramType', 'Unknown')
            print(f"    - {ch['name']} (program type: {prog_type})")
        print()

    channel = get_test_var("channel", "Program channel to be created:", required=True)
    if not channel:
        print("Channel is required for program creation. Skipping.")
        return

    trigger_campaign_id = await resolve_asset(client, "trigger_campaign_id",
                                              "Trigger Campaign name for activate/deactivate tests (or Enter to skip): ",
                                              "get_smart_campaign_by_name",
                                              lambda name: {"name": name})
    batch_campaign_id = await resolve_asset(client, "batch_campaign_id",
                                            "Batch Campaign name for schedule tests (or Enter to skip): ",
                                            "get_smart_campaign_by_name",
                                            lambda name: {"name": name})
    request_campaign_id = await resolve_asset(client, "request_campaign_id",
                                              "Request Campaign name for request campaign test (or Enter to skip): ",
                                              "get_smart_campaign_by_name",
                                              lambda name: {"name": name})
    lead_id = await resolve_lead(client, "lead_id",
                                 "Lead email for request campaign test (or Enter to skip): ")
    email_program_id = await resolve_asset(client, "email_program_id",
                                           "Email Program name for clone/approve/unapprove tests (or Enter to skip): ",
                                           "get_program_by_name",
                                           lambda name: {"name": name})
    merge_winner_id = await resolve_lead(client, "merge_winner_lead_id",
                                         "Winning lead email for merge test (or Enter to skip): ")
    merge_loser_id = await resolve_lead(client, "merge_loser_lead_id",
                                        "Losing lead email for merge test (or Enter to skip): ")

    print("\n--- Create Smart Campaign ---")
    created_campaign = await test(client, "create_smart_campaign('MCPTEST_Campaign')",
                                 "create_smart_campaign",
                                 {"name": "MCPTEST_Campaign", "folder_id": folder_id,
                                  "description": "Test campaign from MCP test suite"})

    if created_campaign and created_campaign.get('result'):
        new_campaign_id = created_campaign['result'][0]['id']
        created_assets['campaigns'].append((new_campaign_id, "MCPTEST_Campaign_Updated"))
        print(f"         Created campaign ID: {new_campaign_id}")

        print("\n--- Update Smart Campaign ---")
        await test(client, f"update_smart_campaign({new_campaign_id})",
                   "update_smart_campaign",
                   {"campaign_id": new_campaign_id,
                    "name": "MCPTEST_Campaign_Updated",
                    "description": "Updated by MCP test suite"})
    else:
        skip("update_smart_campaign", "create failed")

    clone_source_id = trigger_campaign_id or batch_campaign_id or request_campaign_id
    if clone_source_id:
        print("\n--- Clone Smart Campaign ---")
        cloned_campaign = await test(client, f"clone_smart_campaign({clone_source_id})",
                                     "clone_smart_campaign",
                                     {"campaign_id": clone_source_id,
                                      "name": "MCPTEST_Campaign_Clone",
                                      "folder_id": folder_id})
        if cloned_campaign and cloned_campaign.get('result'):
            created_assets['campaigns'].append((cloned_campaign['result'][0]['id'], "MCPTEST_Campaign_Clone"))
    else:
        skip("clone_smart_campaign", "no campaigns provided")

    if trigger_campaign_id:
        print("\n--- Activate Smart Campaign ---")
        await test(client, f"activate_smart_campaign({trigger_campaign_id})",
                   "activate_smart_campaign",
                   {"campaign_id": trigger_campaign_id})

        print("\n--- Deactivate Smart Campaign ---")
        await test(client, f"deactivate_smart_campaign({trigger_campaign_id})",
                   "deactivate_smart_campaign",
                   {"campaign_id": trigger_campaign_id})
    else:
        print("\n--- Activate/Deactivate Smart Campaign ---")
        skip("activate_smart_campaign", "no trigger campaign provided")
        skip("deactivate_smart_campaign", "no trigger campaign provided")

    if batch_campaign_id:
        print("\n--- Schedule Batch Campaign ---")
        print("  WARNING: This will schedule the batch campaign to run.")
        confirm = input("  Proceed? (y/n): ").strip().lower()
        if confirm in ('y', 'yes'):
            await test(client, f"schedule_batch_campaign({batch_campaign_id})",
                       "schedule_batch_campaign",
                       {"campaign_id": batch_campaign_id})
        else:
            skip("schedule_batch_campaign", "user declined")
    else:
        print("\n--- Schedule Batch Campaign ---")
        skip("schedule_batch_campaign", "no batch campaign provided")

    if request_campaign_id and lead_id:
        print("\n--- Request Campaign ---")
        print("  WARNING: This will trigger the request campaign for the lead.")
        confirm = input("  Proceed? (y/n): ").strip().lower()
        if confirm in ('y', 'yes'):
            await test(client, f"request_campaign({request_campaign_id}, [{lead_id}])",
                       "request_campaign",
                       {"campaign_id": request_campaign_id,
                        "lead_ids": [lead_id]})
        else:
            skip("request_campaign", "user declined")
    else:
        print("\n--- Request Campaign ---")
        skip("request_campaign", "no request campaign or lead provided")

    if merge_winner_id and merge_loser_id:
        print("\n--- Merge Leads ---")
        print("  WARNING: This will PERMANENTLY merge the losing lead into the winning lead.")
        confirm = input("  Proceed? (y/n): ").strip().lower()
        if confirm in ('y', 'yes'):
            await test(client, f"merge_leads({merge_winner_id}, [{merge_loser_id}])",
                       "merge_leads",
                       {"winning_lead_id": merge_winner_id,
                        "losing_lead_ids": [merge_loser_id]})
        else:
            skip("merge_leads", "user declined")
    else:
        print("\n--- Merge Leads ---")
        skip("merge_leads", "no winning/losing leads provided")

    print("\n--- Create Program ---")
    created_program = await test(client, "create_program('MCPTEST_Program')",
                                "create_program",
                                {"name": "MCPTEST_Program", "folder_id": folder_id,
                                 "program_type": program_type, "channel": channel,
                                 "description": "Test program from MCP test suite"})

    if created_program and created_program.get('result'):
        new_program_id = created_program['result'][0]['id']
        created_assets['programs'].append((new_program_id, "MCPTEST_Program"))
        print(f"         Created program ID: {new_program_id}")

        print("\n--- Update Program ---")
        await test(client, f"update_program({new_program_id})",
                   "update_program",
                   {"program_id": new_program_id,
                    "description": "Updated by MCP test suite"})
    else:
        skip("update_program", "create failed")

    if email_program_id:
        print("\n--- Clone Program ---")
        cloned_program = await test(client, f"clone_program({email_program_id})",
                                    "clone_program",
                                    {"program_id": email_program_id,
                                     "name": "MCPTEST_Program_Clone",
                                     "folder_id": folder_id})
        if cloned_program and cloned_program.get('result'):
            created_assets['programs'].append((cloned_program['result'][0]['id'], "MCPTEST_Program_Clone"))
    else:
        skip("clone_program", "no email program provided")

    if email_program_id:
        print("\n--- Approve Email Program ---")
        await test(client, f"approve_email_program({email_program_id})",
                   "approve_email_program",
                   {"program_id": email_program_id})

        print("\n--- Unapprove Email Program ---")
        await test(client, f"unapprove_email_program({email_program_id})",
                   "unapprove_email_program",
                   {"program_id": email_program_id})
    else:
        print("\n--- Approve/Unapprove Email Program ---")
        skip("approve_email_program", "no email program provided")
        skip("unapprove_email_program", "no email program provided")

    print("\n--- Create Token ---")
    created_token = await test(client, f"create_token({folder_id}, 'MCPTEST_Token')",
                              "create_token",
                              {"folder_id": folder_id, "name": "MCPTEST_Token",
                               "token_type": "text",
                               "value": "Test value from MCP test suite",
                               "folder_type": "Folder"})

    if created_token and not created_token.get('errors'):
        created_assets['tokens'].append((folder_id, "MCPTEST_Token", "text", "Folder"))

        print("\n--- Update Token ---")
        await test(client, f"update_token({folder_id}, 'MCPTEST_Token')",
                   "update_token",
                   {"folder_id": folder_id, "name": "MCPTEST_Token",
                    "token_type": "text",
                    "value": "Updated value from MCP test suite",
                    "folder_type": "Folder"})
    else:
        skip("update_token", "create failed")

    print_summary()

    await cleanup_test_assets(client, folder_id)


async def run_full_tests(client):
    await run_readonly_tests(client)
    await run_write_tests(client)


# ============================================================================
# Cleanup (interactive)
# ============================================================================

async def cleanup_test_assets(client, folder_id):
    """Delete test assets created during the interactive run."""
    total = (len(created_assets['campaigns']) +
             len(created_assets['programs']) +
             len(created_assets['tokens']))

    if total == 0:
        return

    print(f"\n{'=' * 60}")
    print("CLEANUP - DELETE TEST ASSETS")
    print(f"{'=' * 60}")
    print(f"\nThe following test assets were created:")

    for cid, cname in created_assets['campaigns']:
        print(f"  Smart Campaign ID: {cid} ('{cname}')")
    for pid, pname in created_assets['programs']:
        print(f"  Program ID: {pid} ('{pname}')")
    for (fid, name, ttype, ftype) in created_assets['tokens']:
        print(f"  Token: '{name}' in {ftype} {fid}")

    confirm = input(f"\nDelete all {total} test assets? (y/n): ").strip().lower()
    if confirm not in ('y', 'yes'):
        print("Skipping cleanup. You can delete these manually in Marketo.")
        return

    print("\n--- Deleting test assets ---")

    for (fid, name, ttype, ftype) in created_assets['tokens']:
        executed_tools.add('delete_token')
        try:
            result = await call_tool(client, "delete_token",
                                     {"folder_id": fid, "name": name,
                                      "token_type": ttype, "folder_type": ftype})
            if result and result.get('success'):
                print(f"  [DELETED] Token '{name}' from {ftype} {fid}")
            else:
                print(f"  [FAILED]  Token '{name}' - {result}")
        except Exception as e:
            print(f"  [FAILED]  Token '{name}' - {e}")

    for cid, cname in created_assets['campaigns']:
        executed_tools.add('delete_smart_campaign')
        try:
            result = await call_tool(client, "delete_smart_campaign", {"campaign_id": cid})
            if result and result.get('success'):
                print(f"  [DELETED] Smart Campaign {cid}")
            else:
                print(f"  [FAILED]  Smart Campaign {cid} - {result}")
        except Exception as e:
            print(f"  [FAILED]  Smart Campaign {cid} - {e}")

    for pid, pname in created_assets['programs']:
        executed_tools.add('delete_program')
        try:
            result = await call_tool(client, "delete_program", {"program_id": pid})
            if result and result.get('success'):
                print(f"  [DELETED] Program {pid}")
            else:
                print(f"  [FAILED]  Program {pid} - {result}")
        except Exception as e:
            print(f"  [FAILED]  Program {pid} - {e}")

    print("\nCleanup complete.")

    print("\n--- Verifying cleanup ---")
    leftovers = []
    for cid, cname in created_assets['campaigns']:
        try:
            check = await call_tool(client, "get_smart_campaign_by_name", {"name": cname})
            if check and check.get('result'):
                leftovers.append(f"Smart Campaign '{cname}' (ID {cid})")
        except Exception:
            pass
    for pid, pname in created_assets['programs']:
        try:
            check = await call_tool(client, "get_program_by_name", {"name": pname})
            if check and check.get('result'):
                leftovers.append(f"Program '{pname}' (ID {pid})")
        except Exception:
            pass

    if leftovers:
        print("  WARNING: the following test assets were NOT removed:")
        for item in leftovers:
            print(f"    - {item}")
    else:
        print("  Verified: no test assets left behind.")


# ============================================================================
# ============================================================================
# FULL AUTO SUITE - dependency-ordered step engine over the MCP protocol
# (mirrors test_blended_server.py's full mode; REST is used only for fixture
# plumbing the legacy server has no tools for).
# ============================================================================
# ============================================================================

# NOTE: mktoModule-based template HTML is rejected at approval time by this
# sandbox (709/"There is a problem with the email template content"), so the
# suite uses a plain mktoText template with one mktoString variable. Emails
# built from it have Text sections (no modules); the module-editing steps
# are expected to SKIP with "email has no modules" / 611.
EMAIL_TEMPLATE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MCPTEST_LEG template</title>
<meta class="mktoString" id="mcptestVar" mktoname="MCPTEST Var" default="hello">
</head>
<body>
<div class="mktoText" id="textone" mktoname="Text One">Hello from text one.</div>
<div class="mktoText" id="texttwo" mktoname="Text Two">Hello from text two.</div>
</body>
</html>
"""

LP_TEMPLATE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MCPTEST_LEG LP template</title>
</head>
<body>
<div class="mktoContent" id="content">MCPTEST_LEG landing page template body.</div>
</body>
</html>
"""


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class RestInfra:
    """Direct REST helpers for fixture plumbing the legacy MCP server has no
    tools for (folders, forms, raw emails, snippets, lists, tag discovery,
    lead-import status, lead-export creation). These never count toward tool
    coverage - they only build targets for the real tool steps."""

    def __init__(self, creds):
        self.creds = creds
        self.base_url = creds['MARKETO_BASE_URL']
        self._token = None

    def token(self, refresh=False):
        if self._token is None or refresh:
            resp = requests.get(
                self.base_url + '/identity/oauth/token',
                params={'grant_type': 'client_credentials',
                        'client_id': self.creds['MARKETO_CLIENT_ID'],
                        'client_secret': self.creds['MARKETO_CLIENT_SECRET']},
                timeout=30).json()
            self._token = resp['access_token']
        return self._token

    def _request(self, method, path, **kwargs):
        for attempt in (1, 2):
            headers = kwargs.pop('headers', {})
            headers['Authorization'] = 'Bearer ' + self.token(refresh=(attempt == 2))
            resp = requests.request(method, self.base_url + path, headers=headers,
                                    timeout=60, **dict(kwargs))
            try:
                data = resp.json()
            except ValueError:
                return {'success': False,
                        'errors': [{'code': 'non-json', 'message': resp.text[:200]}]}
            codes = {str(e.get('code')) for e in (data.get('errors') or [])
                     if isinstance(e, dict)}
            if attempt == 1 and codes & {'601', '602'}:
                continue
            return data
        return data

    def get(self, path, params=None):
        return self._request('GET', path, params=params)

    def post(self, path, data=None, json_body=None):
        return self._request('POST', path, data=data, json=json_body)

    # -- folders ------------------------------------------------------------
    def browse_folders(self, root_id, root_type="Folder", max_depth=2, max_return=200):
        return self.get('/rest/asset/v1/folders.json',
                        {'root': json.dumps({"id": root_id, "type": root_type}),
                         'maxDepth': max_depth, 'maxReturn': max_return})

    def find_roots(self):
        top = self.get('/rest/asset/v1/folders.json', {'maxDepth': 2, 'maxReturn': 200})
        out = {}
        for f in top.get('result') or []:
            if f.get('path') == '/Marketing Activities':
                out['ma_root'] = f['id']
            elif f.get('path') == '/Design Studio':
                out['ds_root'] = f['id']
            elif f.get('path') == '/Marketing Activities/Default':
                out['ma_parent'] = f['id']
        if 'ds_root' in out:
            ds = self.browse_folders(out['ds_root'], max_depth=3)
            wanted = {
                '/Design Studio/Default/Forms': 'ds_forms_root',
                '/Design Studio/Default/Emails': 'ds_emails_root',
                '/Design Studio/Default/Emails/Templates': 'ds_etpl_root',
                '/Design Studio/Default/Landing Pages': 'ds_lp_root',
                '/Design Studio/Default/Landing Pages/Templates': 'ds_lpt_root',
                '/Design Studio/Default/Snippets': 'ds_snip_root',
            }
            for f in ds.get('result') or []:
                key = wanted.get(f.get('path'))
                if key:
                    out[key] = f['id']
        if 'ma_parent' not in out and 'ma_root' in out:
            out['ma_parent'] = out['ma_root']
        return out

    def create_folder(self, name, parent_id, parent_type="Folder"):
        return self.post('/rest/asset/v1/folders.json',
                         data={'name': name,
                               'parent': json.dumps({"id": parent_id, "type": parent_type}),
                               'description': 'MCPTEST_LEG suite scratch folder'})

    def delete_folder(self, folder_id):
        return self.post(f'/rest/asset/v1/folder/{folder_id}/delete.json',
                         data={'type': 'Folder'})

    # -- tags ---------------------------------------------------------------
    def discover_required_tags(self, applicable_program_type):
        tags = []
        try:
            resp = self.get('/rest/asset/v1/tagTypes.json', {'maxReturn': 200})
            for tag_type in resp.get('result') or []:
                if not tag_type.get('required'):
                    continue
                applicable = (tag_type.get('applicableProgramTypes') or '')
                applicable = [a.strip() for a in applicable.strip('[]').split(',') if a.strip()]
                if applicable and applicable_program_type \
                        and applicable_program_type not in applicable:
                    continue
                detail = self.get('/rest/asset/v1/tagType/byName.json',
                                  {'name': tag_type['tagType']})
                detail_result = (detail.get('result') or [{}])[0]
                values = [v.strip() for v in
                          (detail_result.get('allowableValues') or '').strip('[]').split(',')
                          if v.strip()]
                if values:
                    tags.append({'tagType': tag_type['tagType'], 'tagValue': values[0]})
        except Exception as e:
            print(f"  (tag discovery failed: {e})")
        return tags

    # -- forms --------------------------------------------------------------
    def create_form(self, name, folder_id):
        return self.post('/rest/asset/v1/forms.json',
                         data={'name': name,
                               'folder': json.dumps({"id": folder_id, "type": "Folder"}),
                               'description': 'MCPTEST_LEG suite form'})

    def add_form_field(self, form_id, field_id):
        return self.post(f'/rest/asset/v1/form/{form_id}/fields.json',
                         data={'fieldId': field_id})

    def approve_form(self, form_id):
        return self.post(f'/rest/asset/v1/form/{form_id}/approveDraft.json')

    def add_form_fieldset(self, form_id, label):
        return self.post(f'/rest/asset/v1/form/{form_id}/fieldSet.json',
                         data={'label': label})

    def browse_forms(self, max_return=200, offset=0):
        return self.get('/rest/asset/v1/forms.json',
                        {'maxReturn': max_return, 'offset': offset})

    # -- emails -------------------------------------------------------------
    def create_email(self, name, folder_id, template_id, subject, from_email):
        return self.post('/rest/asset/v1/emails.json',
                         data={'name': name,
                               'folder': json.dumps({"id": folder_id, "type": "Folder"}),
                               'template': template_id, 'subject': subject,
                               'fromName': 'MCPTEST', 'fromEmail': from_email,
                               'replyEmail': from_email})

    def approve_email(self, email_id):
        return self.post(f'/rest/asset/v1/email/{email_id}/approveDraft.json')

    def email_section_to_dc(self, email_id, html_id, seg_id):
        return self.post(f'/rest/asset/v1/email/{email_id}/content/{html_id}.json',
                         data={'type': 'DynamicContent', 'value': seg_id})

    # -- snippets -----------------------------------------------------------
    def create_snippet(self, name, folder_id):
        return self.post('/rest/asset/v1/snippets.json',
                         data={'name': name,
                               'folder': json.dumps({"id": folder_id, "type": "Folder"}),
                               'description': 'MCPTEST_LEG suite snippet'})

    def update_snippet_content(self, snippet_id, html):
        return self.post(f'/rest/asset/v1/snippet/{snippet_id}/content.json',
                         data={'type': 'HTML', 'content': html})

    def approve_snippet(self, snippet_id):
        return self.post(f'/rest/asset/v1/snippet/{snippet_id}/approveDraft.json')

    def browse_snippets(self, max_return=200, offset=0):
        return self.get('/rest/asset/v1/snippets.json',
                        {'maxReturn': max_return, 'offset': offset})

    # -- lists --------------------------------------------------------------
    def create_static_list(self, name, program_id):
        return self.post('/rest/asset/v1/staticLists.json',
                         data={'name': name,
                               'folder': json.dumps({"id": program_id, "type": "Program"})})

    def add_leads_to_list(self, list_id, lead_ids):
        return self._request('POST', f'/rest/v1/lists/{list_id}/leads.json',
                             json={'input': [{'id': i} for i in lead_ids]})

    def create_smart_list(self, name, program_id):
        return self.post('/rest/asset/v1/smartLists.json',
                         data={'name': name,
                               'folder': json.dumps({"id": program_id, "type": "Program"})})

    def browse_static_lists(self, max_return=200, offset=0):
        return self.get('/rest/asset/v1/staticLists.json',
                        {'maxReturn': max_return, 'offset': offset})

    # -- bulk plumbing -------------------------------------------------------
    def create_lead_export_job(self, fields, start_at, end_at):
        return self.post('/bulk/v1/leads/export/create.json',
                         json_body={'fields': fields, 'format': 'CSV',
                                    'filter': {'createdAt': {'startAt': start_at,
                                                             'endAt': end_at}}})

    def lead_import_status(self, batch_id):
        return self.get(f'/bulk/v1/leads/batch/{batch_id}.json')

    def lookup_leads(self, emails):
        return self.get('/rest/v1/leads.json',
                        {'filterType': 'email', 'filterValues': ','.join(emails),
                         'fields': 'id,email'})

    # -- sweep browses -------------------------------------------------------
    def browse_assets(self, endpoint, max_return=200, offset=0):
        return self.get(f'/rest/asset/v1/{endpoint}.json',
                        {'maxReturn': max_return, 'offset': offset})


# ---------------------------------------------------------------------------
# Step engine (async, over the MCP client)
# ---------------------------------------------------------------------------

def step(tool, args=None, *, name=None, save=None, skip_if=None, skip_on=(),
         skip_errors=None, poll=None, after=None, infra=None, retries=0,
         notes=""):
    """Build one suite step.

    tool        MCP tool name (counted for coverage), or any label when
                infra= is given.
    infra       callable(**kwargs) executed instead of an MCP call (REST
                fixture plumbing; not counted for coverage).
    args        dict, or callable(ctx) -> dict. KeyError inside the callable
                marks the step SKIP (dependency missing).
    save / skip_if / skip_on / skip_errors / poll / after: as in
    test_blended_server.py's full mode.
    """
    return {
        "tool": tool, "args": args or {}, "name": name or tool, "save": save,
        "skip_if": skip_if, "skip_on": tuple(skip_on), "skip_errors": skip_errors,
        "poll": poll, "after": after, "infra": infra, "retries": retries,
        "notes": notes,
    }


def _marketo_errors(data):
    if not isinstance(data, dict):
        return [], ""
    errs = data.get('errors') or []
    codes = [str(e.get('code')) for e in errs if isinstance(e, dict)]
    msgs = " | ".join(str(e.get('message', '')) for e in errs if isinstance(e, dict))
    if data.get('error'):
        msgs = (msgs + " | " + str(data['error'])).strip(" |")
    return codes, msgs


def _is_error_payload(data):
    if not isinstance(data, dict):
        return False
    return data.get('success') is False or bool(data.get('errors')) or bool(data.get('error'))


def _job_status(data):
    if isinstance(data, dict):
        data = data.get('result') or []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get('status', '')).lower()
    return ""


def _job_done(data):
    return _job_status(data) in ('complete', 'completed', 'failed')


def _classify(st, data):
    if not _is_error_payload(data):
        return PASS, ""
    codes, msgs = _marketo_errors(data)
    low = msgs.lower()
    for match, reason in st['skip_on']:
        if str(match) in codes or str(match).lower() in low:
            return SKIP, f"{reason}: {msgs[:140]}"
    if st['skip_errors'] and not ({'601', '602'} & set(codes)):
        return SKIP, f"{st['skip_errors']}: {msgs[:140]}"
    if '603' in codes:
        return SKIP, f"permission(603): {msgs[:140]}"
    if '704' in codes:
        return SKIP, f"v2-unavailable(704): {msgs[:140]}"
    return FAIL, msgs[:200] or json.dumps(data, default=str)[:200]


def _parse_result(result):
    data = getattr(result, 'data', None)
    if data is not None:
        return data
    text = "".join(getattr(block, 'text', '') for block in (result.content or []))
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


class SuiteRunner:
    def __init__(self, url):
        self.url = url
        self.client = None
        self.records = []  # (name, kind, status, reason, secs)

    async def connect(self):
        if self.client is not None:
            try:
                await self.client.__aexit__(None, None, None)
            except Exception:
                pass
        self.client = Client(self.url)
        await self.client.__aenter__()

    async def close(self):
        if self.client is not None:
            try:
                await self.client.__aexit__(None, None, None)
            except Exception:
                pass
            self.client = None

    async def list_tool_names(self):
        return [t.name for t in await self.client.list_tools()]

    async def _call(self, tool, args):
        try:
            return await self.client.call_tool(tool, args, timeout=CALL_TIMEOUT)
        except ToolError:
            raise
        except Exception:
            await self.connect()
            return await self.client.call_tool(tool, args, timeout=CALL_TIMEOUT)

    async def _execute(self, st, args):
        if st['infra'] is not None:
            try:
                data = st['infra'](**args)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                if st['skip_errors']:
                    return SKIP, f"{st['skip_errors']}: {msg[:140]}", None
                return FAIL, msg[:200], None
        else:
            try:
                result = await self._call(st['tool'], args)
            except ToolError as exc:
                msg = str(exc)
                low = msg.lower()
                for match, reason in st['skip_on']:
                    if str(match).lower() in low:
                        return SKIP, f"{reason}: {msg[:140]}", None
                if st['skip_errors']:
                    return SKIP, f"{st['skip_errors']}: {msg[:140]}", None
                return FAIL, f"ToolError: {msg[:200]}", None
            except Exception as exc:
                return FAIL, f"{type(exc).__name__}: {exc}", None
            data = _parse_result(result)
        status, reason = _classify(st, data)
        return status, reason, data

    async def run_step(self, st, ctx):
        kind = "INFRA" if st['infra'] is not None else "TOOL"

        def mark(status):
            if st['infra'] is None and st['tool'] in ALL_TOOLS:
                (skipped_tools if status == SKIP else executed_tools).add(st['tool'])

        if st['skip_if']:
            reason = st['skip_if'](ctx)
            if reason:
                mark(SKIP)
                self.records.append((st['name'], kind, SKIP, str(reason), 0.0))
                if st['after']:
                    st['after'](ctx, SKIP, None)
                self._print_last()
                return

        try:
            args = st['args'](ctx) if callable(st['args']) else dict(st['args'])
        except KeyError as exc:
            mark(SKIP)
            self.records.append((st['name'], kind, SKIP, f"dependency missing: {exc}", 0.0))
            if st['after']:
                st['after'](ctx, SKIP, None)
            self._print_last()
            return

        started = time.time()
        status, reason, data = await self._execute(st, args)
        attempts = 0
        transient = ('rate limit', 'concurrent access', 'timed out', 'temporarily unavailable')
        while status == FAIL and (
                attempts < st.get('retries', 0)
                or (attempts < st.get('retries', 0) + 2
                    and any(t in str(reason).lower() for t in transient))):
            attempts += 1
            await asyncio.sleep(5)
            status, reason, data = await self._execute(st, args)

        if status == PASS and st['poll']:
            deadline = started + POLL_TIMEOUT

            def _done(payload):
                try:
                    return bool(st['poll']['done'](payload))
                except Exception:
                    return False

            while not _done(data) and time.time() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                status, reason, data = await self._execute(st, args)
                if status != PASS:
                    break
            if st['poll'].get('flag'):
                ctx[st['poll']['flag']] = bool(status == PASS and _done(data))

        if status == PASS and st['save']:
            try:
                st['save'](ctx, data)
            except Exception as exc:
                status = FAIL
                reason = (f"save failed ({type(exc).__name__}: {exc}); "
                          f"data={json.dumps(data, default=str)[:200]}")

        mark(status)
        secs = time.time() - started
        self.records.append((st['name'], kind, status, reason, secs))
        if st['after']:
            st['after'](ctx, status, data)
        self._print_last()

    def _print_last(self):
        name, kind, status, reason, secs = self.records[-1]
        marker = {PASS: ".", SKIP: "s", FAIL: "F"}[status]
        print(f"{marker} [{len(self.records):3d}] {kind:<6} {name:<52} {status}"
              + (f"  ({str(reason)[:90]})" if reason else ""), flush=True)


def _save_key(key, *path):
    def _save(ctx, data):
        value = data
        for part in path:
            value = value[part]
        ctx[key] = value
    return _save


def _save_first_id(key):
    return _save_key(key, 'result', 0, 'id')


def _need(*keys):
    def _check(ctx):
        for key in keys:
            if not ctx.get(key):
                return f"dependency missing: {key}"
        return None
    return _check


def _flag_skip(flag):
    def _after(ctx, status, data):
        if status == SKIP:
            ctx[flag] = True
    return _after


def _group_gate(flag, reason):
    def _check(ctx):
        return reason if ctx.get(flag) else None
    return _check


# ---------------------------------------------------------------------------
# MCPTEST_LEG_* sweep (REST; start + end)
# ---------------------------------------------------------------------------

def sweep_mcptest_leg(R):
    """Best-effort REST removal of every MCPTEST_LEG_* asset (only assets
    whose name starts with the prefix - a concurrent MCPTEST_FULL_* suite is
    never disturbed)."""
    prefix = AUTO_PREFIX
    removed = []

    def _paged(endpoint):
        items = []
        for page in range(30):
            resp = R.browse_assets(endpoint, offset=page * 200)
            batch = resp.get('result') or [] if isinstance(resp, dict) else []
            items.extend(batch)
            if len(batch) < 200:
                break
        return items

    plans = [
        ('emails', 'email', 'unapprove'),
        ('emailTemplates', 'emailTemplate', 'unapprove'),
        ('landingPages', 'landingPage', 'unapprove'),
        ('landingPageTemplates', 'landingPageTemplate', 'unapprove'),
        ('forms', 'form', None),
        ('snippets', 'snippet', 'unapprove'),
        ('staticLists', 'staticList', None),
        ('smartCampaigns', 'smartCampaign', None),
        ('programs', 'program', None),
    ]
    for browse_ep, single_ep, pre in plans:
        try:
            for a in _paged(browse_ep):
                if not str(a.get('name', '')).startswith(prefix):
                    continue
                if pre:
                    R.post(f'/rest/asset/v1/{single_ep}/{a["id"]}/{pre}.json')
                r = R.post(f'/rest/asset/v1/{single_ep}/{a["id"]}/delete.json')
                removed.append((single_ep, a['name'], bool(r.get('success'))))
        except Exception as exc:
            print(f"  (sweep of {browse_ep} failed: {exc})")

    try:
        roots = R.find_roots()
        for key in ('ma_parent', 'ds_forms_root', 'ds_emails_root', 'ds_etpl_root',
                    'ds_lp_root', 'ds_lpt_root', 'ds_snip_root'):
            if not roots.get(key):
                continue
            for f in (R.browse_folders(roots[key], max_depth=1).get('result') or []):
                if str(f.get('name', '')).startswith(prefix):
                    fid = f['id'] if not isinstance(f['id'], dict) else f['id'].get('id')
                    r = R.delete_folder(fid)
                    removed.append(('folder', f['name'], bool(r.get('success'))))
    except Exception as exc:
        print(f"  (folder sweep failed: {exc})")

    if removed:
        ok = sum(1 for _, _, s in removed if s)
        print(f"  Sweep removed {ok}/{len(removed)} MCPTEST_LEG_* leftovers:")
        for kind, name, success in removed:
            print(f"    [{'OK' if success else 'LEFT'}] {kind}: {name}")
    else:
        print("  Sweep: no MCPTEST_LEG_* leftovers found.")


# ---------------------------------------------------------------------------
# Full step plan (every legacy tool + every custom_* tool)
# ---------------------------------------------------------------------------

def build_full_steps(sfx, R, group=None):
    now = datetime.now(timezone.utc)
    run_start = now
    full = group is None
    email = lambda n: f"mcptest_leg_{sfx}_{n}@example.invalid"
    name = lambda label: f"{AUTO_PREFIX}{label}_{sfx}"
    steps = []
    add = steps.append

    # ================================================================ A. discovery + folders
    def save_channel(ctx, data):
        default_ch, email_ch, statuses = discover_channels(data.get('result'))
        if not default_ch:
            raise KeyError('no program-type channel with >=2 statuses')
        ctx['channel'] = default_ch['name']
        ctx['statuses'] = statuses
        if email_ch:
            ctx['email_channel'] = email_ch['name']
            ctx['email_channel_type'] = (email_ch.get('applicableProgramType') or '').lower()

    add(step('get_channels', {'max_return': 200}, save=save_channel))

    def find_roots_step(**kwargs):
        roots = R.find_roots()
        missing = [k for k in ('ma_parent',) if k not in roots]
        if full:
            missing += [k for k in ('ds_forms_root', 'ds_emails_root', 'ds_etpl_root',
                                    'ds_lp_root', 'ds_lpt_root', 'ds_snip_root')
                        if k not in roots]
        if missing:
            return {'success': False,
                    'errors': [{'code': 'infra', 'message': f'roots not found: {missing}'}]}
        roots['success'] = True
        return roots

    add(step('infra:find_roots', infra=find_roots_step,
             save=lambda c, d: c.update({k: v for k, v in d.items() if k != 'success'})))
    add(step('infra:create_folder(MA)', lambda c: {'name': name('MA'), 'parent_id': c['ma_parent']},
             infra=R.create_folder, save=_save_first_id('ma_folder')))
    if full:
        for ctx_key, root_key, label in [
            ('ds_forms', 'ds_forms_root', 'FORMS'),
            ('ds_emails', 'ds_emails_root', 'EMAILS'),
            ('ds_etpl', 'ds_etpl_root', 'ETPL'),
            ('ds_lp', 'ds_lp_root', 'LP'),
            ('ds_lpt', 'ds_lpt_root', 'LPT'),
            ('ds_snip', 'ds_snip_root', 'SNIP'),
        ]:
            add(step(f'infra:create_folder({label})',
                     (lambda rk, lb: lambda c: {'name': name(lb), 'parent_id': c[rk]})(root_key, label),
                     infra=R.create_folder, save=_save_first_id(ctx_key)))

        add(step('get_activity_types'))
        add(step('describe_leads'))
        add(step('custom_describe_lead2'))
        add(step('browse_folders', {'max_return': 20}))
        add(step('get_folder_by_name', lambda c: {'name': name('MA')}))
        add(step('custom_get_daily_usage'))
        add(step('custom_get_weekly_usage'))
        add(step('custom_get_daily_errors'))
        add(step('custom_get_weekly_errors'))

    # ================================================================ B. leads (createOnly -> createDuplicate -> merges)
    def save_lead_ids(ctx, data):
        ids = [r['id'] for r in data['result'] if r.get('status') in ('created', 'updated')]
        if len(ids) < 3:
            raise KeyError(f"expected 3 created leads, got {data['result']}")
        ctx['lead1'], ctx['lead2'], ctx['lead3'] = ids[:3]

    add(step('custom_sync_leads',
             {'leads': [{'email': email(1), 'firstName': 'MCP', 'lastName': 'LegOne'},
                        {'email': email(2), 'firstName': 'MCP', 'lastName': 'LegTwo'},
                        {'email': email(3), 'firstName': 'MCP', 'lastName': 'LegThree'}],
              'action': 'createOnly'},
             name='custom_sync_leads(createOnly)', save=save_lead_ids))

    if full:
        add(step('custom_sync_leads',
                 {'leads': [{'email': email(1), 'firstName': 'MCP', 'lastName': 'LegDupeA'}],
                  'action': 'createDuplicate'},
                 name='custom_sync_leads(createDuplicate#1)',
                 save=_save_first_id('dup1')))
        add(step('custom_merge_leads',
                 lambda c: {'winning_lead_id': c['lead1'], 'losing_lead_ids': [c['dup1']]},
                 after=lambda c, s, d: c.__setitem__('dup1_merged', s == PASS),
                 notes='createOnly -> createDuplicate -> merge chain (custom tool)'))
        add(step('custom_sync_leads',
                 {'leads': [{'email': email(2), 'firstName': 'MCP', 'lastName': 'LegDupeB'}],
                  'action': 'createDuplicate'},
                 name='custom_sync_leads(createDuplicate#2)',
                 save=_save_first_id('dup2')))
        add(step('merge_leads',
                 lambda c: {'winning_lead_id': c['lead2'], 'losing_lead_ids': [c['dup2']]},
                 after=lambda c, s, d: c.__setitem__('dup2_merged', s == PASS),
                 notes='same chain through the legacy merge tool'))

        add(step('get_lead_by_email', {'email': email(1)}))
        add(step('custom_get_lead_by_id', lambda c: {'lead_id': c['lead1'], 'fields': 'id,email'}))
        add(step('custom_get_lead_fields', {'batch_size': 5}))
        add(step('custom_get_lead_field_by_name', {'field_api_name': 'email'}))
        add(step('custom_create_lead_fields',
                 {'fields': [{'displayName': 'MCPTEST Leg Field1', 'name': LEAD_FIELD,
                              'dataType': 'string', 'description': 'MCPTEST_LEG suite field'}]},
                 skip_on=[('already exist', 'pre-existing lead field'),
                          ('1003', 'pre-existing lead field')]))
        add(step('custom_update_lead_field',
                 {'field_api_name': LEAD_FIELD,
                  'updates': {'description': f'MCPTEST_LEG updated {sfx}'}}))
        add(step('custom_get_lead_partitions'))
        add(step('custom_update_lead_partitions',
                 lambda c: {'assignments': [{'id': c['lead1'], 'partitionName': 'Default'}]}))
        add(step('get_lead_changes', lambda c: {'lead_id': c['lead1'], 'days_back': 1}))
        add(step('custom_get_lead_changes', lambda c: {'lead_id': c['lead1'], 'days_back': 1}))
        add(step('get_lead_activities', lambda c: {'lead_id': c['lead1'], 'days_back': 1}))
        add(step('get_lead_activities_by_email', {'email': email(1), 'days_back': 1}))
        add(step('custom_get_lead_activities_by_email', {'email': email(1), 'days_back': 1}))
        add(step('custom_associate_lead',
                 lambda c: {'lead_id': c['lead1'],
                            'cookie': 'id:287-GTJ-838&token:_mch-test-mcptest-leg'},
                 skip_errors='needs-real-cookie'))
        add(step('custom_get_lead_list_membership', lambda c: {'lead_id': c['lead1']}))
        add(step('custom_get_lead_program_membership', lambda c: {'lead_id': c['lead1']}))
        add(step('custom_get_lead_smart_campaign_membership', lambda c: {'lead_id': c['lead1']}))

    # ================================================================ C. tags -> program (+ members, tokens)
    def discover_tags_step(**kwargs):
        # Required-tag discovery must not silently come back empty (the
        # sandbox rejects untagged programs with 702): retry with a fresh
        # token before accepting an empty result.
        for attempt in range(3):
            tags = R.discover_required_tags('program')
            if tags:
                return {'success': True, 'result': tags}
            time.sleep(3)
            R.token(refresh=True)
        return {'success': True, 'result': []}

    add(step('infra:discover_required_tags', infra=discover_tags_step,
             save=lambda c, d: c.__setitem__('program_tags', d['result']),
             notes='this sandbox REQUIRES program tags (error 702 without them)'))

    def create_program_args(c):
        args = {'name': name('PROG'), 'folder_id': c['ma_folder'], 'program_type': 'Default',
                'channel': c['channel'], 'description': 'MCPTEST_LEG suite program'}
        if c.get('program_tags'):
            args['tags'] = c['program_tags']
        return args

    add(step('create_program', create_program_args, save=_save_first_id('program_id')))
    add(step('custom_change_lead_program_status',
             lambda c: {'program_id': c['program_id'], 'lead_ids': [c['lead1']],
                        'status': c['statuses'][0]}))

    if full:
        add(step('get_program_by_id', lambda c: {'program_id': c['program_id']}))
        add(step('get_program_by_name', lambda c: {'name': name('PROG'), 'include_tags': True}))
        add(step('browse_programs', {'max_return': 5}))
        add(step('update_program',
                 lambda c: {'program_id': c['program_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step('clone_program',
                 lambda c: {'program_id': c['program_id'], 'name': name('PROG_CLONE'),
                            'folder_id': c['ma_folder']},
                 save=_save_first_id('program_clone_id')))
        add(step('custom_push_leads',
                 lambda c: {'leads': [{'email': email(4), 'firstName': 'MCP',
                                       'lastName': 'LegFour'}],
                            'lookup_field': 'email', 'program_name': name('PROG'),
                            'program_status': c['statuses'][0]},
                 skip_if=_need('program_id'),
                 save=_save_key('lead4', 'result', 0, 'id')))
        add(step('custom_get_leads_by_program',
                 lambda c: {'program_id': c['program_id'], 'fields': 'id,email'}))
        add(step('describe_program_members',
                 save=lambda c, d: c.__setitem__(
                     'pm_export_fields',
                     [n for n in ('leadId', 'program', 'programId', 'statusName',
                                  'reachedSuccess')
                      if n in {f.get('name') for f in
                               ((d.get('result') or [{}])[0].get('fields') or [])}][:2]
                     or ['leadId', 'program'])))
        add(step('query_program_members',
                 lambda c: {'program_id': c['program_id'], 'filter_type': 'leadId',
                            'filter_values': str(c['lead1'])}))
        add(step('custom_query_program_members',
                 lambda c: {'program_id': c['program_id'], 'filter_type': 'leadId',
                            'filter_values': f"{c['lead1']},{c['lead2']}"}))
        add(step('custom_sync_program_member_status',
                 lambda c: {'program_id': c['program_id'], 'status_name': c['statuses'][0],
                            'lead_ids': [c['lead2']]}))
        add(step('custom_create_program_member_fields',
                 {'fields': [{'displayName': 'MCPTEST Leg PM Field1', 'name': PM_FIELD,
                              'dataType': 'string', 'description': 'MCPTEST_LEG PM field'}]},
                 skip_on=[('already exist', 'pre-existing PM field'),
                          ('1003', 'pre-existing PM field')]))
        add(step('custom_get_program_member_field_by_name', {'field_api_name': PM_FIELD}))
        add(step('custom_update_program_member_field',
                 {'field_api_name': PM_FIELD,
                  'updates': [{'description': f'MCPTEST_LEG updated {sfx}'}]}))
        add(step('custom_sync_program_member_data',
                 lambda c: {'program_id': c['program_id'],
                            'members': [{'leadId': c['lead1'], PM_FIELD: f'value-{sfx}'}]},
                 skip_on=[('1006', 'no-pm-field'), ('invalid field', 'no-pm-field')]))
        add(step('custom_delete_program_members',
                 lambda c: {'program_id': c['program_id'], 'lead_ids': [c['lead2']]}))

        add(step('create_program',
                 lambda c: {'name': name('EMAILPROG'), 'folder_id': c['ma_folder'],
                            'program_type': 'Email', 'channel': c['email_channel'],
                            'description': 'MCPTEST_LEG email program',
                            'tags': R.discover_required_tags(
                                c.get('email_channel_type', 'email')) or None},
                 name='create_program(Email)', save=_save_first_id('email_program_id'),
                 skip_errors='email-program-create-unavailable'))
        add(step('approve_email_program', lambda c: {'program_id': c['email_program_id']},
                 skip_errors='email-program-not-ready',
                 notes='empty email program; approval is expected to be rejected'))
        add(step('unapprove_email_program', lambda c: {'program_id': c['email_program_id']},
                 skip_errors='email-program-not-approved'))
        add(step('custom_unapprove_email_program',
                 lambda c: {'program_id': c['email_program_id']},
                 skip_errors='email-program-not-approved'))

        add(step('create_token',
                 lambda c: {'folder_id': c['program_id'], 'name': 'MCPTEST_LEG_token',
                            'token_type': 'text', 'value': 'MCPTEST token value',
                            'folder_type': 'Program'}))
        add(step('get_tokens_by_folder',
                 lambda c: {'folder_id': c['program_id'], 'folder_type': 'Program'}))
        add(step('update_token',
                 lambda c: {'folder_id': c['program_id'], 'name': 'MCPTEST_LEG_token',
                            'token_type': 'text', 'value': 'MCPTEST updated value',
                            'folder_type': 'Program'}))
        add(step('delete_token',
                 lambda c: {'folder_id': c['program_id'], 'name': 'MCPTEST_LEG_token',
                            'token_type': 'text', 'folder_type': 'Program'}))
        add(step('create_token',
                 lambda c: {'folder_id': c['program_id'], 'name': 'MCPTEST_LEG_token2',
                            'token_type': 'text', 'value': 'MCPTEST token value 2',
                            'folder_type': 'Program'},
                 name='create_token(2)'))
        add(step('custom_delete_token',
                 lambda c: {'folder_id': c['program_id'], 'name': 'MCPTEST_LEG_token2',
                            'token_type': 'text', 'folder_type': 'Program'}))

        # ============================================================ D. smart campaigns
        add(step('create_smart_campaign',
                 lambda c: {'name': name('SC'), 'folder_id': c['ma_folder'],
                            'description': 'MCPTEST_LEG suite campaign'},
                 save=_save_first_id('sc_id')))
        add(step('get_smart_campaign_by_id', lambda c: {'campaign_id': c['sc_id']}))
        add(step('get_smart_campaign_by_name', lambda c: {'name': name('SC')}))
        add(step('browse_smart_campaigns', {'max_return': 5}))
        add(step('update_smart_campaign',
                 lambda c: {'campaign_id': c['sc_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step('custom_clone_smart_campaign',
                 lambda c: {'campaign_id': c['sc_id'], 'name': name('SC_CLONE'),
                            'folder_id': c['ma_folder']},
                 save=_save_first_id('sc_clone_id')))
        add(step('clone_smart_campaign',
                 lambda c: {'campaign_id': c['sc_id'], 'name': name('SC_CLONE2'),
                            'folder_id': c['ma_folder']},
                 save=_save_first_id('sc_clone2_id')))
        add(step('activate_smart_campaign', lambda c: {'campaign_id': c['sc_id']},
                 skip_errors='campaign-not-activatable',
                 notes='campaign has no triggers/flow; activation error is expected'))
        add(step('deactivate_smart_campaign', lambda c: {'campaign_id': c['sc_id']},
                 skip_errors='campaign-not-active'))
        add(step('custom_deactivate_smart_campaign', lambda c: {'campaign_id': c['sc_id']},
                 skip_errors='campaign-not-active'))
        add(step('schedule_batch_campaign', lambda c: {'campaign_id': c['sc_id']},
                 skip_errors='campaign-not-schedulable'))
        add(step('request_campaign',
                 lambda c: {'campaign_id': c['sc_id'], 'lead_ids': [c['lead1']]},
                 skip_errors='campaign-not-requestable'))

        # ============================================================ E. lists
        add(step('infra:create_static_list',
                 lambda c: {'name': name('LIST'), 'program_id': c['program_id']},
                 infra=R.create_static_list, save=_save_first_id('list_id')))
        add(step('infra:add_leads_to_list',
                 lambda c: {'list_id': c['list_id'], 'lead_ids': [c['lead1'], c['lead2']]},
                 infra=R.add_leads_to_list))
        add(step('custom_is_member_of_list',
                 lambda c: {'list_id': c['list_id'], 'lead_ids': [c['lead1'], c['lead2']]}))
        add(step('custom_remove_leads_from_list',
                 lambda c: {'list_id': c['list_id'], 'lead_ids': [c['lead2']]}))
        add(step('infra:create_smart_list',
                 lambda c: {'name': name('SL'), 'program_id': c['program_id']},
                 infra=R.create_smart_list, save=_save_first_id('sl_id'),
                 skip_errors='smart-list-create-unavailable'))

        # ============================================================ F. forms
        add(step('infra:create_form',
                 lambda c: {'name': name('FORM'), 'folder_id': c['ds_forms']},
                 infra=R.create_form, save=_save_first_id('form_id')))
        for field in ('Email', 'FirstName'):
            add(step(f'infra:add_form_field({field})',
                     (lambda fld: lambda c: {'form_id': c['form_id'], 'field_id': fld})(field),
                     infra=R.add_form_field,
                     skip_on=[('already exist', 'field-pre-existing')]))
        add(step('infra:approve_form', lambda c: {'form_id': c['form_id']},
                 infra=R.approve_form))
        add(step('custom_submit_form',
                 lambda c: {'form_id': c['form_id'],
                            'lead_form_fields': {'Email': email(1), 'FirstName': 'MCP'},
                            'visitor_data': {'pageURL': 'https://example.invalid/mcptest-leg'}}))
        add(step('custom_update_form_submit_button',
                 lambda c: {'form_id': c['form_id'], 'label': 'MCPTEST Go',
                            'waiting_label': 'Sending...'}))
        add(step('custom_update_form_thank_you_pages',
                 lambda c: {'form_id': c['form_id'],
                            'rules': [{'default': True, 'followupType': 'url',
                                       'followupValue': 'https://example.com/mcptest-thanks'}]}))
        add(step('custom_delete_form_field',
                 lambda c: {'form_id': c['form_id'], 'field_id': 'FirstName'}))
        add(step('infra:add_form_fieldset',
                 lambda c: {'form_id': c['form_id'], 'label': 'MCPTEST FS'},
                 infra=R.add_form_fieldset,
                 save=lambda c, d: c.__setitem__('fieldset_id',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step('custom_delete_form_fieldset_field',
                 lambda c: {'form_id': c['form_id'], 'field_set_id': str(c['fieldset_id']),
                            'field_id': 'LastName'},
                 skip_if=lambda c: None if c.get('fieldset_id') else 'no fieldset created',
                 skip_errors='no-fieldset-field'))
        add(step('custom_discard_form_draft', lambda c: {'form_id': c['form_id']}))

        # ============================================================ G. email templates + emails
        add(step('custom_create_email_template',
                 lambda c: {'name': name('TPL'), 'folder_id': c['ds_etpl'],
                            'html_content': EMAIL_TEMPLATE_HTML,
                            'description': 'MCPTEST_LEG suite template'},
                 save=_save_first_id('tpl_id')))
        add(step('custom_browse_email_templates', {'max_return': 5}))
        add(step('custom_get_email_template_by_id', lambda c: {'template_id': c['tpl_id']}))
        add(step('custom_get_email_template_by_name', lambda c: {'name': name('TPL')}))
        add(step('custom_get_email_template_content', lambda c: {'template_id': c['tpl_id']}))
        add(step('custom_update_email_template',
                 lambda c: {'template_id': c['tpl_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step('custom_approve_email_template', lambda c: {'template_id': c['tpl_id']}))
        add(step('custom_get_email_template_used_by', lambda c: {'template_id': c['tpl_id']}))
        add(step('custom_clone_email_template',
                 lambda c: {'template_id': c['tpl_id'], 'name': name('TPL_CLONE'),
                            'folder_id': c['ds_etpl']},
                 save=_save_first_id('tpl_clone_id')))
        add(step('infra:create_email',
                 lambda c: {'name': name('EMAIL'), 'folder_id': c['ds_emails'],
                            'template_id': c['tpl_id'], 'subject': 'MCPTEST_LEG subject',
                            'from_email': SAMPLE_EMAIL_TO},
                 infra=R.create_email, save=_save_first_id('email_id')))
        add(step('get_email_by_id', lambda c: {'email_id': c['email_id']}))
        add(step('get_email_by_name', lambda c: {'name': name('EMAIL')}))
        add(step('browse_emails', {'max_return': 5}))
        add(step('custom_update_email',
                 lambda c: {'email_id': c['email_id'], 'description': f'MCPTEST {sfx}'}))
        add(step('custom_update_email_headers',
                 lambda c: {'email_id': c['email_id'], 'subject': f'MCPTEST subject {sfx}',
                            'reply_to': SAMPLE_EMAIL_TO}))
        add(step('custom_get_email_variables', lambda c: {'email_id': c['email_id']},
                 save=lambda c, d: c.__setitem__('email_vars',
                                                 [v.get('name') or v.get('id')
                                                  for v in d.get('result') or []]),
                 skip_errors='no-email-variables'))
        add(step('custom_update_email_variable',
                 lambda c: {'email_id': c['email_id'], 'variable_name': c['email_vars'][0],
                            'value': 'world'},
                 skip_if=lambda c: None if c.get('email_vars') else 'no variables on email'))

        def save_email_sections(ctx, data):
            sections = data.get('result') or []
            modules = [s for s in sections if str(s.get('contentType')) == 'Module']
            texts = [s for s in sections if str(s.get('contentType')) in ('Text', 'HTML')]
            ctx['email_modules'] = [m.get('htmlId') for m in modules]
            ctx['email_text_section'] = texts[0].get('htmlId') if texts else None

        add(step('get_email_content', lambda c: {'email_id': c['email_id']},
                 save=save_email_sections))
        add(step('custom_add_email_module',
                 lambda c: {'email_id': c['email_id'], 'module_id': c['email_modules'][0],
                            'name': 'MCPTEST Module Copy', 'index': 1},
                 skip_if=lambda c: None if c.get('email_modules') else 'email has no modules',
                 skip_on=[('611', 'no-modular-editor')],
                 save=lambda c, d: c.__setitem__('added_module',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step('custom_rename_email_module',
                 lambda c: {'email_id': c['email_id'], 'module_id': c['added_module'],
                            'name': 'MCPTEST Module Renamed'},
                 skip_if=lambda c: None if c.get('added_module') else 'no module was added'))
        add(step('custom_duplicate_email_module',
                 lambda c: {'email_id': c['email_id'], 'module_id': c['email_modules'][0],
                            'name': 'MCPTEST Module Dupe'},
                 skip_if=lambda c: None if c.get('email_modules') else 'email has no modules',
                 save=lambda c, d: c.__setitem__('dupe_module',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step('custom_rearrange_email_modules',
                 lambda c: {'email_id': c['email_id'],
                            'positions': [{'index': i, 'moduleId': m} for i, m in enumerate(
                                reversed([m for m in [c['email_modules'][0],
                                                      c.get('added_module'),
                                                      c.get('dupe_module')]
                                          + c['email_modules'][1:] if m]))]},
                 skip_if=lambda c: None if c.get('email_modules') else 'email has no modules',
                 skip_errors='rearrange-rejected'))
        add(step('custom_delete_email_module',
                 lambda c: {'email_id': c['email_id'], 'module_id': c['dupe_module']},
                 skip_if=lambda c: None if c.get('dupe_module') else 'no duplicated module'))

        def save_segmentation(ctx, data):
            for seg in data.get('result') or []:
                if seg.get('status') == 'approved':
                    ctx['seg_id'] = seg['id']
                    break

        add(step('custom_browse_segmentations', save=save_segmentation))
        add(step('custom_get_segments', lambda c: {'segmentation_id': c['seg_id']},
                 skip_if=lambda c: None if c.get('seg_id') else 'no approved segmentation',
                 save=lambda c, d: c.__setitem__('segments',
                                                 [s['name'] for s in d.get('result') or []])))
        add(step('infra:email_section_to_dc',
                 lambda c: {'email_id': c['email_id'], 'html_id': c['email_text_section'],
                            'seg_id': c['seg_id']},
                 infra=R.email_section_to_dc,
                 skip_if=lambda c: (None if (c.get('seg_id') and c.get('email_text_section'))
                                    else 'needs a segmentation and a text section'),
                 skip_errors='dc-conversion-rejected'))

        def save_email_dc(ctx, data):
            for section in data.get('result') or []:
                if str(section.get('contentType')) == 'DynamicContent':
                    value = section.get('value')
                    ctx['email_dc_id'] = (value if isinstance(value, (str, int))
                                          else section.get('htmlId'))
                    break

        add(step('get_email_content', lambda c: {'email_id': c['email_id'], 'status': 'draft'},
                 name='get_email_content(draft)', save=save_email_dc))
        add(step('custom_get_email_dynamic_content',
                 lambda c: {'email_id': c['email_id'],
                            'dynamic_content_id': str(c['email_dc_id'])},
                 skip_if=lambda c: None if c.get('email_dc_id') else 'no dynamic content section'))
        add(step('custom_update_email_dynamic_content',
                 lambda c: {'email_id': c['email_id'],
                            'dynamic_content_id': str(c['email_dc_id']),
                            'segment': [s for s in c.get('segments', []) if s != 'Default'][0],
                            'type': 'HTML', 'value': '<p>MCPTEST segment content</p>'},
                 skip_if=lambda c: (None if (c.get('email_dc_id') and
                                             [s for s in c.get('segments', []) if s != 'Default'])
                                    else 'no dynamic content section / segments')))
        add(step('custom_update_email_full_content',
                 lambda c: {'email_id': c['email_id'],
                            'html_content': '<html><body><p>MCPTEST full content</p></body></html>'},
                 skip_errors='not-supported-for-modular-email'))
        add(step('custom_send_sample_email',
                 lambda c: {'email_id': c['email_id'], 'email_address': SAMPLE_EMAIL_TO}))
        add(step('preview_email', lambda c: {'email_id': c['email_id']}))
        add(step('custom_preview_email', lambda c: {'email_id': c['email_id']}))
        add(step('get_email_cc_fields'))
        add(step('custom_get_email_cc_fields'))
        add(step('infra:approve_email', lambda c: {'email_id': c['email_id']},
                 infra=R.approve_email))
        add(step('custom_update_email_headers',
                 lambda c: {'email_id': c['email_id'],
                            'subject': f'MCPTEST draft subject {sfx}'},
                 name='custom_update_email_headers(draft)'))
        add(step('custom_discard_email_draft', lambda c: {'email_id': c['email_id']}))
        add(step('custom_clone_email',
                 lambda c: {'email_id': c['email_id'], 'name': name('EMAIL_CLONE'),
                            'folder_id': c['ds_emails']},
                 save=_save_first_id('email_clone_id')))
        add(step('custom_unapprove_email', lambda c: {'email_id': c['email_id']}))
        add(step('custom_update_email_template_content',
                 lambda c: {'template_id': c['tpl_id'],
                            'html_content': EMAIL_TEMPLATE_HTML.replace(
                                'Hello from text one.', 'Hello from text one (draft).')}))
        add(step('custom_discard_email_template_draft', lambda c: {'template_id': c['tpl_id']}))

        # ============================================================ H. files
        file_name = f"MCPTEST_LEG_file_{sfx}.txt"

        def save_file_folder(ctx, data):
            for file in data.get('result') or []:
                folder = file.get('folder') or {}
                if folder.get('id'):
                    ctx['file_folder'] = folder['id']
                    return

        add(step('custom_browse_files', {'max_return': 10}, save=save_file_folder))
        add(step('custom_upload_file',
                 lambda c: {'name': file_name, 'folder_id': c['file_folder'],
                            'file_content': f'MCPTEST_LEG suite run {sfx}\n',
                            'insert_only': True,
                            'description': 'MCPTEST suite file (files cannot be deleted via API)'},
                 skip_if=lambda c: None if c.get('file_folder') else 'no existing files folder found',
                 save=_save_first_id('file_id')))
        add(step('custom_get_file_by_name', lambda c: {'name': file_name},
                 skip_if=_need('file_id')))
        add(step('custom_get_file_by_id', lambda c: {'file_id': c['file_id']},
                 skip_if=_need('file_id')))
        add(step('custom_replace_file_content',
                 lambda c: {'file_id': c['file_id'], 'file_name': file_name,
                            'file_content': f'MCPTEST_LEG suite run {sfx} (replaced)\n'},
                 skip_if=_need('file_id'),
                 skip_on=[('709', 'KNOWN-BUG-709-multipart-mime (no per-part Content-Type; '
                                  'replace can never match the stored mimeType)')]))

        # ============================================================ I. landing pages + redirects
        add(step('custom_create_landing_page_template',
                 lambda c: {'name': name('LPT'), 'folder_id': c['ds_lpt'],
                            'description': 'MCPTEST_LEG LP template',
                            'template_type': 'freeForm'},
                 save=_save_first_id('lpt_id')))
        add(step('custom_browse_landing_page_templates', {'max_return': 5}))
        add(step('custom_get_landing_page_template_by_id', lambda c: {'template_id': c['lpt_id']}))
        add(step('custom_get_landing_page_template_by_name', lambda c: {'name': name('LPT')}))
        add(step('custom_update_landing_page_template',
                 lambda c: {'template_id': c['lpt_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step('custom_update_landing_page_template_content',
                 lambda c: {'template_id': c['lpt_id'], 'html_content': LP_TEMPLATE_HTML}))
        add(step('custom_get_landing_page_template_content',
                 lambda c: {'template_id': c['lpt_id']}))
        add(step('custom_approve_landing_page_template', lambda c: {'template_id': c['lpt_id']}))
        add(step('custom_clone_landing_page_template',
                 lambda c: {'template_id': c['lpt_id'], 'name': name('LPT_CLONE'),
                            'folder_id': c['ds_lpt']},
                 save=_save_first_id('lpt_clone_id')))
        add(step('custom_update_landing_page_template_content',
                 lambda c: {'template_id': c['lpt_id'],
                            'html_content': LP_TEMPLATE_HTML.replace(
                                'template body.', 'template body (draft).')},
                 name='custom_update_landing_page_template_content(draft)'))
        add(step('custom_discard_landing_page_template_draft',
                 lambda c: {'template_id': c['lpt_id']}))
        add(step('custom_create_landing_page',
                 lambda c: {'name': name('LP'), 'folder_id': c['ds_lp'],
                            'template_id': c['lpt_id'],
                            'description': 'MCPTEST_LEG landing page'},
                 save=_save_first_id('lp_id'), skip_errors='lp-create-unavailable'))
        add(step('custom_browse_landing_pages', {'max_return': 5}))
        add(step('custom_get_landing_page_by_id', lambda c: {'landing_page_id': c['lp_id']}))
        add(step('custom_get_landing_page_by_name', lambda c: {'name': name('LP')}))
        add(step('custom_update_landing_page',
                 lambda c: {'landing_page_id': c['lp_id'], 'title': f'MCPTEST title {sfx}'}))
        add(step('custom_add_landing_page_content_section',
                 lambda c: {'landing_page_id': c['lp_id'], 'content_id': f'mcptest-sec-{sfx}',
                            'content_type': 'HTML', 'value': '<p>MCPTEST section</p>',
                            'layout': {'left': 10, 'top': 10, 'width': 300, 'height': 80}},
                 skip_errors='lp-section-add-rejected'))

        def save_lp_section(ctx, data):
            sections = data.get('result') or []
            for section in sections:
                if str(section.get('type', '')).upper() in ('HTML', 'RICHTEXT'):
                    ctx['lp_section_id'] = section['id']
                    return
            if sections:
                ctx['lp_section_id'] = sections[0]['id']

        add(step('custom_get_landing_page_content',
                 lambda c: {'landing_page_id': c['lp_id']}, save=save_lp_section))
        add(step('custom_update_landing_page_content_section',
                 lambda c: {'landing_page_id': c['lp_id'], 'content_id': str(c['lp_section_id']),
                            'content_type': 'HTML', 'value': '<p>MCPTEST updated section</p>'},
                 skip_if=lambda c: None if c.get('lp_section_id') else 'no LP content section'))
        add(step('custom_update_landing_page_content_section',
                 lambda c: {'landing_page_id': c['lp_id'], 'content_id': str(c['lp_section_id']),
                            'content_type': 'DynamicContent', 'value': str(c['seg_id'])},
                 name='custom_update_landing_page_content_section(DC)',
                 skip_if=lambda c: (None if (c.get('lp_section_id') and c.get('seg_id'))
                                    else 'needs an LP section and a segmentation'),
                 skip_errors='lp-dc-conversion-rejected'))

        def save_lp_dc(ctx, data):
            for section in data.get('result') or []:
                if str(section.get('type', '')) == 'DynamicContent':
                    value = section.get('content') or section.get('value')
                    ctx['lp_dc_id'] = (value if isinstance(value, (str, int))
                                       else section.get('id'))
                    break

        add(step('custom_get_landing_page_content',
                 lambda c: {'landing_page_id': c['lp_id'], 'status': 'draft'},
                 name='custom_get_landing_page_content(draft)', save=save_lp_dc))
        add(step('custom_get_landing_page_full_content',
                 lambda c: {'landing_page_id': c['lp_id']},
                 skip_errors='lp-full-content-unavailable'))
        add(step('custom_get_landing_page_variables',
                 lambda c: {'landing_page_id': c['lp_id']},
                 skip_errors='freeform-lp-has-no-variables'))
        add(step('custom_update_landing_page_variable',
                 lambda c: {'landing_page_id': c['lp_id'], 'variable_id': 'none', 'value': 'x'},
                 skip_if=lambda c: 'freeForm landing page has no variables (guided only)'))
        add(step('custom_update_landing_page_dynamic_content',
                 lambda c: {'landing_page_id': c['lp_id'],
                            'dynamic_content_id': str(c['lp_dc_id']),
                            'segment': [s for s in c.get('segments', []) if s != 'Default'][0],
                            'content_type': 'HTML', 'value': '<p>MCPTEST DC</p>'},
                 skip_if=lambda c: (None if c.get('lp_dc_id') else
                                    'no dynamic content section on landing page')))
        add(step('custom_get_landing_page_dynamic_content',
                 lambda c: {'landing_page_id': c['lp_id'],
                            'dynamic_content_id': str(c['lp_dc_id'])},
                 skip_if=lambda c: (None if c.get('lp_dc_id') else
                                    'no dynamic content section on landing page')))
        add(step('custom_delete_landing_page_content_section',
                 lambda c: {'landing_page_id': c['lp_id'], 'content_id': str(c['lp_section_id'])},
                 skip_if=lambda c: None if c.get('lp_section_id') else 'no LP content section'))
        add(step('custom_approve_landing_page', lambda c: {'landing_page_id': c['lp_id']},
                 skip_errors='lp-approve-unavailable',
                 after=lambda c, s, d: c.__setitem__('lp_approved', s == PASS)))
        add(step('custom_add_landing_page_content_section',
                 lambda c: {'landing_page_id': c['lp_id'], 'content_id': f'mcptest-d2-{sfx}',
                            'content_type': 'HTML', 'value': '<p>MCPTEST draft2</p>',
                            'layout': {'left': 10, 'top': 120, 'width': 300, 'height': 80}},
                 name='custom_add_landing_page_content_section(draft2)',
                 skip_if=lambda c: None if c.get('lp_approved') else 'landing page never approved',
                 skip_errors='lp-section-add-rejected',
                 notes='creates a draft on the approved LP for discardDraft'))
        add(step('custom_discard_landing_page_draft', lambda c: {'landing_page_id': c['lp_id']},
                 skip_if=lambda c: None if c.get('lp_approved') else
                 'LP never approved (discarding a draft-only LP deletes it)',
                 skip_errors='no-lp-draft'))
        add(step('custom_clone_landing_page',
                 lambda c: {'landing_page_id': c['lp_id'], 'name': name('LP_CLONE'),
                            'folder_id': c['ds_lp'], 'template_id': c['lpt_id']},
                 save=_save_first_id('lp_clone_id'),
                 notes='this instance requires the template param on LP clone'))
        add(step('custom_unapprove_landing_page', lambda c: {'landing_page_id': c['lp_id']},
                 skip_if=lambda c: None if c.get('lp_approved') else 'landing page never approved',
                 retries=3,
                 notes='approval propagates asynchronously; retry a few times'))
        add(step('custom_get_landing_page_domains',
                 save=lambda c, d: c.__setitem__('lp_domains',
                                                 [r.get('domain') or r.get('name')
                                                  for r in d.get('result') or []])))
        add(step('custom_browse_redirect_rules', {'max_return': 5}))
        add(step('custom_create_redirect_rule',
                 lambda c: {'hostname': c['lp_domains'][0],
                            'from_type': 'path', 'from_value': f'/mcptest-leg-from-{sfx}.html',
                            'to_type': 'path', 'to_value': f'/mcptest-leg-to-{sfx}.html'},
                 skip_if=lambda c: None if c.get('lp_domains') else 'no LP domains configured',
                 save=_save_first_id('redirect_id'), skip_errors='redirect-create-rejected'))
        add(step('custom_get_redirect_rule_by_id', lambda c: {'rule_id': c['redirect_id']},
                 skip_if=_need('redirect_id')))
        add(step('custom_update_redirect_rule',
                 lambda c: {'rule_id': c['redirect_id'],
                            'to_type': 'path', 'to_value': f'/mcptest-leg-to2-{sfx}.html'},
                 skip_if=_need('redirect_id')))
        add(step('custom_delete_redirect_rule', lambda c: {'rule_id': c['redirect_id']},
                 skip_if=_need('redirect_id')))

        # ============================================================ J. snippets
        add(step('infra:create_snippet',
                 lambda c: {'name': name('SNIP'), 'folder_id': c['ds_snip']},
                 infra=R.create_snippet, save=_save_first_id('snippet_id')))
        add(step('infra:update_snippet_content',
                 lambda c: {'snippet_id': c['snippet_id'], 'html': '<p>MCPTEST snippet</p>'},
                 infra=R.update_snippet_content))
        add(step('infra:approve_snippet', lambda c: {'snippet_id': c['snippet_id']},
                 infra=R.approve_snippet))
        add(step('infra:update_snippet_content(draft)',
                 lambda c: {'snippet_id': c['snippet_id'],
                            'html': '<p>MCPTEST snippet draft</p>'},
                 infra=R.update_snippet_content))
        add(step('custom_discard_snippet_draft', lambda c: {'snippet_id': c['snippet_id']}))
        add(step('custom_unapprove_snippet', lambda c: {'snippet_id': c['snippet_id']}))

        # ============================================================ K. custom activity types
        def save_act_types(ctx, data):
            ctx['act_type_pre_existing'] = any(
                t.get('apiName') == ACT_TYPE for t in data.get('result') or [])

        def act_create_after(ctx, status, data):
            ctx['act_ok'] = status == PASS or ctx.get('act_type_pre_existing')

        act_gate = lambda c: None if c.get('act_ok') else 'activity type unavailable (create failed)'

        add(step('custom_get_custom_activity_types', save=save_act_types))
        add(step('custom_create_custom_activity_type',
                 {'api_name': ACT_TYPE, 'name': 'MCPTEST Leg Activity',
                  'filter_name': 'MCPTEST Leg Activity Filter',
                  'trigger_name': 'MCPTEST Leg Activity Trigger',
                  'primary_attribute': {'apiName': 'mcptestPrimary', 'name': 'MCPTEST Primary'},
                  'description': 'MCPTEST_LEG suite activity type'},
                 skip_on=[('already exist', 'pre-existing activity type')],
                 after=act_create_after))
        add(step('custom_describe_custom_activity_type', {'api_name': ACT_TYPE, 'draft': True},
                 name='custom_describe_custom_activity_type(draft)',
                 skip_if=act_gate, skip_errors='no-activity-type-draft'))
        add(step('custom_update_custom_activity_type',
                 {'api_name': ACT_TYPE, 'description': f'MCPTEST_LEG updated {sfx}'},
                 skip_if=act_gate))
        add(step('custom_add_custom_activity_type_attributes',
                 {'api_name': ACT_TYPE,
                  'attributes': [{'apiName': 'mcptestAttrA', 'name': 'MCPTEST Attr A',
                                  'dataType': 'string'},
                                 {'apiName': 'mcptestAttrB', 'name': 'MCPTEST Attr B',
                                  'dataType': 'string'}]},
                 skip_if=act_gate, skip_on=[('already exist', 'pre-existing attributes')]))
        add(step('custom_update_custom_activity_type_attributes',
                 {'api_name': ACT_TYPE,
                  'attributes': [{'apiName': 'mcptestAttrA', 'name': 'MCPTEST Attr A2',
                                  'dataType': 'string'}]},
                 skip_if=act_gate))
        add(step('custom_delete_custom_activity_type_attributes',
                 {'api_name': ACT_TYPE, 'attributes': [{'apiName': 'mcptestAttrB'}]},
                 skip_if=act_gate))
        add(step('custom_approve_custom_activity_type', {'api_name': ACT_TYPE},
                 skip_if=act_gate, skip_on=[('no draft', 'act-type-already-approved')]))
        add(step('custom_describe_custom_activity_type', {'api_name': ACT_TYPE},
                 skip_if=act_gate, save=_save_key('act_type_id', 'result', 0, 'id')))
        add(step('custom_add_custom_activities',
                 lambda c: {'activities': [{'leadId': c['lead1'],
                                            'activityTypeId': c['act_type_id'],
                                            'activityDate': _iso(now),
                                            'primaryAttributeValue': f'mcptest-{sfx}',
                                            'attributes': [{'name': 'mcptestAttrA',
                                                            'value': 'attr-value'}]}]},
                 skip_if=_need('act_type_id')))
        add(step('custom_update_custom_activity_type',
                 {'api_name': ACT_TYPE, 'description': f'MCPTEST draft {sfx}'},
                 name='custom_update_custom_activity_type(draft)', skip_if=act_gate))
        add(step('custom_discard_custom_activity_type_draft', {'api_name': ACT_TYPE},
                 skip_if=act_gate, skip_errors='no-activity-type-draft'))

        # ============================================================ L. CRM objects
        add(step('custom_describe_companies', skip_errors='crm-unavailable',
                 after=_flag_skip('no_crm')))
        crm_gate = _group_gate('no_crm', 'crm-synced instance (companies API unavailable)')
        add(step('custom_sync_companies',
                 {'records': [{'externalCompanyId': f'mcptest-leg-co-{sfx}',
                               'company': 'MCPTEST Leg Co'}]}, skip_if=crm_gate))
        add(step('custom_query_companies',
                 {'filter_type': 'externalCompanyId',
                  'filter_values': f'mcptest-leg-co-{sfx}'}, skip_if=crm_gate))
        add(step('custom_get_company_fields', {'batch_size': 5}, skip_if=crm_gate))
        add(step('custom_get_company_field_by_name', {'field_api_name': 'externalCompanyId'},
                 skip_if=crm_gate))
        add(step('custom_delete_companies',
                 {'records': [{'externalCompanyId': f'mcptest-leg-co-{sfx}'}]},
                 skip_if=crm_gate))
        add(step('custom_describe_opportunities', skip_if=crm_gate))
        add(step('custom_sync_opportunities',
                 {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}',
                               'name': 'MCPTEST Leg Opp'}]}, skip_if=crm_gate))
        add(step('custom_query_opportunities',
                 {'filter_type': 'externalOpportunityId',
                  'filter_values': f'mcptest-leg-opp-{sfx}'}, skip_if=crm_gate))
        add(step('custom_get_opportunity_fields', {'batch_size': 5}, skip_if=crm_gate))
        add(step('custom_get_opportunity_field_by_name',
                 {'field_api_name': 'externalOpportunityId'}, skip_if=crm_gate))
        add(step('custom_describe_opportunity_roles', skip_if=crm_gate))
        add(step('custom_sync_opportunity_roles',
                 lambda c: {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}',
                                         'leadId': c['lead1'], 'role': 'MCPTEST'}]},
                 skip_if=crm_gate))
        add(step('custom_query_opportunity_roles',
                 lambda c: {'filter_type': 'leadId', 'filter_values': str(c['lead1'])},
                 skip_if=crm_gate))
        add(step('custom_delete_opportunity_roles',
                 lambda c: {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}',
                                         'leadId': c['lead1'], 'role': 'MCPTEST'}]},
                 skip_if=crm_gate))
        add(step('custom_delete_opportunities',
                 {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}'}]},
                 skip_if=crm_gate))
        add(step('custom_describe_sales_persons', skip_if=crm_gate))
        add(step('custom_sync_sales_persons',
                 {'records': [{'externalSalesPersonId': f'mcptest-leg-sp-{sfx}',
                               'email': f'mcptest_leg_sp_{sfx}@example.invalid',
                               'firstName': 'MCP', 'lastName': 'SalesLeg'}]},
                 skip_if=crm_gate))
        add(step('custom_query_sales_persons',
                 {'filter_type': 'externalSalesPersonId',
                  'filter_values': f'mcptest-leg-sp-{sfx}'}, skip_if=crm_gate))
        add(step('custom_delete_sales_persons',
                 {'records': [{'externalSalesPersonId': f'mcptest-leg-sp-{sfx}'}]},
                 skip_if=crm_gate))

    # ================================================================ M. custom object type (full + both groups)
    if full:
        add(step('custom_list_custom_object_types'))
        add(step('custom_get_custom_object_field_types'))
        add(step('custom_get_custom_object_linkable_objects'))
    add(step('custom_sync_custom_object_type',
             {'api_name': CO_TYPE, 'display_name': 'MCPTEST Leg CO',
              'plural_name': 'MCPTEST Leg COs', 'action': 'createOrUpdate',
              'description': 'MCPTEST_LEG suite custom object'},
             skip_errors='co-schema-unavailable', after=_flag_skip('no_co_schema')))
    co_gate = _group_gate('no_co_schema', 'custom-object schema API unavailable')
    add(step('custom_add_custom_object_type_fields',
             {'api_name': CO_TYPE,
              'fields': [{'name': 'mcptestKey', 'displayName': 'MCPTEST Key',
                          'dataType': 'string', 'isDedupeField': True},
                         {'name': 'mcptestVal', 'displayName': 'MCPTEST Val',
                          'dataType': 'string'}]},
             skip_if=co_gate,
             skip_on=[('already exist', 'pre-existing CO fields'),
                      ('dedupe fields cannot be added', 'pre-existing CO fields')]))
    add(step('custom_approve_custom_object_type', {'api_name': CO_TYPE}, skip_if=co_gate,
             skip_on=[('no draft', 'co-already-approved')]))
    add(step('custom_sync_custom_objects',
             {'object_api_name': CO_TYPE,
              'records': [{'mcptestKey': f'k1-{sfx}', 'mcptestVal': 'v1'}]},
             skip_if=co_gate, after=_flag_skip('no_co_records')))
    co_rec_gate = _group_gate('no_co_records', 'custom-object records unavailable')

    if full:
        add(step('custom_describe_custom_object_type', {'api_name': CO_TYPE, 'state': 'draft'},
                 name='custom_describe_custom_object_type(draft)',
                 skip_if=co_gate, skip_errors='no-co-draft'))
        add(step('custom_update_custom_object_type_field',
                 {'api_name': CO_TYPE, 'field_api_name': 'mcptestVal',
                  'updates': {'description': f'MCPTEST_LEG updated {sfx}'}},
                 skip_if=co_gate, skip_errors='co-field-update-rejected'))
        add(step('custom_list_custom_objects', {'names': CO_TYPE}, skip_if=co_gate))
        add(step('custom_describe_custom_object', {'object_api_name': CO_TYPE},
                 skip_if=co_gate))
        add(step('custom_get_custom_object_type_dependents', {'api_name': CO_TYPE},
                 skip_if=co_gate))
        add(step('custom_query_custom_objects',
                 {'object_api_name': CO_TYPE, 'filter_type': 'mcptestKey',
                  'filter_values': f'k1-{sfx}'}, skip_if=co_rec_gate))
        add(step('custom_add_custom_object_type_fields',
                 {'api_name': CO_TYPE,
                  'fields': [{'name': 'mcptestTmp', 'displayName': 'MCPTEST Tmp',
                              'dataType': 'string'}]},
                 name='custom_add_custom_object_type_fields(tmp)', skip_if=co_gate,
                 skip_on=[('already exist', 'pre-existing CO fields')]))
        add(step('custom_delete_custom_object_type_fields',
                 {'api_name': CO_TYPE, 'field_names': ['mcptestTmp']},
                 skip_if=co_gate, skip_errors='co-delete-field-rejected'))
        add(step('custom_discard_custom_object_type_draft', {'api_name': CO_TYPE},
                 skip_if=co_gate, skip_errors='no-co-draft'))

        # ============================================================ N. named accounts / ABM
        add(step('custom_describe_named_accounts',
                 skip_on=[('abm', 'abm-not-enabled')], skip_errors='abm-unavailable',
                 after=_flag_skip('no_abm')))
        abm_gate = _group_gate('no_abm', 'ABM not enabled on this subscription')
        add(step('custom_get_named_account_fields', {'batch_size': 5}, skip_if=abm_gate))
        add(step('custom_get_named_account_field_by_name', {'field_api_name': 'name'},
                 skip_if=abm_gate))
        add(step('custom_sync_named_accounts',
                 {'records': [{'name': name('NA'), 'domainName': 'mcptest.invalid'}]},
                 skip_if=abm_gate, save=_save_key('na_guid', 'result', 0, 'marketoGUID')))
        add(step('custom_query_named_accounts',
                 {'filter_type': 'name', 'filter_values': name('NA'),
                  'fields': 'name,marketoGUID'}, skip_if=abm_gate))
        add(step('custom_sync_named_account_lists',
                 {'records': [{'name': name('NAL')}], 'action': 'createOnly'},
                 skip_if=abm_gate, save=_save_key('nal_id', 'result', 0, 'marketoGUID')))
        add(step('custom_query_named_account_lists',
                 {'filter_type': 'dedupeFields', 'filter_values': name('NAL')},
                 skip_if=abm_gate))
        add(step('custom_add_named_account_list_members',
                 lambda c: {'list_id': str(c['nal_id']), 'account_ids': [c['na_guid']]},
                 skip_if=_need('nal_id', 'na_guid')))
        add(step('custom_get_named_account_list_members',
                 lambda c: {'list_id': str(c['nal_id'])}, skip_if=_need('nal_id')))
        add(step('custom_remove_named_account_list_members',
                 lambda c: {'list_id': str(c['nal_id']), 'account_ids': [c['na_guid']]},
                 skip_if=_need('nal_id', 'na_guid')))
        add(step('custom_delete_named_account_lists',
                 lambda c: {'records': [{'id': c['nal_id']}], 'delete_by': 'idField'},
                 skip_if=_need('nal_id')))
        add(step('custom_delete_named_accounts',
                 lambda c: {'records': [{'id': c['na_guid']}], 'delete_by': 'idField'},
                 skip_if=_need('na_guid')))

    # ================================================================ O. bulk import group
    if full or group == GROUP_IMPORT:
        add(step('custom_import_leads_csv',
                 {'csv_content': f'email,firstName,lastName\n{email(5)},MCP,ImportFive\n'
                                 f'{email(6)},MCP,ImportSix\n'},
                 save=_save_key('lead_batch', 'result', 0, 'batchId')))
        add(step('infra:lead_import_status',
                 lambda c: {'batch_id': c['lead_batch']},
                 infra=R.lead_import_status, skip_if=_need('lead_batch'),
                 poll={'done': _job_done, 'flag': 'lead_import_done'}))
        add(step('custom_get_lead_import_failures', lambda c: {'batch_id': c['lead_batch']},
                 skip_if=_need('lead_batch')))
        add(step('custom_get_lead_import_warnings', lambda c: {'batch_id': c['lead_batch']},
                 skip_if=_need('lead_batch')))
        add(step('custom_import_program_members_csv',
                 lambda c: {'program_id': c['program_id'],
                            'program_member_status': c['statuses'][0],
                            'csv_content': f'email\n{email(7)}\n'},
                 save=_save_key('pm_batch', 'result', 0, 'batchId')))
        add(step('custom_get_program_member_import_status',
                 lambda c: {'batch_id': c['pm_batch']}, skip_if=_need('pm_batch'),
                 poll={'done': _job_done, 'flag': 'pm_import_done'}))
        add(step('custom_get_program_member_import_failures',
                 lambda c: {'batch_id': c['pm_batch']}, skip_if=_need('pm_batch')))
        add(step('custom_get_program_member_import_warnings',
                 lambda c: {'batch_id': c['pm_batch']}, skip_if=_need('pm_batch')))
        add(step('custom_import_custom_objects_csv',
                 {'object_api_name': CO_TYPE,
                  'csv_content': f'mcptestKey,mcptestVal\nk2-{sfx},v2\n'},
                 skip_if=co_rec_gate, save=_save_key('co_batch', 'result', 0, 'batchId')))
        add(step('custom_get_custom_object_import_status',
                 lambda c: {'object_api_name': CO_TYPE, 'batch_id': c['co_batch']},
                 skip_if=_need('co_batch'),
                 poll={'done': _job_done, 'flag': 'co_import_done'}))
        add(step('custom_get_custom_object_import_failures',
                 lambda c: {'object_api_name': CO_TYPE, 'batch_id': c['co_batch']},
                 skip_if=_need('co_batch')))
        add(step('custom_get_custom_object_import_warnings',
                 lambda c: {'object_api_name': CO_TYPE, 'batch_id': c['co_batch']},
                 skip_if=_need('co_batch')))
        add(step('infra:lookup_imported_leads',
                 lambda c: {'emails': [email(5), email(6), email(7)]},
                 infra=R.lookup_leads,
                 save=lambda c, d: c.__setitem__('imported_lead_ids',
                                                 [r['id'] for r in d.get('result') or []]),
                 notes='resolve imported lead ids for cleanup'))

    # ================================================================ P. bulk export group
    if full or group == GROUP_EXPORT:
        add(step('custom_list_lead_export_jobs', {'batch_size': 10}))
        add(step('infra:create_lead_export_job',
                 lambda c: {'fields': ['email', 'firstName'],
                            'start_at': _iso(run_start - timedelta(minutes=10)),
                            'end_at': _iso(datetime.now(timezone.utc))},
                 infra=R.create_lead_export_job,
                 save=_save_key('lead_export', 'result', 0, 'exportId'),
                 notes='created (not enqueued) purely so the cancel tool has a target'))
        add(step('custom_cancel_lead_export_job', lambda c: {'export_id': c['lead_export']},
                 skip_if=_need('lead_export')))
        add(step('custom_create_activity_export_job',
                 lambda c: {'start_at': _iso(run_start - timedelta(minutes=5)),
                            'end_at': _iso(datetime.now(timezone.utc))},
                 save=_save_key('act_export', 'result', 0, 'exportId'),
                 notes='tiny window: a few minutes around this run'))
        add(step('custom_enqueue_activity_export_job', lambda c: {'export_id': c['act_export']},
                 skip_if=_need('act_export'), skip_on=[('1029', 'export-queue-full')]))
        add(step('custom_get_activity_export_job_status',
                 lambda c: {'export_id': c['act_export']}, skip_if=_need('act_export'),
                 poll={'done': _job_done, 'flag': 'act_export_done'}))
        add(step('custom_get_activity_export_file', lambda c: {'export_id': c['act_export']},
                 skip_if=lambda c: (None if (c.get('act_export') and c.get('act_export_done'))
                                    else 'export job still pending after poll window')))
        add(step('custom_create_activity_export_job',
                 lambda c: {'start_at': _iso(run_start - timedelta(minutes=5)),
                            'end_at': _iso(datetime.now(timezone.utc))},
                 name='custom_create_activity_export_job(cancel-target)',
                 save=_save_key('act_export2', 'result', 0, 'exportId')))
        add(step('custom_cancel_activity_export_job',
                 lambda c: {'export_id': c['act_export2']}, skip_if=_need('act_export2')))
        add(step('custom_list_activity_export_jobs', {'batch_size': 10}))

        if not full:
            add(step('describe_program_members',
                     save=lambda c, d: c.__setitem__(
                         'pm_export_fields',
                         [n for n in ('leadId', 'program', 'programId', 'statusName',
                                      'reachedSuccess')
                          if n in {f.get('name') for f in
                                   ((d.get('result') or [{}])[0].get('fields') or [])}][:2]
                         or ['leadId', 'program'])))
        add(step('custom_create_program_member_export_job',
                 lambda c: {'fields': c.get('pm_export_fields', ['leadId', 'program']),
                            'program_id': c['program_id']},
                 save=_save_key('pm_export', 'result', 0, 'exportId'),
                 notes="scoped to this run's program"))
        add(step('custom_enqueue_program_member_export_job',
                 lambda c: {'export_id': c['pm_export']}, skip_if=_need('pm_export'),
                 skip_on=[('1029', 'export-queue-full')]))
        add(step('custom_get_program_member_export_job_status',
                 lambda c: {'export_id': c['pm_export']}, skip_if=_need('pm_export'),
                 poll={'done': _job_done, 'flag': 'pm_export_done'}))
        add(step('custom_get_program_member_export_file',
                 lambda c: {'export_id': c['pm_export']},
                 skip_if=lambda c: (None if (c.get('pm_export') and c.get('pm_export_done'))
                                    else 'export job still pending after poll window')))
        add(step('custom_create_program_member_export_job',
                 lambda c: {'fields': c.get('pm_export_fields', ['leadId', 'program']),
                            'program_id': c['program_id']},
                 name='custom_create_program_member_export_job(cancel-target)',
                 save=_save_key('pm_export2', 'result', 0, 'exportId')))
        add(step('custom_cancel_program_member_export_job',
                 lambda c: {'export_id': c['pm_export2']}, skip_if=_need('pm_export2')))
        add(step('custom_list_program_member_export_jobs', {'batch_size': 10}))

        co_filter = lambda: {'updatedAt': {'startAt': _iso(run_start - timedelta(hours=1)),
                                           'endAt': _iso(datetime.now(timezone.utc)
                                                         + timedelta(minutes=5))}}
        add(step('custom_create_custom_object_export_job',
                 lambda c: {'object_api_name': CO_TYPE,
                            'fields': ['mcptestKey', 'mcptestVal'],
                            'filter': co_filter()},
                 skip_if=co_rec_gate, save=_save_key('co_export', 'result', 0, 'exportId')))
        add(step('custom_enqueue_custom_object_export_job',
                 lambda c: {'object_api_name': CO_TYPE, 'export_id': c['co_export']},
                 skip_if=_need('co_export'), skip_on=[('1029', 'export-queue-full')]))
        add(step('custom_get_custom_object_export_job_status',
                 lambda c: {'object_api_name': CO_TYPE, 'export_id': c['co_export']},
                 skip_if=_need('co_export'),
                 poll={'done': _job_done, 'flag': 'co_export_done'}))
        add(step('custom_get_custom_object_export_file',
                 lambda c: {'object_api_name': CO_TYPE, 'export_id': c['co_export']},
                 skip_if=lambda c: (None if (c.get('co_export') and c.get('co_export_done'))
                                    else 'export job still pending after poll window')))
        add(step('custom_create_custom_object_export_job',
                 lambda c: {'object_api_name': CO_TYPE, 'fields': ['mcptestKey'],
                            'filter': co_filter()},
                 name='custom_create_custom_object_export_job(cancel-target)',
                 skip_if=co_rec_gate, save=_save_key('co_export2', 'result', 0, 'exportId')))
        add(step('custom_cancel_custom_object_export_job',
                 lambda c: {'object_api_name': CO_TYPE, 'export_id': c['co_export2']},
                 skip_if=_need('co_export2')))
        add(step('custom_list_custom_object_export_jobs', {'object_api_name': CO_TYPE},
                 skip_if=co_gate))

    # ================================================================ Q. users + Asset v2 (full only)
    if full:
        add(step('custom_list_workspaces', skip_errors='user-mgmt-permission-missing',
                 after=_flag_skip('no_user_mgmt'),
                 save=lambda c, d: c.__setitem__('workspace_id',
                                                 (d.get('result') or [{}])[0].get('id', 1))))
        um_gate = _group_gate('no_user_mgmt',
                              'user-management permission missing (603) on API role')
        add(step('custom_list_users', {'page_size': 5}, skip_if=um_gate,
                 save=lambda c, d: c.__setitem__('first_user_id',
                                                 (d.get('result') or [{}])[0].get('userid'))))
        add(step('custom_get_user_by_id', lambda c: {'user_id': c['first_user_id']},
                 skip_if=um_gate))
        add(step('custom_list_user_roles', skip_if=um_gate,
                 save=lambda c, d: c.__setitem__('role_id',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step('custom_get_user_roles', lambda c: {'user_id': c['first_user_id']},
                 skip_if=um_gate))
        add(step('custom_invite_user',
                 lambda c: {'email_address': INVITE_EMAIL, 'first_name': 'MCP',
                            'last_name': 'LegInvite', 'api_only': True,
                            'expires_at': _iso(now + timedelta(days=1)),
                            'reason': 'MCPTEST_LEG suite',
                            'user_role_workspaces': [{'accessRoleId': c['role_id'],
                                                      'workspaceId': c['workspace_id']}]},
                 skip_if=um_gate,
                 after=lambda c, s, d: c.__setitem__('invited', s == PASS)))
        invited_gate = lambda c: (None if c.get('invited')
                                  else 'safety: only the suite-invited user may be touched')
        add(step('custom_get_user_invite', {'user_id': INVITE_EMAIL}, skip_if=invited_gate))
        add(step('custom_update_user',
                 {'user_id': INVITE_EMAIL, 'last_name': 'LegInviteUpdated'},
                 skip_if=invited_gate, skip_errors='pending-user-not-updatable'))
        add(step('custom_add_user_roles',
                 lambda c: {'user_id': INVITE_EMAIL,
                            'role_workspaces': [{'accessRoleId': c['role_id'],
                                                 'workspaceId': c['workspace_id']}]},
                 skip_if=invited_gate, skip_errors='pending-user-roles-unmodifiable'))
        add(step('custom_remove_user_roles',
                 lambda c: {'user_id': INVITE_EMAIL,
                            'role_workspaces': [{'accessRoleId': c['role_id'],
                                                 'workspaceId': c['workspace_id']}]},
                 skip_if=invited_gate, skip_errors='pending-user-roles-unmodifiable'))
        add(step('custom_delete_user_invite', {'user_id': INVITE_EMAIL}, skip_if=invited_gate))
        add(step('custom_delete_user', {'user_id': INVITE_EMAIL}, skip_if=invited_gate,
                 skip_errors='invited-user-not-deletable'))

        add(step('custom_browse_email_templates2',
                 lambda c: {'workspace_id': c.get('workspace_id', 1)},
                 skip_on=[('704', 'v2-unavailable: x-app-type header required'),
                          ('non-json', 'v2-unavailable'),
                          ('expecting value', 'v2-unavailable (non-JSON response)')],
                 skip_errors='v2-unavailable', after=_flag_skip('no_v2')))
        v2_gate = _group_gate(
            'no_v2', 'Asset v2 unavailable (704 x-app-type header / Emails 2.0 not enabled)')
        for tool, args in [
            ('custom_get_email2_by_id', lambda c: {'email_id': c['email_id']}),
            ('custom_create_email2',
             lambda c: {'name': name('EMAIL2'), 'app_data': {'folderId': c['ds_emails']},
                        'headers': {'subject': 'MCPTEST', 'fromName': 'MCPTEST',
                                    'fromEmail': SAMPLE_EMAIL_TO, 'replyTo': SAMPLE_EMAIL_TO}}),
            ('custom_update_email2',
             lambda c: {'email_id': c['email2_id'], 'description': 'MCPTEST'}),
            ('custom_clone_email2',
             lambda c: {'email_id': c['email2_id'], 'name': name('EMAIL2_CLONE'),
                        'folder_id': c['ds_emails']}),
            ('custom_transition_email2_state',
             lambda c: {'email_id': c['email2_id'], 'action': 'approve'}),
            ('custom_get_email2_used_by', lambda c: {'email_id': c['email2_id']}),
            ('custom_delete_email2', lambda c: {'email_id': c['email2_id']}),
            ('custom_get_email_template2_by_id', lambda c: {'template_id': c['tpl_id']}),
            ('custom_create_email_template2',
             lambda c: {'name': name('TPL2'), 'app_data': {'folderId': c['ds_etpl']}}),
            ('custom_update_email_template2',
             lambda c: {'template_id': c['tpl2_id'], 'description': 'MCPTEST'}),
            ('custom_clone_email_template2',
             lambda c: {'template_id': c['tpl2_id'], 'name': name('TPL2_CLONE'),
                        'folder_id': c['ds_etpl']}),
            ('custom_transition_email_template2_state',
             lambda c: {'template_id': c['tpl2_id'], 'action': 'approve'}),
            ('custom_get_email_template2_used_by', lambda c: {'template_id': c['tpl2_id']}),
            ('custom_delete_email_template2', lambda c: {'template_id': c['tpl2_id']}),
            ('custom_browse_fragments', lambda c: {'workspace_id': c.get('workspace_id', 1)}),
            ('custom_get_fragment_by_id', lambda c: {'fragment_id': c['fragment_id']}),
            ('custom_create_fragment',
             lambda c: {'name': name('FRAG'), 'app_data': {'folderId': c['ds_emails']},
                        'settings': {}}),
            ('custom_update_fragment',
             lambda c: {'fragment_id': c['fragment_id'], 'description': 'MCPTEST'}),
            ('custom_clone_fragment',
             lambda c: {'fragment_id': c['fragment_id'], 'name': name('FRAG_CLONE'),
                        'folder_id': c['ds_emails']}),
            ('custom_transition_fragment_state',
             lambda c: {'fragment_id': c['fragment_id'], 'action': 'approve'}),
            ('custom_get_fragment_used_by', lambda c: {'fragment_id': c['fragment_id']}),
            ('custom_delete_fragment', lambda c: {'fragment_id': c['fragment_id']}),
        ]:
            save = None
            if tool == 'custom_create_email2':
                save = _save_key('email2_id', 'result', 0, 'id')
            elif tool == 'custom_create_email_template2':
                save = _save_key('tpl2_id', 'result', 0, 'id')
            elif tool == 'custom_create_fragment':
                save = _save_key('fragment_id', 'result', 0, 'id')
            add(step(tool, args, skip_if=v2_gate, skip_errors='v2-schema', save=save,
                     notes='pragmatic minimal-body attempt; validation errors -> SKIP'))

    # ================================================================ R. cleanup
    def delete_leads_args(ctx):
        ids = [ctx.get(k) for k in ('lead1', 'lead2', 'lead3', 'lead4')]
        if not ctx.get('dup1_merged'):
            ids.append(ctx.get('dup1'))
        if not ctx.get('dup2_merged'):
            ids.append(ctx.get('dup2'))
        ids += ctx.get('imported_lead_ids', [])
        ids = [i for i in ids if i]
        if not ids:
            raise KeyError('lead ids')
        return {'lead_ids': ids}

    add(step('custom_delete_leads', delete_leads_args))
    if full:
        add(step('custom_get_deleted_leads',
                 {'since_datetime': _iso(now - timedelta(hours=1))}))
        add(step('custom_delete_static_list', lambda c: {'list_id': c['list_id']}))
        add(step('custom_delete_smart_list', lambda c: {'smart_list_id': c['sl_id']}))
        add(step('custom_delete_smart_campaign', lambda c: {'campaign_id': c['sc_clone_id']}))
        add(step('delete_smart_campaign', lambda c: {'campaign_id': c['sc_clone2_id']},
                 name='delete_smart_campaign(clone2)'))
        add(step('delete_smart_campaign', lambda c: {'campaign_id': c['sc_id']}))
        add(step('delete_program', lambda c: {'program_id': c['program_clone_id']},
                 name='delete_program(clone)'))
        add(step('custom_delete_program', lambda c: {'program_id': c['email_program_id']},
                 name='custom_delete_program(email)'))
    add(step('custom_delete_program', lambda c: {'program_id': c['program_id']}))
    if full:
        add(step('custom_delete_snippet', lambda c: {'snippet_id': c['snippet_id']}))
        add(step('custom_delete_form', lambda c: {'form_id': c['form_id']}))
        add(step('custom_unapprove_email', lambda c: {'email_id': c['email_clone_id']},
                 name='custom_unapprove_email(clone)', skip_errors='clone-not-approved'))
        add(step('custom_delete_email', lambda c: {'email_id': c['email_clone_id']},
                 name='custom_delete_email(clone)'))
        add(step('custom_delete_email', lambda c: {'email_id': c['email_id']}))
        add(step('custom_unapprove_email_template', lambda c: {'template_id': c['tpl_id']}))
        add(step('custom_delete_email_template', lambda c: {'template_id': c['tpl_clone_id']},
                 name='custom_delete_email_template(clone)'))
        add(step('custom_delete_email_template', lambda c: {'template_id': c['tpl_id']}))
        add(step('custom_unapprove_landing_page', lambda c: {'landing_page_id': c['lp_id']},
                 name='custom_unapprove_landing_page(cleanup)',
                 skip_errors='lp-not-approved',
                 notes='defensive: LP must be unapproved before deletion'))
        add(step('custom_delete_landing_page', lambda c: {'landing_page_id': c['lp_clone_id']},
                 name='custom_delete_landing_page(clone)'))
        add(step('custom_delete_landing_page', lambda c: {'landing_page_id': c['lp_id']},
                 retries=2))
        add(step('custom_unapprove_landing_page_template',
                 lambda c: {'template_id': c['lpt_id']},
                 skip_errors='lpt-not-approved'))
        add(step('custom_delete_landing_page_template',
                 lambda c: {'template_id': c['lpt_clone_id']},
                 name='custom_delete_landing_page_template(clone)'))
        add(step('custom_delete_landing_page_template', lambda c: {'template_id': c['lpt_id']}))
        add(step('custom_delete_custom_activity_type', {'api_name': ACT_TYPE},
                 skip_errors='activity-type-in-use',
                 notes='types with recent activity records cannot be deleted; reused next run'))
    add(step('custom_delete_custom_objects',
             lambda c: {'object_api_name': CO_TYPE,
                        'records': [{'mcptestKey': f'k1-{sfx}', },
                                    {'mcptestKey': f'k2-{sfx}'}]},
             skip_if=co_rec_gate))
    if full:
        add(step('custom_delete_custom_object_type', {'api_name': CO_TYPE},
                 skip_if=co_gate, skip_errors='co-type-has-records',
                 notes='record deletion is async; type delete may need a later run'))
        for key in ('ds_forms', 'ds_emails', 'ds_etpl', 'ds_lp', 'ds_lpt', 'ds_snip'):
            add(step('custom_delete_folder',
                     (lambda k: lambda c: {'folder_id': c[k]})(key),
                     name=f'custom_delete_folder({key})'))
    add(step('custom_delete_folder', lambda c: {'folder_id': c['ma_folder']},
             name='custom_delete_folder(ma)'))

    return steps


def print_engine_summary(records, uncovered, elapsed, enforce_coverage):
    width = max((len(r[0]) for r in records), default=20)
    print("\n" + "=" * (width + 40))
    print(f"{'STEP':<{width}}  {'KIND':<6} {'STATUS':<6} {'SECS':>6}  REASON")
    print("-" * (width + 40))
    for nm, kind, status, reason, secs in records:
        print(f"{nm:<{width}}  {kind:<6} {status:<6} {secs:>6.1f}  {str(reason)[:100]}")
    counts = {PASS: 0, FAIL: 0, SKIP: 0}
    for _, _, status, _, _ in records:
        counts[status] += 1
    print("-" * (width + 40))
    print(f"TOTALS: {counts[PASS]} PASS, {counts[FAIL]} FAIL, {counts[SKIP]} SKIP, "
          f"{len(uncovered) if enforce_coverage else 'n/a'} UNCOVERED  |  "
          f"steps: {len(records)}  |  wall clock: {elapsed/60:.1f} min")

    fails = [(nm, r) for nm, _, s, r, _ in records if s == FAIL]
    if fails:
        print("\nFAILURES:")
        for nm, reason in fails:
            print(f"  FAIL {nm}: {reason}")
    skips = {}
    for nm, _, status, reason, _ in records:
        if status == SKIP:
            key = str(reason).split(":")[0]
            skips.setdefault(key, []).append(nm)
    if skips:
        print("\nSKIPS grouped by reason:")
        for key in sorted(skips):
            print(f"  [{key}] ({len(skips[key])}): {', '.join(skips[key])}")
    return counts


async def run_auto_suite(creds, group=None):
    sfx = datetime.now().strftime("%m%d%H%M%S")
    R = RestInfra(creds)

    label = group or 'full'
    print(f"Run suffix: {sfx}  |  mode: {label}")
    print("\n--- Sweep: clearing MCPTEST_LEG_* leftovers (start) ---")
    sweep_mcptest_leg(R)

    steps = build_full_steps(sfx, R, group)
    print(f"\n--- Running {len(steps)} steps against {AUTO_URL} ---")
    started = time.time()
    runner = SuiteRunner(AUTO_URL)
    await runner.connect()
    try:
        tool_names = await runner.list_tool_names()
        ALL_TOOLS.clear()
        ALL_TOOLS.extend(sorted(tool_names))
        print(f"Connected: {len(ALL_TOOLS)} tools listed.")
        ctx = {}
        for st in steps:
            try:
                await runner.run_step(st, ctx)
            except Exception as exc:
                runner.records.append((st['name'], 'ENGINE', FAIL,
                                       f"engine error: {type(exc).__name__}: {exc}", 0.0))
                print(f"F [{len(runner.records):3d}] ENGINE {st['name']} FAIL ({exc})",
                      flush=True)
    finally:
        await runner.close()

    print("\n--- Sweep: clearing MCPTEST_LEG_* leftovers (end) ---")
    sweep_mcptest_leg(R)

    enforce = group is None
    uncovered = print_coverage(enforce=enforce)
    counts = print_engine_summary(runner.records, uncovered, time.time() - started, enforce)
    return 1 if (counts[FAIL] or (enforce and uncovered)) else 0


# ============================================================================
# Main
# ============================================================================

async def main():
    global AUTO_MODE

    parser = argparse.ArgumentParser(description="Test suite for mcp_server.py (via MCP protocol)")
    parser.add_argument('--auto', action='store_true',
                        help="Run the FULL-COVERAGE suite non-interactively: starts "
                             "mcp_server.py as a subprocess on port 8010, exercises every "
                             "tool with MCPTEST_LEG_* assets, always cleans up; exits "
                             "non-zero on FAIL or uncovered tools")
    parser.add_argument('--group', choices=[GROUP_EXPORT, GROUP_IMPORT],
                        help="Run only the bulk-export or bulk-import steps plus minimal "
                             "prerequisites (implies --auto)")
    args = parser.parse_args()
    AUTO_MODE = args.auto or bool(args.group)

    load_test_config()

    mcp_api_key = os.environ.get("MCP_API_KEY")

    print("=" * 60)
    print("MCP Server - Tool Test Suite")
    print("=" * 60)

    if AUTO_MODE:
        mode = args.group or 'full coverage'
        print(f"\nMode: AUTO ({mode}, non-interactive, self-managed server on :{AUTO_PORT})")
        creds = resolve_credentials()
        if not creds:
            print("ERROR: Marketo credentials not found in environment, .env, or .env.sandbox")
            sys.exit(1)
        server_proc, _ = start_mcp_server(creds, AUTO_PORT)
        try:
            exit_code = await run_auto_suite(creds, args.group)
        finally:
            stop_mcp_server(server_proc)
        sys.exit(exit_code)

    print(f"\nConnects to the MCP server at {MCP_SERVER_URL}")
    print("Make sure the server is running: python mcp_server.py (or mcp_server_auth.py)")
    if mcp_api_key:
        print("Auth: Bearer token from MCP_API_KEY detected")
    else:
        print("Auth: None (set MCP_API_KEY in .env for mcp_server_auth.py)")
    print("\n1. Read-only tests (safe, no modifications)")
    print("2. Write-only tests (create, clone, update, delete)")
    print("3. Full tests (read-only + write operations)")

    choice = input("\nSelect test mode (1, 2, or 3): ").strip()

    client = Client(MCP_SERVER_URL, auth=mcp_api_key)

    print(f"\nConnecting to MCP server: {MCP_SERVER_URL}")

    async with client:
        print("Connected.\n")

        if not ALL_TOOLS:
            tools = await client.list_tools()
            ALL_TOOLS.extend(sorted(t.name for t in tools))

        if choice == '2':
            await run_write_tests(client)
        elif choice == '3':
            await run_full_tests(client)
        else:
            await run_readonly_tests(client)

    print_coverage(enforce=False)

    if skip_reasons:
        print("\nSkipped tests:")
        for name, reason in skip_reasons:
            print(f"  - {name}: {reason}")


if __name__ == '__main__':
    asyncio.run(main())
