"""
Test script for marketo_functions.py - calls functions directly.
Run: python test_marketo_functions.py
"""

import marketo_functions
import json
import os

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


def resolve_asset(config_key, prompt, lookup_fn):
    """Resolve an asset by name, with disambiguation if multiple matches found.

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

    result = lookup_fn(name)

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


def resolve_lead(config_key, prompt, token):
    """Resolve a lead by email address. Saves the lead ID for future runs."""
    saved = _test_config.get(config_key, "")
    if saved:
        print(f"  (loaded from test_config.json: {config_key}={saved})")
        return int(saved)

    email = input(prompt).strip()
    if not email:
        return None

    result = marketo_functions.lookupLead(token, "email", email)

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


def test(test_name, func, *args, **kwargs):
    """Run a single test and track the result."""
    global passed, failed
    try:
        result = func(*args, **kwargs)

        # Check for Marketo API errors
        if isinstance(result, dict) and result.get('errors'):
            print(f"  [FAIL] {test_name}")
            print(f"         {result['errors']}")
            failed += 1
            return None

        print(f"  [PASS] {test_name}")
        passed += 1
        return result

    except Exception as e:
        print(f"  [FAIL] {test_name} - {e}")
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

def run_readonly_tests():
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("MARKETO FUNCTIONS - READ-ONLY TESTS")
    print("=" * 60)

    # --- Authentication ---
    print("\n--- Authentication ---")
    try:
        token = marketo_functions.getToken()
        print(f"  [PASS] getToken()")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] getToken() - {e}")
        failed += 1
        print("\nAuthentication failed. Cannot continue.")
        print_summary()
        return

    # --- Browse & Describe (no input needed) ---
    print("\n--- Activity Types ---")
    activity_types = test("getActivityTypes", marketo_functions.getActivityTypes, token)
    if activity_types and activity_types.get('result'):
        print(f"         Found {len(activity_types['result'])} activity types")

    print("\n--- Lead Schema ---")
    lead_schema = test("describeLeads", marketo_functions.describeLeads, token)
    if lead_schema and lead_schema.get('result'):
        print(f"         Found {len(lead_schema['result'])} field definitions")

    print("\n--- Browse Emails ---")
    emails = test("browseEmails", marketo_functions.browseEmails, token)
    if emails and emails.get('result'):
        print(f"         Found {len(emails['result'])} emails")

    print("\n--- Email CC Fields ---")
    test("getEmailCcFields", marketo_functions.getEmailCcFields, token)

    print("\n--- Channels ---")
    channels = test("getChannels", marketo_functions.getChannels, token)
    if channels and channels.get('result'):
        print(f"         Found {len(channels['result'])} channels")

    print("\n--- Browse Folders ---")
    folders = test("browseFolders", marketo_functions.browseFolders, token)
    if folders and folders.get('result'):
        print(f"         Found {len(folders['result'])} folders")

    print("\n--- Browse Smart Campaigns ---")
    campaigns = test("browseSmartCampaigns", marketo_functions.browseSmartCampaigns, token)
    if campaigns and campaigns.get('result'):
        print(f"         Found {len(campaigns['result'])} campaigns")

    print("\n--- Browse Programs ---")
    programs = test("browsePrograms", marketo_functions.browsePrograms, token)
    if programs and programs.get('result'):
        print(f"         Found {len(programs['result'])} programs")

    print("\n--- Program Members Schema ---")
    test("describeProgramMembers", marketo_functions.describeProgramMembers, token)

    # --- Detail lookups using auto-discovered IDs ---
    print("\n--- Email Detail Tests (auto-discovered) ---")
    if emails and emails.get('result'):
        email_asset = emails['result'][0]
        eid = email_asset['id']
        ename = email_asset['name']
        print(f"  Using email: '{ename}' (ID: {eid})")

        test(f"getEmailById({eid})", marketo_functions.getEmailById, token, eid)
        test(f"getEmailByName('{ename}')", marketo_functions.getEmailByName, token, ename)
        test(f"getEmailContent({eid})", marketo_functions.getEmailContent, token, eid)
        test(f"previewEmail({eid})", marketo_functions.previewEmail, token, eid)
    else:
        skip("getEmailById", "no emails found in browse")
        skip("getEmailByName", "no emails found in browse")
        skip("getEmailContent", "no emails found in browse")
        skip("previewEmail", "no emails found in browse")

    print("\n--- Smart Campaign Detail Tests (auto-discovered) ---")
    if campaigns and campaigns.get('result'):
        camp = campaigns['result'][0]
        cid = camp['id']
        cname = camp['name']
        print(f"  Using campaign: '{cname}' (ID: {cid})")

        test(f"getSmartCampaignById({cid})", marketo_functions.getSmartCampaignById, token, cid)
        test(f"getSmartCampaignByName('{cname}')", marketo_functions.getSmartCampaignByName, token, cname)
    else:
        skip("getSmartCampaignById", "no campaigns found in browse")
        skip("getSmartCampaignByName", "no campaigns found in browse")

    print("\n--- Program Detail Tests (auto-discovered) ---")
    if programs and programs.get('result'):
        prog = programs['result'][0]
        pid = prog['id']
        pname = prog['name']
        print(f"  Using program: '{pname}' (ID: {pid})")

        test(f"getProgramById({pid})", marketo_functions.getProgramById, token, pid)
        test(f"getProgramByName('{pname}')", marketo_functions.getProgramByName, token, pname)
        test(f"queryProgramMembers({pid})", marketo_functions.queryProgramMembers,
             token, pid, "statusName", "member")
    else:
        skip("getProgramById", "no programs found in browse")
        skip("getProgramByName", "no programs found in browse")
        skip("queryProgramMembers", "no programs found in browse")

    print("\n--- Folder Token Tests (auto-discovered) ---")
    if folders and folders.get('result'):
        folder = folders['result'][0]
        fid = folder['id']
        print(f"  Using folder ID: {fid}")

        test(f"getTokensByFolder({fid})", marketo_functions.getTokensByFolder, token, fid)
    else:
        skip("getTokensByFolder", "no folders found in browse")

    # --- Lead tests (need email input) ---
    print("\n--- Lead Lookup Tests ---")
    test_email = get_test_var("test_email", "Enter a test email address for lead lookup (or Enter to skip): ")

    if test_email:
        lead_data = test(f"lookupLead('email', '{test_email}')",
                         marketo_functions.lookupLead, token, "email", test_email)

        if lead_data and lead_data.get('result'):
            lead_id = lead_data['result'][0]['id']
            print(f"         Found lead ID: {lead_id}")

            test(f"getLeadActivities({lead_id})",
                 marketo_functions.getLeadActivities, token, lead_id)
            test(f"getLeadChanges({lead_id})",
                 marketo_functions.getLeadChanges, token, lead_id)
        else:
            print(f"         No lead found for '{test_email}'")
            skip("getLeadActivities", "no lead found")
            skip("getLeadChanges", "no lead found")
    else:
        skip("lookupLead", "no email provided")
        skip("getLeadActivities", "no email provided")
        skip("getLeadChanges", "no email provided")

    print_summary()


# ============================================================================
# Write-Only Tests (create, clone, update, delete)
# ============================================================================

def run_write_tests():
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("WRITE OPERATIONS TESTS")
    print("=" * 60)
    print("\nThese tests will CREATE, UPDATE, and CLONE assets in Marketo.")
    print("Test assets will be prefixed with 'MCPTEST_' for easy cleanup.\n")

    # Get a fresh token (needed for asset lookups and tests)
    token = marketo_functions.getToken()

    # Collect required inputs (resolve by name, save IDs for future runs)
    print("--- Test Configuration ---")
    folder_id = resolve_asset("folder_id",
                              "Folder name to create test assets in: ",
                              lambda name: marketo_functions.getFolderByName(token, name))
    if not folder_id:
        print("Folder is required for write tests. Skipping.")
        return

    program_type = get_test_var("program_type", "Program type to be created (e.g. 'Default', 'Email', 'Engagement', 'Event'):", required=True)
    if not program_type:
        print("Program type is required for program creation. Skipping.")
        return

    # Fetch available channels to help the user choose
    available_channels = marketo_functions.getChannels(token)
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

    trigger_campaign_id = resolve_asset("trigger_campaign_id",
                                        "Trigger Campaign name for activate/deactivate tests (or Enter to skip): ",
                                        lambda name: marketo_functions.getSmartCampaignByName(token, name))
    batch_campaign_id = resolve_asset("batch_campaign_id",
                                      "Batch Campaign name for schedule tests (or Enter to skip): ",
                                      lambda name: marketo_functions.getSmartCampaignByName(token, name))
    request_campaign_id = resolve_asset("request_campaign_id",
                                        "Request Campaign name for request campaign test (or Enter to skip): ",
                                        lambda name: marketo_functions.getSmartCampaignByName(token, name))
    lead_id = resolve_lead("lead_id",
                           "Lead email for request campaign test (or Enter to skip): ",
                           token)
    email_program_id = resolve_asset("email_program_id",
                                     "Email Program name for clone/approve/unapprove tests (or Enter to skip): ",
                                     lambda name: marketo_functions.getProgramByName(token, name))

    # --- Smart Campaign Tests ---
    print("\n--- Create Smart Campaign ---")
    created_campaign = test("createSmartCampaign('MCPTEST_Campaign')",
                           marketo_functions.createSmartCampaign,
                           token, "MCPTEST_Campaign", folder_id, "Test campaign from MCP test suite")

    if created_campaign and created_campaign.get('result'):
        new_campaign_id = created_campaign['result'][0]['id']
        created_assets['campaigns'].append(new_campaign_id)
        print(f"         Created campaign ID: {new_campaign_id}")

        print("\n--- Update Smart Campaign ---")
        test(f"updateSmartCampaign({new_campaign_id})",
             marketo_functions.updateSmartCampaign,
             token, new_campaign_id, name="MCPTEST_Campaign_Updated",
             description="Updated by test suite")
    else:
        skip("updateSmartCampaign", "create failed")

    # Clone using the first available campaign from trigger/batch/request
    clone_source_id = trigger_campaign_id or batch_campaign_id or request_campaign_id
    if clone_source_id:
        print("\n--- Clone Smart Campaign ---")
        cloned_campaign = test(f"cloneSmartCampaign({clone_source_id})",
                               marketo_functions.cloneSmartCampaign,
                               token, clone_source_id, "MCPTEST_Campaign_Clone", folder_id)
        if cloned_campaign and cloned_campaign.get('result'):
            created_assets['campaigns'].append(cloned_campaign['result'][0]['id'])
    else:
        skip("cloneSmartCampaign", "no campaigns provided")

    # --- Activate / Deactivate ---
    if trigger_campaign_id:
        print("\n--- Activate Smart Campaign ---")
        test(f"activateSmartCampaign({trigger_campaign_id})",
             marketo_functions.activateSmartCampaign,
             token, trigger_campaign_id)

        print("\n--- Deactivate Smart Campaign ---")
        test(f"deactivateSmartCampaign({trigger_campaign_id})",
             marketo_functions.deactivateSmartCampaign,
             token, trigger_campaign_id)
    else:
        print("\n--- Activate/Deactivate Smart Campaign ---")
        skip("activateSmartCampaign", "no trigger campaign provided")
        skip("deactivateSmartCampaign", "no trigger campaign provided")

    # --- Schedule Batch Campaign ---
    if batch_campaign_id:
        print("\n--- Schedule Batch Campaign ---")
        print("  WARNING: This will schedule the batch campaign to run.")
        confirm = input("  Proceed? (y/n): ").strip().lower()
        if confirm in ('y', 'yes'):
            test(f"scheduleBatchCampaign({batch_campaign_id})",
                 marketo_functions.scheduleBatchCampaign,
                 token, batch_campaign_id)
        else:
            skip("scheduleBatchCampaign", "user declined")
    else:
        print("\n--- Schedule Batch Campaign ---")
        skip("scheduleBatchCampaign", "no batch campaign provided")

    # --- Request Campaign ---
    if request_campaign_id and lead_id:
        print("\n--- Request Campaign ---")
        print("  WARNING: This will trigger the request campaign for the lead.")
        confirm = input("  Proceed? (y/n): ").strip().lower()
        if confirm in ('y', 'yes'):
            test(f"requestCampaign({request_campaign_id}, [{lead_id}])",
                 marketo_functions.requestCampaign,
                 token, request_campaign_id, [lead_id])
        else:
            skip("requestCampaign", "user declined")
    else:
        print("\n--- Request Campaign ---")
        skip("requestCampaign", "no request campaign or lead provided")

    # --- Program Tests ---
    print("\n--- Create Program ---")
    created_program = test("createProgram('MCPTEST_Program')",
                          marketo_functions.createProgram,
                          token, "MCPTEST_Program", folder_id, program_type, channel,
                          description="Test program from MCP test suite")

    if created_program and created_program.get('result'):
        new_program_id = created_program['result'][0]['id']
        created_assets['programs'].append(new_program_id)
        print(f"         Created program ID: {new_program_id}")

        print("\n--- Update Program ---")
        test(f"updateProgram({new_program_id})",
             marketo_functions.updateProgram,
             token, new_program_id, description="Updated by test suite")
    else:
        skip("updateProgram", "create failed")

    if email_program_id:
        print("\n--- Clone Program ---")
        cloned_program = test(f"cloneProgram({email_program_id})",
                              marketo_functions.cloneProgram,
                              token, email_program_id, "MCPTEST_Program_Clone", folder_id)
        if cloned_program and cloned_program.get('result'):
            created_assets['programs'].append(cloned_program['result'][0]['id'])
    else:
        skip("cloneProgram", "no email program provided")

    # --- Approve / Unapprove Email Program ---
    if email_program_id:
        print("\n--- Approve Email Program ---")
        test(f"approveEmailProgram({email_program_id})",
             marketo_functions.approveEmailProgram,
             token, email_program_id)

        print("\n--- Unapprove Email Program ---")
        test(f"unapproveEmailProgram({email_program_id})",
             marketo_functions.unapproveEmailProgram,
             token, email_program_id)
    else:
        print("\n--- Approve/Unapprove Email Program ---")
        skip("approveEmailProgram", "no email program provided")
        skip("unapproveEmailProgram", "no email program provided")

    # --- Token Tests ---
    print("\n--- Create Token ---")
    created_token = test(f"createToken({folder_id}, 'MCPTEST_Token')",
                        marketo_functions.createToken,
                        token, folder_id, "MCPTEST_Token", "text",
                        "Test value from MCP test suite", "Folder")

    if created_token and not created_token.get('errors'):
        created_assets['tokens'].append((folder_id, "MCPTEST_Token", "text", "Folder"))

        print("\n--- Update Token ---")
        test(f"updateToken({folder_id}, 'MCPTEST_Token')",
             marketo_functions.updateToken,
             token, folder_id, "MCPTEST_Token", "text",
             "Updated value from MCP test suite", "Folder")
    else:
        skip("updateToken", "create failed")

    print_summary()

    # --- Cleanup ---
    cleanup_test_assets(token, folder_id)


# ============================================================================
# Full Tests (read-only + write operations)
# ============================================================================

def run_full_tests():
    run_readonly_tests()
    run_write_tests()


# ============================================================================
# Cleanup
# ============================================================================

def cleanup_test_assets(token, folder_id):
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
            result = marketo_functions.deleteSmartCampaign(token, cid)
            if result.get('success'):
                print(f"  [DELETED] Smart Campaign {cid}")
            else:
                print(f"  [FAILED]  Smart Campaign {cid} - {result.get('errors', result)}")
        except Exception as e:
            print(f"  [FAILED]  Smart Campaign {cid} - {e}")

    for pid in created_assets['programs']:
        try:
            result = marketo_functions.deleteProgram(token, pid)
            if result.get('success'):
                print(f"  [DELETED] Program {pid}")
            else:
                print(f"  [FAILED]  Program {pid} - {result.get('errors', result)}")
        except Exception as e:
            print(f"  [FAILED]  Program {pid} - {e}")

    for (fid, name, ttype, ftype) in created_assets['tokens']:
        try:
            result = marketo_functions.deleteToken(token, fid, name, ttype, ftype)
            if result.get('success'):
                print(f"  [DELETED] Token '{name}' from {ftype} {fid}")
            else:
                print(f"  [FAILED]  Token '{name}' - {result.get('errors', result)}")
        except Exception as e:
            print(f"  [FAILED]  Token '{name}' - {e}")

    print("\nCleanup complete.")


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    load_test_config()

    print("=" * 60)
    print("Marketo Functions - Direct Test Suite")
    print("=" * 60)
    print("\n1. Read-only tests (safe, no modifications)")
    print("2. Write-only tests (create, clone, update, delete)")
    print("3. Full tests (read-only + write operations)")

    choice = input("\nSelect test mode (1, 2, or 3): ").strip()

    if choice == '2':
        run_write_tests()
    elif choice == '3':
        run_full_tests()
    else:
        run_readonly_tests()
