"""
Test script for mcp_server.py - calls tools through the MCP protocol.
Connects to the MCP server running locally on http://localhost:8000/mcp.
Start the server first: python mcp_server.py
Run: python test_mcp_server.py
"""

import asyncio
import json
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastmcp import Client

TEST_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_config.json")

_test_config = {}


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
    """Get a test variable from saved config or prompt the user.

    Returns the value (str) or empty string if skipped.
    Saves new values to the config file automatically.
    """
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
    """Resolve an asset by name via MCP tool, with disambiguation if multiple matches.

    Checks saved config first (stored as ID from a previous run).
    If not saved, prompts for a name, looks it up, and lets the user
    choose if there are multiple matches. Saves the resolved ID for future runs.

    Returns the asset ID (int) or None if skipped/not found.
    """
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

    # Multiple matches - ask user to choose
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
    """Resolve a lead by email address via MCP tool. Saves the lead ID for future runs."""
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


passed = 0
failed = 0
skipped = 0

# Track created assets for cleanup
created_assets = {
    'campaigns': [],   # list of campaign IDs
    'programs': [],    # list of program IDs
    'tokens': []       # list of (folder_id, name, token_type, folder_type) tuples
}


async def call_tool(client, tool_name, arguments=None):
    """Call an MCP tool and return the parsed result."""
    if arguments is None:
        arguments = {}

    result = await client.call_tool(tool_name, arguments)

    # Parse the result - fastmcp returns a CallToolResult with .content list
    if result and result.content:
        text = result.content[0].text
        return json.loads(text)

    return None


async def test(client, name, tool_name, arguments=None):
    """Run a single MCP tool test and track the result."""
    global passed, failed
    try:
        result = await call_tool(client, tool_name, arguments)

        # Check for Marketo API errors
        if isinstance(result, dict) and result.get('errors'):
            print(f"  [FAIL] {name}")
            print(f"         {result['errors']}")
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
    skipped += 1


def print_summary():
    """Print final test results."""
    total = passed + failed + skipped
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed, {skipped} skipped (total: {total})")
    print(f"{'=' * 60}")


# ============================================================================
# Read-Only Tests
# ============================================================================

async def run_readonly_tests(client):
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("MCP SERVER - READ-ONLY TESTS")
    print("=" * 60)

    # --- List available tools ---
    print("\n--- Server Connection ---")
    try:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]
        print(f"  [PASS] list_tools() - {len(tools)} tools available")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] list_tools() - {e}")
        failed += 1
        print("\nCannot connect to MCP server. Exiting.")
        print_summary()
        return

    # --- Browse & Describe (no input needed) ---
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

    # --- Detail lookups using auto-discovered IDs ---
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

    # --- Lead tests (need email input) ---
    print("\n--- Lead Lookup Tests ---")
    test_email = get_test_var("test_email", "Enter a test email address for lead lookup (or Enter to skip): ")

    if test_email:
        lead_data = await test(client, f"get_lead_by_email('{test_email}')",
                               "get_lead_by_email", {"email": test_email})

        if lead_data and lead_data.get('result'):
            lead_id = lead_data['result'][0]['id']
            print(f"         Found lead ID: {lead_id}")

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
# Write-Only Tests (create, clone, update, delete)
# ============================================================================

async def run_write_tests(client):
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("WRITE OPERATIONS TESTS (via MCP)")
    print("=" * 60)
    print("\nThese tests will CREATE, UPDATE, and CLONE assets in Marketo.")
    print("Test assets will be prefixed with 'MCPTEST_' for easy cleanup.\n")

    # Collect required inputs (resolve by name, save IDs for future runs)
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

    # Fetch available channels to help the user choose
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

    # --- Smart Campaign Tests ---
    print("\n--- Create Smart Campaign ---")
    created_campaign = await test(client, "create_smart_campaign('MCPTEST_Campaign')",
                                 "create_smart_campaign",
                                 {"name": "MCPTEST_Campaign", "folder_id": folder_id,
                                  "description": "Test campaign from MCP test suite"})

    if created_campaign and created_campaign.get('result'):
        new_campaign_id = created_campaign['result'][0]['id']
        created_assets['campaigns'].append(new_campaign_id)
        print(f"         Created campaign ID: {new_campaign_id}")

        print("\n--- Update Smart Campaign ---")
        await test(client, f"update_smart_campaign({new_campaign_id})",
                   "update_smart_campaign",
                   {"campaign_id": new_campaign_id,
                    "name": "MCPTEST_Campaign_Updated",
                    "description": "Updated by MCP test suite"})
    else:
        skip("update_smart_campaign", "create failed")

    # Clone using the first available campaign from trigger/batch/request
    clone_source_id = trigger_campaign_id or batch_campaign_id or request_campaign_id
    if clone_source_id:
        print("\n--- Clone Smart Campaign ---")
        cloned_campaign = await test(client, f"clone_smart_campaign({clone_source_id})",
                                     "clone_smart_campaign",
                                     {"campaign_id": clone_source_id,
                                      "name": "MCPTEST_Campaign_Clone",
                                      "folder_id": folder_id})
        if cloned_campaign and cloned_campaign.get('result'):
            created_assets['campaigns'].append(cloned_campaign['result'][0]['id'])
    else:
        skip("clone_smart_campaign", "no campaigns provided")

    # --- Activate / Deactivate ---
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

    # --- Schedule Batch Campaign ---
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

    # --- Request Campaign ---
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

    # --- Program Tests ---
    print("\n--- Create Program ---")
    created_program = await test(client, "create_program('MCPTEST_Program')",
                                "create_program",
                                {"name": "MCPTEST_Program", "folder_id": folder_id,
                                 "program_type": program_type, "channel": channel,
                                 "description": "Test program from MCP test suite"})

    if created_program and created_program.get('result'):
        new_program_id = created_program['result'][0]['id']
        created_assets['programs'].append(new_program_id)
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
            created_assets['programs'].append(cloned_program['result'][0]['id'])
    else:
        skip("clone_program", "no email program provided")

    # --- Approve / Unapprove Email Program ---
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

    # --- Token Tests ---
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

    # --- Cleanup ---
    await cleanup_test_assets(client, folder_id)


# ============================================================================
# Full Tests (read-only + write operations)
# ============================================================================

async def run_full_tests(client):
    await run_readonly_tests(client)
    await run_write_tests(client)


# ============================================================================
# Cleanup
# ============================================================================

async def cleanup_test_assets(client, folder_id):
    """Prompt user to delete test assets created during the full test run."""
    total = (len(created_assets['campaigns']) +
             len(created_assets['programs']) +
             len(created_assets['tokens']))

    if total == 0:
        return

    print(f"\n{'=' * 60}")
    print("CLEANUP - DELETE TEST ASSETS")
    print(f"{'=' * 60}")
    print(f"\nThe following test assets were created:")

    for cid in created_assets['campaigns']:
        print(f"  Smart Campaign ID: {cid}")
    for pid in created_assets['programs']:
        print(f"  Program ID: {pid}")
    for (fid, name, ttype, ftype) in created_assets['tokens']:
        print(f"  Token: '{name}' in {ftype} {fid}")

    confirm = input(f"\nDelete all {total} test assets? (y/n): ").strip().lower()
    if confirm not in ('y', 'yes'):
        print("Skipping cleanup. You can delete these manually in Marketo.")
        return

    print("\n--- Deleting test assets ---")

    for cid in created_assets['campaigns']:
        try:
            result = await call_tool(client, "delete_smart_campaign", {"campaign_id": cid})
            if result and result.get('success'):
                print(f"  [DELETED] Smart Campaign {cid}")
            else:
                print(f"  [FAILED]  Smart Campaign {cid} - {result}")
        except Exception as e:
            print(f"  [FAILED]  Smart Campaign {cid} - {e}")

    for pid in created_assets['programs']:
        try:
            result = await call_tool(client, "delete_program", {"program_id": pid})
            if result and result.get('success'):
                print(f"  [DELETED] Program {pid}")
            else:
                print(f"  [FAILED]  Program {pid} - {result}")
        except Exception as e:
            print(f"  [FAILED]  Program {pid} - {e}")

    for (fid, name, ttype, ftype) in created_assets['tokens']:
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

    print("\nCleanup complete.")


# ============================================================================
# Main
# ============================================================================

MCP_SERVER_URL = "http://localhost:8000/mcp"


async def main():
    load_test_config()

    print("=" * 60)
    print("MCP Server - Tool Test Suite")
    print("=" * 60)
    print(f"\nConnects to the MCP server at {MCP_SERVER_URL}")
    print("Make sure the server is running: python mcp_server.py")
    print("\n1. Read-only tests (safe, no modifications)")
    print("2. Write-only tests (create, clone, update, delete)")
    print("3. Full tests (read-only + write operations)")

    choice = input("\nSelect test mode (1, 2, or 3): ").strip()

    # Connect to the running MCP server
    client = Client(MCP_SERVER_URL)

    print(f"\nConnecting to MCP server: {MCP_SERVER_URL}")

    async with client:
        print("Connected.\n")

        if choice == '2':
            await run_write_tests(client)
        elif choice == '3':
            await run_full_tests(client)
        else:
            await run_readonly_tests(client)


if __name__ == '__main__':
    asyncio.run(main())
