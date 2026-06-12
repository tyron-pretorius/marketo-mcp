"""
Test script for marketo_functions.py - calls functions directly.

Interactive run: python test_marketo_functions.py
    Prompts for a test mode (1=read-only, 2=write, 3=full) and for any
    asset names/emails it needs. Inputs are saved to test_config.json.

Auto run: python test_marketo_functions.py --auto
    Non-interactive FULL-COVERAGE suite: a dependency-ordered step engine
    (modeled on test_blended_server.py's full mode) exercises EVERY public
    function in marketo_functions.py against a real sandbox. Credentials are
    loaded from .env (via marketo_functions) with a fallback to .env.sandbox
    (MARKETO_CLIENT_ID / MARKETO_CLIENT_SECRET / MARKETO_MUNCHKIN_ID, with
    MARKETO_BASE_URL derived as https://{munchkin}.mktorest.com).

    All created assets are named MCPTEST_LEG_* and removed at the end; a
    sweep also clears MCPTEST_LEG_* leftovers at start and end so reruns are
    repeatable. Objects Marketo cannot delete via API (lead / program-member
    fields, the custom activity type, the custom object type) use fixed
    names with reuse-if-exists semantics. Steps are classified PASS / SKIP
    (with a reason: feature not enabled, state-dependent rejection, pending
    bulk job, ...) / FAIL. Exit code is non-zero if anything FAILs or any
    public function is left uncovered.

    Notable chains (each tests several operations in one flow):
      - syncLeads(createOnly) -> syncLeads(createDuplicate) -> mergeLeads
      - tag-type discovery -> createProgram with required tags (702 guard)
      - import batch -> status poll -> failures -> warnings
      - export create -> enqueue -> status poll -> file (+ cancel on a 2nd job)

Group runs: python test_marketo_functions.py --group bulk-export
            python test_marketo_functions.py --group bulk-import
    Run ONLY the bulk-export / bulk-import steps plus minimal prerequisites
    (a few leads, one program, the custom object type). Export jobs are kept
    tiny: the activity window covers just this run's own activities, and the
    program-member / custom-object exports are scoped to this run's assets.
    Imports are 2-3 rows. Exit code reflects FAILs only (full coverage is
    not enforced for group runs).
"""

import argparse
import inspect
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import marketo_functions

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_CONFIG_FILE = os.path.join(SCRIPT_DIR, "test_config.json")
ENV_SANDBOX_FILE = os.path.join(SCRIPT_DIR, ".env.sandbox")

AUTO_MODE = False
AUTO_TEST_EMAIL = "mcptest@example.invalid"
AUTO_PREFIX = "MCPTEST_LEG_"
SAMPLE_EMAIL_TO = "tyron.pretorius+mcptest@knak.com"
INVITE_EMAIL = "tyron.pretorius+mcptestleginvite@knak.com"

# Marketo error codes that mean "asset is not in the required state" for
# operations that need fuller setup (activate/schedule/approve/etc.).
# In auto mode these are reported as SKIP, not FAIL.
STATE_ERROR_CODES = {'709', '1003', '1004', '1006', '1042'}

# Fixed-name objects that Marketo cannot delete via API: reuse across runs.
LEAD_FIELD = "mcptestLegField1"
PM_FIELD = "mcptestLegPmField1"
ACT_TYPE = "mcptestlegact1"
CO_TYPE = "mcptest_leg_co"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
POLL_INTERVAL = 5
POLL_TIMEOUT = 90

_test_config = {}


# ============================================================================
# Credentials
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


def ensure_credentials():
    """Make sure marketo_functions has credentials.

    marketo_functions loads .env on import. If any value is missing, fall
    back to .env.sandbox, deriving MARKETO_BASE_URL from the munchkin ID.
    Returns True if credentials are available.
    """
    if (marketo_functions.base_url and marketo_functions.client_id
            and marketo_functions.client_secret):
        return True

    sandbox = parse_env_file(ENV_SANDBOX_FILE)
    client_id = marketo_functions.client_id or sandbox.get('MARKETO_CLIENT_ID')
    client_secret = marketo_functions.client_secret or sandbox.get('MARKETO_CLIENT_SECRET')
    base_url = marketo_functions.base_url or sandbox.get('MARKETO_BASE_URL')
    if not base_url and sandbox.get('MARKETO_MUNCHKIN_ID'):
        base_url = f"https://{sandbox['MARKETO_MUNCHKIN_ID']}.mktorest.com"

    if not (client_id and client_secret and base_url):
        return False

    marketo_functions.client_id = client_id
    marketo_functions.client_secret = client_secret
    marketo_functions.base_url = base_url
    os.environ['MARKETO_CLIENT_ID'] = client_id
    os.environ['MARKETO_CLIENT_SECRET'] = client_secret
    os.environ['MARKETO_BASE_URL'] = base_url
    return True


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


def resolve_asset(config_key, prompt, lookup_fn):
    """Resolve an asset by name, with disambiguation if multiple matches found."""
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


# ============================================================================
# Test bookkeeping & coverage
# ============================================================================

passed = 0
failed = 0
skipped = 0

skip_reasons = []  # list of (test_name, reason)

# Every public function defined in marketo_functions.py
ALL_FUNCTIONS = sorted(
    name for name, obj in inspect.getmembers(marketo_functions, inspect.isfunction)
    if obj.__module__ == 'marketo_functions' and not name.startswith('_')
)

executed_functions = set()   # functions actually called by a test
skipped_functions = set()    # functions whose test was skipped

# Track created assets for cleanup (interactive write tests)
created_assets = {
    'campaigns': [],   # list of (campaign_id, name)
    'programs': [],    # list of (program_id, name)
    'tokens': []       # list of (folder_id, name, token_type, folder_type) tuples
}


def record_skip_coverage(test_name):
    """If a skipped test's name maps to a known function, record it."""
    fname = test_name.split('(')[0].strip()
    if fname in ALL_FUNCTIONS:
        skipped_functions.add(fname)


def test(test_name, func, *args, allowed_errors=None, **kwargs):
    """Run a single test and track the result (interactive modes).

    allowed_errors: set of Marketo error codes (strings) that indicate the
    target asset is not in the required state - reported as SKIP, not FAIL.
    """
    global passed, failed, skipped
    fname = getattr(func, '__name__', '')
    if fname in ALL_FUNCTIONS:
        executed_functions.add(fname)
    try:
        result = func(*args, **kwargs)

        if isinstance(result, dict) and result.get('errors'):
            codes = {str(e.get('code')) for e in result['errors'] if isinstance(e, dict)}
            if allowed_errors and codes & {str(c) for c in allowed_errors}:
                reason = '; '.join(
                    f"{e.get('code')}: {e.get('message')}" for e in result['errors']
                )
                print(f"  [SKIP] {test_name} - expected state error ({reason})")
                skip_reasons.append((test_name, f"expected state error ({reason})"))
                skipped += 1
                return None
            print(f"  [FAIL] {test_name}")
            print(f"         {result['errors']}")
            failed += 1
            return None

        if isinstance(result, dict) and 'success' in result and result['success'] is not True:
            print(f"  [FAIL] {test_name}")
            print(f"         success={result.get('success')} with no errors: {result}")
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
    """Print which marketo_functions were exercised by this run."""
    covered = executed_functions | skipped_functions
    uncovered = [f for f in ALL_FUNCTIONS if f not in covered]
    skipped_only = sorted(skipped_functions - executed_functions)

    print(f"\n{'=' * 60}")
    print(f"COVERAGE: covered {len(covered & set(ALL_FUNCTIONS))}/{len(ALL_FUNCTIONS)} functions "
          f"({len(executed_functions & set(ALL_FUNCTIONS))} executed, "
          f"{len(skipped_only)} skipped-only)")
    if skipped_only:
        print(f"  Skipped-only: {', '.join(skipped_only)}")
    if uncovered:
        print(f"  UNCOVERED: {', '.join(uncovered)}")
        if not enforce:
            print("  (coverage not enforced for group runs)")
    else:
        print("  All functions covered.")
    print(f"{'=' * 60}")
    return uncovered


# ============================================================================
# Auto-mode discovery helpers
# ============================================================================

def discover_channels(channels_result):
    """Find a channel for a Default program (with >=2 statuses) and one for
    an Email program. Returns (default_channel, email_channel, statuses)."""
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


def discover_required_tags(token, applicable_program_type):
    """Find required program tag types and pick an allowed value for each.

    Some instances require tags on program creation (error 702 otherwise).
    Uses the asset API directly since the legacy wrapper has no tag functions.
    """
    headers = {'Authorization': 'Bearer ' + token}
    tags = []
    try:
        resp = requests.get(
            marketo_functions.base_url + '/rest/asset/v1/tagTypes.json',
            headers=headers, params={'maxReturn': 200}, timeout=30
        ).json()
        for tag_type in resp.get('result') or []:
            if not tag_type.get('required'):
                continue
            applicable = (tag_type.get('applicableProgramTypes') or '')
            applicable = [a.strip() for a in applicable.strip('[]').split(',') if a.strip()]
            if applicable and applicable_program_type and applicable_program_type not in applicable:
                continue
            detail = requests.get(
                marketo_functions.base_url + '/rest/asset/v1/tagType/byName.json',
                headers=headers, params={'name': tag_type['tagType']}, timeout=30
            ).json()
            detail_result = (detail.get('result') or [{}])[0]
            values = [v.strip() for v in
                      (detail_result.get('allowableValues') or '').strip('[]').split(',')
                      if v.strip()]
            if values:
                tags.append({'tagType': tag_type['tagType'], 'tagValue': values[0]})
    except Exception as e:
        print(f"  (tag discovery failed: {e})")
    return tags


# ============================================================================
# Read-Only Tests (interactive)
# ============================================================================

def run_readonly_tests():
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("MARKETO FUNCTIONS - READ-ONLY TESTS")
    print("=" * 60)

    print("\n--- Authentication ---")
    try:
        token = marketo_functions.getToken()
        executed_functions.add('getToken')
        print(f"  [PASS] getToken()")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] getToken() - {e}")
        failed += 1
        print("\nAuthentication failed. Cannot continue.")
        print_summary()
        return

    print("\n--- Activity Types ---")
    activity_types = test("getActivityTypes", marketo_functions.getActivityTypes, token)
    if activity_types and activity_types.get('result'):
        print(f"         Found {len(activity_types['result'])} activity types")

    print("\n--- Paging Token ---")
    since_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    test("getPagingToken", marketo_functions.getPagingToken, token, since_date)

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

    print("\n--- Folder By Name (auto-discovered) ---")
    if folders and folders.get('result'):
        folder_name = folders['result'][0]['name']
        test(f"getFolderByName('{folder_name}')",
             marketo_functions.getFolderByName, token, folder_name)
    else:
        skip("getFolderByName", "no folders found in browse")

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

    print("\n--- Lead Lookup Tests ---")
    test_email = get_test_var("test_email", "Enter a test email address for lead lookup (or Enter to skip): ")

    if test_email:
        lead_data = test(f"lookupLead('email', '{test_email}')",
                         marketo_functions.lookupLead, token, "email", test_email)

        lead_id = None
        if lead_data and lead_data.get('result'):
            lead_id = lead_data['result'][0]['id']
            print(f"         Found lead ID: {lead_id}")

        if lead_id is not None:
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
# Write-Only Tests (interactive: create, clone, update, delete)
# ============================================================================

def run_write_tests():
    global passed, failed, skipped

    print("\n" + "=" * 60)
    print("WRITE OPERATIONS TESTS")
    print("=" * 60)
    print(f"\nThese tests will CREATE, UPDATE, and CLONE assets in Marketo.")
    print(f"Test assets will be prefixed with 'MCPTEST_' for easy cleanup.\n")

    token = marketo_functions.getToken()
    executed_functions.add('getToken')

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
    merge_winner_id = resolve_lead("merge_winner_lead_id",
                                   "Winning lead email for merge test (or Enter to skip): ",
                                   token)
    merge_loser_id = resolve_lead("merge_loser_lead_id",
                                  "Losing lead email for merge test (or Enter to skip): ",
                                  token)

    print("\n--- Create Smart Campaign ---")
    created_campaign = test("createSmartCampaign('MCPTEST_Campaign')",
                           marketo_functions.createSmartCampaign,
                           token, "MCPTEST_Campaign", folder_id, "Test campaign from MCP test suite")

    if created_campaign and created_campaign.get('result'):
        new_campaign_id = created_campaign['result'][0]['id']
        created_assets['campaigns'].append((new_campaign_id, "MCPTEST_Campaign_Updated"))
        print(f"         Created campaign ID: {new_campaign_id}")

        print("\n--- Update Smart Campaign ---")
        test(f"updateSmartCampaign({new_campaign_id})",
             marketo_functions.updateSmartCampaign,
             token, new_campaign_id, name="MCPTEST_Campaign_Updated",
             description="Updated by test suite")
    else:
        skip("updateSmartCampaign", "create failed")

    clone_source_id = trigger_campaign_id or batch_campaign_id or request_campaign_id
    if clone_source_id:
        print("\n--- Clone Smart Campaign ---")
        cloned_campaign = test(f"cloneSmartCampaign({clone_source_id})",
                               marketo_functions.cloneSmartCampaign,
                               token, clone_source_id, "MCPTEST_Campaign_Clone", folder_id)
        if cloned_campaign and cloned_campaign.get('result'):
            created_assets['campaigns'].append((cloned_campaign['result'][0]['id'], "MCPTEST_Campaign_Clone"))
    else:
        skip("cloneSmartCampaign", "no campaigns provided")

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

    if merge_winner_id and merge_loser_id:
        print("\n--- Merge Leads ---")
        print("  WARNING: This will PERMANENTLY merge the losing lead into the winning lead.")
        confirm = input("  Proceed? (y/n): ").strip().lower()
        if confirm in ('y', 'yes'):
            test(f"mergeLeads({merge_winner_id}, [{merge_loser_id}])",
                 marketo_functions.mergeLeads,
                 token, merge_winner_id, [merge_loser_id])
        else:
            skip("mergeLeads", "user declined")
    else:
        print("\n--- Merge Leads ---")
        skip("mergeLeads", "no winning/losing leads provided")

    print("\n--- Create Program ---")
    created_program = test("createProgram('MCPTEST_Program')",
                          marketo_functions.createProgram,
                          token, "MCPTEST_Program", folder_id, program_type, channel,
                          description="Test program from MCP test suite")

    if created_program and created_program.get('result'):
        new_program_id = created_program['result'][0]['id']
        created_assets['programs'].append((new_program_id, "MCPTEST_Program"))
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
            created_assets['programs'].append((cloned_program['result'][0]['id'], "MCPTEST_Program_Clone"))
    else:
        skip("cloneProgram", "no email program provided")

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

    cleanup_test_assets(token, folder_id)


def run_full_tests():
    run_readonly_tests()
    run_write_tests()


# ============================================================================
# Cleanup (interactive write tests)
# ============================================================================

def cleanup_test_assets(token, folder_id):
    """Delete test assets created during the run (prompts unless in auto mode)."""
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

    if AUTO_MODE:
        print(f"\nAuto mode: deleting all {total} test assets...")
    else:
        confirm = input(f"\nDelete all {total} test assets? (y/n): ").strip().lower()
        if confirm not in ('y', 'yes'):
            print("Skipping cleanup. You can delete these manually in Marketo.")
            return

    print("\n--- Deleting test assets ---")

    for (fid, name, ttype, ftype) in created_assets['tokens']:
        executed_functions.add('deleteToken')
        try:
            result = marketo_functions.deleteToken(token, fid, name, ttype, ftype)
            if result.get('success'):
                print(f"  [DELETED] Token '{name}' from {ftype} {fid}")
            else:
                print(f"  [FAILED]  Token '{name}' - {result.get('errors', result)}")
        except Exception as e:
            print(f"  [FAILED]  Token '{name}' - {e}")

    for cid, cname in created_assets['campaigns']:
        executed_functions.add('deleteSmartCampaign')
        try:
            result = marketo_functions.deleteSmartCampaign(token, cid)
            if result.get('success'):
                print(f"  [DELETED] Smart Campaign {cid}")
            else:
                print(f"  [FAILED]  Smart Campaign {cid} - {result.get('errors', result)}")
        except Exception as e:
            print(f"  [FAILED]  Smart Campaign {cid} - {e}")

    for pid, pname in created_assets['programs']:
        executed_functions.add('deleteProgram')
        try:
            result = marketo_functions.deleteProgram(token, pid)
            if result.get('success'):
                print(f"  [DELETED] Program {pid}")
            else:
                print(f"  [FAILED]  Program {pid} - {result.get('errors', result)}")
        except Exception as e:
            print(f"  [FAILED]  Program {pid} - {e}")

    print("\nCleanup complete.")

    print("\n--- Verifying cleanup ---")
    leftovers = []
    for cid, cname in created_assets['campaigns']:
        try:
            check = marketo_functions.getSmartCampaignByName(token, cname)
            if check.get('result'):
                leftovers.append(f"Smart Campaign '{cname}' (ID {cid})")
        except Exception:
            pass
    for pid, pname in created_assets['programs']:
        try:
            check = marketo_functions.getProgramByName(token, pname)
            if check.get('result'):
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
# FULL AUTO SUITE - dependency-ordered step engine (mirrors the design of
# test_blended_server.py's full mode, adapted to direct function calls).
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
    """Direct REST helpers for infrastructure marketo_functions lacks
    (folder/form/email/snippet/list creation, tag discovery, job polling).
    These are NOT part of the library surface under test - they only build
    the fixtures the real function steps run against."""

    def __init__(self, holder):
        self.holder = holder  # {'token': ...} kept fresh by the runner

    def _headers(self, content_type=None):
        h = {'Authorization': 'Bearer ' + self.holder['token']}
        if content_type:
            h['Content-Type'] = content_type
        return h

    def get(self, path, params=None):
        return requests.get(marketo_functions.base_url + path,
                            headers=self._headers(), params=params, timeout=30).json()

    def post(self, path, data=None, json_body=None):
        return requests.post(marketo_functions.base_url + path,
                             headers=self._headers(), data=data, json=json_body,
                             timeout=60).json()

    # -- folders ------------------------------------------------------------
    def browse_folders(self, root_id, root_type="Folder", max_depth=2, max_return=200):
        return self.get('/rest/asset/v1/folders.json',
                        {'root': json.dumps({"id": root_id, "type": root_type}),
                         'maxDepth': max_depth, 'maxReturn': max_return})

    def find_roots(self):
        """Locate Marketing Activities Default + Design Studio content roots."""
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
        return requests.post(
            marketo_functions.base_url + f'/rest/v1/lists/{list_id}/leads.json',
            headers=self._headers('application/json'),
            json={'input': [{'id': i} for i in lead_ids]}, timeout=30).json()

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


# ---------------------------------------------------------------------------
# Step engine
# ---------------------------------------------------------------------------

def step(fn, args=None, *, name=None, save=None, skip_if=None, skip_on=(),
         skip_errors=None, poll=None, after=None, infra=False, covers=None,
         retries=0, notes=""):
    """Build one suite step.

    fn          marketo_functions function (counted for coverage) or, with
                infra=True, any callable(**kwargs) used purely as fixture
                plumbing (not counted).
    args        dict, or callable(ctx) -> dict of keyword args. A KeyError
                inside the callable marks the step SKIP (dependency missing).
    save        callable(ctx, data) run after a PASS; raising marks FAIL.
    skip_if     callable(ctx) -> falsy | reason-string, evaluated pre-call.
    skip_on     iterable of (match, reason): match is a Marketo error code or
                lowercase message substring; a matching error -> SKIP.
    skip_errors reason string: ANY structured Marketo error or exception
                (except auth 601/602) -> SKIP with this reason.
    poll        {'done': fn(data)->bool, 'flag': ctx_key} - re-call every
                POLL_INTERVAL until done() or POLL_TIMEOUT; ctx[flag]=done.
    after       callable(ctx, status, data) always run, even on SKIP/FAIL.
    covers      extra function names to mark covered when this step runs.
    """
    return {
        "fn": fn, "args": args or {}, "name": name or getattr(fn, '__name__', str(fn)),
        "save": save, "skip_if": skip_if, "skip_on": tuple(skip_on),
        "skip_errors": skip_errors, "poll": poll, "after": after,
        "infra": infra, "covers": tuple(covers or ()), "retries": retries,
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
    if data.get('success') is False:
        return True
    if data.get('errors'):
        return True
    if data.get('error'):
        return True
    return False


def _job_status(data):
    if isinstance(data, dict):
        data = data.get('result') or []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get('status', '')).lower()
    return ""


def _job_done(data):
    return _job_status(data) in ('complete', 'completed', 'failed')


def _classify(st, data):
    """Classify a result into (status, reason)."""
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


class SuiteRunner:
    def __init__(self, holder):
        self.holder = holder
        self.records = []  # (name, kind, status, reason, secs)

    def _refresh_token(self):
        try:
            self.holder['token'] = marketo_functions.getToken()
        except Exception as exc:
            print(f"  (token refresh failed: {exc})")

    def _call(self, st, args):
        if st['infra']:
            return st['fn'](**args)
        result = st['fn'](self.holder['token'], **args)
        codes, _ = _marketo_errors(result) if isinstance(result, dict) else ([], "")
        if {'601', '602'} & set(codes):
            self._refresh_token()
            result = st['fn'](self.holder['token'], **args)
        return result

    def _execute(self, st, args):
        try:
            data = self._call(st, args)
        except Exception as exc:
            msg = f"{type(exc).__name__}: {exc}"
            low = msg.lower()
            for match, reason in st['skip_on']:
                if str(match).lower() in low:
                    return SKIP, f"{reason}: {msg[:140]}", None
            if st['skip_errors']:
                return SKIP, f"{st['skip_errors']}: {msg[:140]}", None
            return FAIL, msg[:200], None
        status, reason = _classify(st, data)
        return status, reason, data

    def run_step(self, st, ctx):
        kind = "INFRA" if st['infra'] else "FN"
        fname = getattr(st['fn'], '__name__', '')

        def mark(status):
            if not st['infra'] and fname in ALL_FUNCTIONS:
                (skipped_functions if status == SKIP else executed_functions).add(fname)
            for extra in st['covers']:
                (skipped_functions if status == SKIP else executed_functions).add(extra)

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
        status, reason, data = self._execute(st, args)
        attempts = 0
        transient = ('rate limit', 'concurrent access', 'timed out', 'temporarily unavailable')
        while status == FAIL and (
                attempts < st.get('retries', 0)
                or (attempts < st.get('retries', 0) + 2
                    and any(t in str(reason).lower() for t in transient))):
            attempts += 1
            time.sleep(5)
            self._refresh_token()
            status, reason, data = self._execute(st, args)

        if status == PASS and st['poll']:
            deadline = started + POLL_TIMEOUT

            def _done(payload):
                try:
                    return bool(st['poll']['done'](payload))
                except Exception:
                    return False

            while not _done(data) and time.time() < deadline:
                time.sleep(POLL_INTERVAL)
                status, reason, data = self._execute(st, args)
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
        print(f"{marker} [{len(self.records):3d}] {kind:<6} {name:<48} {status}"
              + (f"  ({str(reason)[:90]})" if reason else ""), flush=True)


# ---------------------------------------------------------------------------
# Suite definition helpers
# ---------------------------------------------------------------------------

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
# MCPTEST_LEG_* sweep (start + end): clears leftovers from crashed runs
# ---------------------------------------------------------------------------

def sweep_mcptest_leg(holder, R):
    """Best-effort removal of every MCPTEST_LEG_* asset in the sandbox.

    Only touches assets whose name starts with the MCPTEST_LEG_ prefix, so a
    concurrently-running MCPTEST_FULL_* suite is never disturbed."""
    token = holder['token']
    prefix = AUTO_PREFIX
    removed = []

    def _paged(browse_fn, **kwargs):
        items = []
        for page in range(30):
            try:
                resp = browse_fn(token, maxReturn=200, offset=page * 200, **kwargs)
            except Exception:
                break
            batch = resp.get('result') or [] if isinstance(resp, dict) else []
            items.extend(batch)
            if len(batch) < 200:
                break
        return items

    # emails (unapprove first so delete succeeds)
    for e in _paged(marketo_functions.browseEmails):
        if str(e.get('name', '')).startswith(prefix):
            marketo_functions.unapproveEmail(token, e['id'])
            r = marketo_functions.deleteEmail(token, e['id'])
            removed.append(('email', e['name'], r.get('success')))
    # email templates
    for t in _paged(marketo_functions.browseEmailTemplates):
        if str(t.get('name', '')).startswith(prefix):
            marketo_functions.unapproveEmailTemplate(token, t['id'])
            r = marketo_functions.deleteEmailTemplate(token, t['id'])
            removed.append(('emailTemplate', t['name'], r.get('success')))
    # landing pages then LP templates
    for lp in _paged(marketo_functions.browseLandingPages):
        if str(lp.get('name', '')).startswith(prefix):
            marketo_functions.unapproveLandingPage(token, lp['id'])
            r = marketo_functions.deleteLandingPage(token, lp['id'])
            removed.append(('landingPage', lp['name'], r.get('success')))
    for t in _paged(marketo_functions.browseLandingPageTemplates):
        if str(t.get('name', '')).startswith(prefix):
            marketo_functions.unapproveLandingPageTemplate(token, t['id'])
            r = marketo_functions.deleteLandingPageTemplate(token, t['id'])
            removed.append(('lpTemplate', t['name'], r.get('success')))
    # forms / snippets / static lists (browsed via REST; no browse functions)
    try:
        for f in (R.browse_forms().get('result') or []):
            if str(f.get('name', '')).startswith(prefix):
                r = marketo_functions.deleteForm(token, f['id'])
                removed.append(('form', f['name'], r.get('success')))
    except Exception:
        pass
    try:
        for s in (R.browse_snippets().get('result') or []):
            if str(s.get('name', '')).startswith(prefix):
                marketo_functions.unapproveSnippet(token, s['id'])
                r = marketo_functions.deleteSnippet(token, s['id'])
                removed.append(('snippet', s['name'], r.get('success')))
    except Exception:
        pass
    try:
        for l in (R.browse_static_lists().get('result') or []):
            if str(l.get('name', '')).startswith(prefix):
                r = marketo_functions.deleteStaticList(token, l['id'])
                removed.append(('staticList', l['name'], r.get('success')))
    except Exception:
        pass
    # standalone smart campaigns, then programs (program delete removes children)
    for c in _paged(marketo_functions.browseSmartCampaigns):
        if str(c.get('name', '')).startswith(prefix):
            r = marketo_functions.deleteSmartCampaign(token, c['id'])
            removed.append(('smartCampaign', c['name'], r.get('success')))
    for p in _paged(marketo_functions.browsePrograms):
        if str(p.get('name', '')).startswith(prefix):
            r = marketo_functions.deleteProgram(token, p['id'])
            removed.append(('program', p['name'], r.get('success')))
    # scratch folders under MA Default + DS content roots
    try:
        roots = R.find_roots()
        candidates = []
        for key in ('ma_parent', 'ds_forms_root', 'ds_emails_root', 'ds_etpl_root',
                    'ds_lp_root', 'ds_lpt_root', 'ds_snip_root'):
            if roots.get(key):
                for f in (R.browse_folders(roots[key], max_depth=1).get('result') or []):
                    if str(f.get('name', '')).startswith(prefix):
                        candidates.append(f)
        for f in candidates:
            fid = f['id'] if not isinstance(f['id'], dict) else f['id'].get('id')
            r = marketo_functions.deleteFolder(token, fid)
            removed.append(('folder', f['name'], r.get('success')))
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
# Full step plan
# ---------------------------------------------------------------------------

GROUP_EXPORT = 'bulk-export'
GROUP_IMPORT = 'bulk-import'


def build_full_steps(sfx, R, group=None):
    """Return the dependency-ordered step list. group=None builds the full
    suite; 'bulk-export' / 'bulk-import' build just that group plus minimal
    prerequisites (leads, one program, the custom object type)."""
    mf = marketo_functions
    now = datetime.now(timezone.utc)
    run_start = now
    full = group is None
    email = lambda n: f"mcptest_leg_{sfx}_{n}@example.invalid"
    name = lambda label: f"{AUTO_PREFIX}{label}_{sfx}"
    steps = []
    add = steps.append

    # ================================================================ A. discovery + read-only basics
    def save_channel(ctx, data):
        default_ch, email_ch, statuses = discover_channels(data.get('result'))
        if not default_ch:
            raise KeyError('no program-type channel with >=2 statuses')
        ctx['channel'] = default_ch['name']
        ctx['statuses'] = statuses
        if email_ch:
            ctx['email_channel'] = email_ch['name']
            ctx['email_channel_type'] = (email_ch.get('applicableProgramType') or '').lower()

    add(step(mf.getChannels, {'maxReturn': 200}, save=save_channel))

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

    add(step(find_roots_step, infra=True, name='infra:find_roots',
             save=lambda c, d: c.update({k: v for k, v in d.items() if k != 'success'})))
    add(step(lambda **kw: R.create_folder(**kw),
             lambda c: {'name': name('MA'), 'parent_id': c['ma_parent']},
             infra=True, name='infra:create_folder(MA)', save=_save_first_id('ma_folder')))

    if full:
        for ctx_key, root_key, label in [
            ('ds_forms', 'ds_forms_root', 'FORMS'),
            ('ds_emails', 'ds_emails_root', 'EMAILS'),
            ('ds_etpl', 'ds_etpl_root', 'ETPL'),
            ('ds_lp', 'ds_lp_root', 'LP'),
            ('ds_lpt', 'ds_lpt_root', 'LPT'),
            ('ds_snip', 'ds_snip_root', 'SNIP'),
        ]:
            add(step(lambda **kw: R.create_folder(**kw),
                     (lambda rk, lb: lambda c: {'name': name(lb), 'parent_id': c[rk]})(root_key, label),
                     infra=True, name=f'infra:create_folder({label})',
                     save=_save_first_id(ctx_key)))

        add(step(mf.getActivityTypes))
        add(step(mf.getPagingToken, {'sinceDate': _iso(now - timedelta(days=1))}))
        add(step(mf.describeLeads))
        add(step(mf.describeLead2))
        add(step(mf.browseFolders, {'maxReturn': 20}))
        add(step(mf.getFolderByName, lambda c: {'name': name('MA')}))
        add(step(mf.getDailyUsage))
        add(step(mf.getWeeklyUsage))
        add(step(mf.getDailyErrors))
        add(step(mf.getWeeklyErrors))

    # ================================================================ B. leads (createOnly -> createDuplicate -> merge)
    def save_lead_ids(ctx, data):
        ids = [r['id'] for r in data['result'] if r.get('status') in ('created', 'updated')]
        if len(ids) < 3:
            raise KeyError(f"expected 3 created leads, got {data['result']}")
        ctx['lead1'], ctx['lead2'], ctx['lead3'] = ids[:3]

    add(step(mf.syncLeads,
             {'leads': [{'email': email(1), 'firstName': 'MCP', 'lastName': 'LegOne'},
                        {'email': email(2), 'firstName': 'MCP', 'lastName': 'LegTwo'},
                        {'email': email(3), 'firstName': 'MCP', 'lastName': 'LegThree'}],
              'action': 'createOnly'},
             name='syncLeads(createOnly)', save=save_lead_ids))

    if full:
        add(step(mf.syncLeads,
                 {'leads': [{'email': email(1), 'firstName': 'MCP', 'lastName': 'LegDupe'}],
                  'action': 'createDuplicate'},
                 name='syncLeads(createDuplicate)',
                 save=_save_first_id('dup1'),
                 notes='intentional duplicate of lead1, merged below'))

        def _lookup_via_override(filterType, filterValues):
            with mf.base_url_override(mf.base_url):
                return mf.lookupLead(SuiteRunner_token['token'], filterType, filterValues)

        add(step(_lookup_via_override,
                 {'filterType': 'email', 'filterValues': email(1)},
                 infra=True, name='lookupLead(via base_url_override)',
                 covers=('lookupLead', 'base_url_override'),
                 notes='exercises the base_url_override contextvar routing'))

        add(step(mf.getLeadById, lambda c: {'leadId': c['lead1'], 'fields': 'id,email'}))
        add(step(mf.getLeadFields, {'batchSize': 5}))
        add(step(mf.getLeadFieldByName, {'fieldApiName': 'email'}))
        add(step(mf.createLeadFields,
                 {'fields': [{'displayName': 'MCPTEST Leg Field1', 'name': LEAD_FIELD,
                              'dataType': 'string', 'description': 'MCPTEST_LEG suite field'}]},
                 skip_on=[('already exist', 'pre-existing lead field'),
                          ('1003', 'pre-existing lead field')],
                 notes='lead fields cannot be deleted via API; fixed name, reuse-if-exists'))
        add(step(mf.updateLeadField,
                 {'fieldApiName': LEAD_FIELD,
                  'updates': {'description': f'MCPTEST_LEG updated {sfx}'}}))
        add(step(mf.getLeadPartitions))
        add(step(mf.updateLeadPartitions,
                 lambda c: {'assignments': [{'id': c['lead1'], 'partitionName': 'Default'}]}))
        add(step(mf.getLeadChanges, lambda c: {'leadId': c['lead1'], 'daysBack': 1}))
        add(step(mf.getLeadActivities, lambda c: {'leadId': c['lead1'], 'daysBack': 1}))
        add(step(mf.getLeadActivitiesByEmail, {'email': email(1), 'daysBack': 1}))
        add(step(mf.associateLead,
                 lambda c: {'leadId': c['lead1'],
                            'cookie': 'id:287-GTJ-838&token:_mch-test-mcptest-leg'},
                 skip_errors='needs-real-cookie',
                 notes='fabricated Munchkin cookie; non-auth errors are expected'))
        add(step(mf.getLeadListMembership, lambda c: {'leadId': c['lead1']}))
        add(step(mf.getLeadProgramMembership, lambda c: {'leadId': c['lead1']}))
        add(step(mf.getLeadSmartCampaignMembership, lambda c: {'leadId': c['lead1']}))
        add(step(mf.mergeLeads,
                 lambda c: {'winningLeadId': c['lead1'], 'losingLeadIds': [c['dup1']]},
                 name='mergeLeads(dup-of-lead1 -> lead1)',
                 after=lambda c, s, d: c.__setitem__('dup1_merged', s == PASS),
                 notes='completes the createOnly -> createDuplicate -> merge chain'))

    # ================================================================ C. tags -> program (+ members)
    def discover_tags(**kwargs):
        # Required-tag discovery must not silently come back empty (the
        # sandbox rejects untagged programs with 702), so retry with a fresh
        # token a few times before accepting an empty result.
        for attempt in range(3):
            tags = discover_required_tags(SuiteRunner_token['token'], 'program')
            if tags:
                return {'success': True, 'result': tags}
            time.sleep(3)
            SuiteRunner_token['token'] = marketo_functions.getToken()
        return {'success': True, 'result': []}

    add(step(discover_tags, infra=True, name='infra:discover_required_tags',
             save=lambda c, d: c.__setitem__('program_tags', d['result']),
             notes='this sandbox REQUIRES program tags (error 702 without them)'))

    def create_program_args(c):
        kw = {'name': name('PROG'), 'folderId': c['ma_folder'], 'programType': 'Default',
              'channel': c['channel'], 'description': 'MCPTEST_LEG suite program'}
        if c.get('program_tags'):
            kw['tags'] = c['program_tags']
        return kw

    add(step(mf.createProgram, create_program_args, save=_save_first_id('program_id')))
    add(step(mf.changeLeadProgramStatus,
             lambda c: {'programId': c['program_id'], 'leadIds': [c['lead1']],
                        'status': c['statuses'][0]}))

    if full:
        add(step(mf.getProgramById, lambda c: {'programId': c['program_id']}))
        add(step(mf.getProgramByName, lambda c: {'name': name('PROG'), 'includeTags': True}))
        add(step(mf.browsePrograms, {'maxReturn': 5}))
        add(step(mf.updateProgram,
                 lambda c: {'programId': c['program_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step(mf.cloneProgram,
                 lambda c: {'programId': c['program_id'], 'name': name('PROG_CLONE'),
                            'folderId': c['ma_folder']},
                 save=_save_first_id('program_clone_id')))
        add(step(mf.pushLeads,
                 lambda c: {'leads': [{'email': email(4), 'firstName': 'MCP',
                                       'lastName': 'LegFour'}],
                            'lookupField': 'email', 'programName': name('PROG'),
                            'programStatus': c['statuses'][0]},
                 skip_if=_need('program_id'),
                 save=_save_key('lead4', 'result', 0, 'id')))
        add(step(mf.getLeadsByProgram,
                 lambda c: {'programId': c['program_id'], 'fields': 'id,email'}))
        add(step(mf.describeProgramMembers,
                 save=lambda c, d: c.__setitem__(
                     'pm_export_fields',
                     [n for n in ('leadId', 'program', 'programId', 'statusName',
                                  'reachedSuccess')
                      if n in {f.get('name') for f in
                               ((d.get('result') or [{}])[0].get('fields') or [])}][:2]
                     or ['leadId', 'program'])))
        add(step(mf.queryProgramMembers,
                 lambda c: {'programId': c['program_id'], 'filterType': 'leadId',
                            'filterValues': f"{c['lead1']},{c['lead2']}"}))
        add(step(mf.syncProgramMemberStatus,
                 lambda c: {'programId': c['program_id'], 'statusName': c['statuses'][0],
                            'leadIds': [c['lead2']]}))
        add(step(mf.createProgramMemberFields,
                 {'fields': [{'displayName': 'MCPTEST Leg PM Field1', 'name': PM_FIELD,
                              'dataType': 'string', 'description': 'MCPTEST_LEG PM field'}]},
                 skip_on=[('already exist', 'pre-existing PM field'),
                          ('1003', 'pre-existing PM field')],
                 notes='PM fields cannot be deleted via API; fixed name, reuse-if-exists'))
        add(step(mf.getProgramMemberFieldByName, {'fieldApiName': PM_FIELD}))
        add(step(mf.updateProgramMemberField,
                 {'fieldApiName': PM_FIELD,
                  'updates': [{'description': f'MCPTEST_LEG updated {sfx}'}]}))
        add(step(mf.syncProgramMemberData,
                 lambda c: {'programId': c['program_id'],
                            'members': [{'leadId': c['lead1'], PM_FIELD: f'value-{sfx}'}]},
                 skip_on=[('1006', 'no-pm-field'), ('invalid field', 'no-pm-field')]))
        add(step(mf.deleteProgramMembers,
                 lambda c: {'programId': c['program_id'], 'leadIds': [c['lead2']]}))

        # email program: approve/unapprove need an Email-type program
        add(step(mf.createProgram,
                 lambda c: {'name': name('EMAILPROG'), 'folderId': c['ma_folder'],
                            'programType': 'Email', 'channel': c['email_channel'],
                            'description': 'MCPTEST_LEG email program',
                            'tags': discover_required_tags(
                                SuiteRunner_token['token'],
                                c.get('email_channel_type', 'email')) or None},
                 name='createProgram(Email)', save=_save_first_id('email_program_id'),
                 skip_errors='email-program-create-unavailable'))
        add(step(mf.approveEmailProgram,
                 lambda c: {'programId': c['email_program_id']},
                 skip_errors='email-program-not-ready',
                 notes='empty email program; approval is expected to be rejected'))
        add(step(mf.unapproveEmailProgram,
                 lambda c: {'programId': c['email_program_id']},
                 skip_errors='email-program-not-approved'))

        # tokens (on the program so cleanup is self-contained)
        add(step(mf.createToken,
                 lambda c: {'folderId': c['program_id'], 'name': 'MCPTEST_LEG_token',
                            'tokenType': 'text', 'value': 'MCPTEST token value',
                            'folderType': 'Program'}))
        add(step(mf.getTokensByFolder,
                 lambda c: {'folderId': c['program_id'], 'folderType': 'Program'}))
        add(step(mf.updateToken,
                 lambda c: {'folderId': c['program_id'], 'name': 'MCPTEST_LEG_token',
                            'tokenType': 'text', 'value': 'MCPTEST updated value',
                            'folderType': 'Program'}))
        add(step(mf.deleteToken,
                 lambda c: {'folderId': c['program_id'], 'name': 'MCPTEST_LEG_token',
                            'tokenType': 'text', 'folderType': 'Program'}))

        # ============================================================ D. smart campaigns
        add(step(mf.createSmartCampaign,
                 lambda c: {'name': name('SC'), 'folderId': c['ma_folder'],
                            'description': 'MCPTEST_LEG suite campaign'},
                 save=_save_first_id('sc_id')))
        add(step(mf.getSmartCampaignById, lambda c: {'campaignId': c['sc_id']}))
        add(step(mf.getSmartCampaignByName, lambda c: {'name': name('SC')}))
        add(step(mf.browseSmartCampaigns, {'maxReturn': 5}))
        add(step(mf.updateSmartCampaign,
                 lambda c: {'campaignId': c['sc_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step(mf.cloneSmartCampaign,
                 lambda c: {'campaignId': c['sc_id'], 'name': name('SC_CLONE'),
                            'folderId': c['ma_folder']},
                 save=_save_first_id('sc_clone_id')))
        add(step(mf.activateSmartCampaign, lambda c: {'campaignId': c['sc_id']},
                 skip_errors='campaign-not-activatable',
                 notes='campaign has no triggers/flow; activation error is expected'))
        add(step(mf.deactivateSmartCampaign, lambda c: {'campaignId': c['sc_id']},
                 skip_errors='campaign-not-active'))
        add(step(mf.scheduleBatchCampaign, lambda c: {'campaignId': c['sc_id']},
                 skip_errors='campaign-not-schedulable'))
        add(step(mf.requestCampaign,
                 lambda c: {'campaignId': c['sc_id'], 'leadIds': [c['lead1']]},
                 skip_errors='campaign-not-requestable'))

        # ============================================================ E. static + smart lists
        add(step(lambda **kw: R.create_static_list(**kw),
                 lambda c: {'name': name('LIST'), 'program_id': c['program_id']},
                 infra=True, name='infra:create_static_list',
                 save=_save_first_id('list_id')))
        add(step(lambda **kw: R.add_leads_to_list(**kw),
                 lambda c: {'list_id': c['list_id'], 'lead_ids': [c['lead1'], c['lead2']]},
                 infra=True, name='infra:add_leads_to_list'))
        add(step(mf.isMemberOfList,
                 lambda c: {'listId': c['list_id'], 'leadIds': [c['lead1'], c['lead2']]}))
        add(step(mf.removeLeadsFromList,
                 lambda c: {'listId': c['list_id'], 'leadIds': [c['lead2']]}))
        add(step(lambda **kw: R.create_smart_list(**kw),
                 lambda c: {'name': name('SL'), 'program_id': c['program_id']},
                 infra=True, name='infra:create_smart_list',
                 save=_save_first_id('sl_id'), skip_errors='smart-list-create-unavailable'))

        # ============================================================ F. forms
        add(step(lambda **kw: R.create_form(**kw),
                 lambda c: {'name': name('FORM'), 'folder_id': c['ds_forms']},
                 infra=True, name='infra:create_form', save=_save_first_id('form_id')))
        for field in ('Email', 'FirstName'):
            add(step(lambda **kw: R.add_form_field(**kw),
                     (lambda fld: lambda c: {'form_id': c['form_id'], 'field_id': fld})(field),
                     infra=True, name=f'infra:add_form_field({field})',
                     skip_on=[('already exist', 'field-pre-existing')]))
        add(step(lambda **kw: R.approve_form(**kw),
                 lambda c: {'form_id': c['form_id']},
                 infra=True, name='infra:approve_form'))
        add(step(mf.submitForm,
                 lambda c: {'formId': c['form_id'],
                            'leadFormFields': {'Email': email(1), 'FirstName': 'MCP'},
                            'visitorData': {'pageURL': 'https://example.invalid/mcptest-leg'}}))
        add(step(mf.updateFormSubmitButton,
                 lambda c: {'formId': c['form_id'], 'label': 'MCPTEST Go',
                            'waitingLabel': 'Sending...'}))
        add(step(mf.updateFormThankYouPages,
                 lambda c: {'formId': c['form_id'],
                            'rules': [{'default': True, 'followupType': 'url',
                                       'followupValue': 'https://example.com/mcptest-thanks'}]},
                 notes='a url rule is the only round-trippable shape (611 otherwise)'))
        add(step(mf.deleteFormField,
                 lambda c: {'formId': c['form_id'], 'fieldId': 'FirstName'}))
        add(step(lambda **kw: R.add_form_fieldset(**kw),
                 lambda c: {'form_id': c['form_id'], 'label': 'MCPTEST FS'},
                 infra=True, name='infra:add_form_fieldset',
                 save=lambda c, d: c.__setitem__('fieldset_id',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step(mf.deleteFormFieldsetField,
                 lambda c: {'formId': c['form_id'], 'fieldSetId': str(c['fieldset_id']),
                            'fieldId': 'LastName'},
                 skip_if=lambda c: None if c.get('fieldset_id') else 'no fieldset created',
                 skip_errors='no-fieldset-field',
                 notes='API has no way to place a field inside a fieldset; expected skip'))
        add(step(mf.discardFormDraft, lambda c: {'formId': c['form_id']}))

        # ============================================================ G. email templates + emails
        add(step(mf.createEmailTemplate,
                 lambda c: {'name': name('TPL'), 'folderId': c['ds_etpl'],
                            'htmlContent': EMAIL_TEMPLATE_HTML,
                            'description': 'MCPTEST_LEG suite template'},
                 save=_save_first_id('tpl_id')))
        add(step(mf.browseEmailTemplates, {'maxReturn': 5}))
        add(step(mf.getEmailTemplateById, lambda c: {'templateId': c['tpl_id']}))
        add(step(mf.getEmailTemplateByName, lambda c: {'name': name('TPL')}))
        add(step(mf.getEmailTemplateContent, lambda c: {'templateId': c['tpl_id']}))
        add(step(mf.updateEmailTemplate,
                 lambda c: {'templateId': c['tpl_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step(mf.approveEmailTemplate, lambda c: {'templateId': c['tpl_id']}))
        add(step(mf.getEmailTemplateUsedBy, lambda c: {'templateId': c['tpl_id']}))
        add(step(mf.cloneEmailTemplate,
                 lambda c: {'templateId': c['tpl_id'], 'name': name('TPL_CLONE'),
                            'folderId': c['ds_etpl']},
                 save=_save_first_id('tpl_clone_id')))
        add(step(lambda **kw: R.create_email(**kw),
                 lambda c: {'name': name('EMAIL'), 'folder_id': c['ds_emails'],
                            'template_id': c['tpl_id'],
                            'subject': 'MCPTEST_LEG subject', 'from_email': SAMPLE_EMAIL_TO},
                 infra=True, name='infra:create_email', save=_save_first_id('email_id')))
        add(step(mf.getEmailById, lambda c: {'emailId': c['email_id']}))
        add(step(mf.getEmailByName, lambda c: {'name': name('EMAIL')}))
        add(step(mf.browseEmails, {'maxReturn': 5}))
        add(step(mf.updateEmail,
                 lambda c: {'emailId': c['email_id'], 'description': f'MCPTEST {sfx}'}))
        add(step(mf.updateEmailHeaders,
                 lambda c: {'emailId': c['email_id'], 'subject': f'MCPTEST subject {sfx}',
                            'replyTo': SAMPLE_EMAIL_TO}))
        add(step(mf.getEmailVariables, lambda c: {'emailId': c['email_id']},
                 save=lambda c, d: c.__setitem__('email_vars',
                                                 [v.get('name') or v.get('id')
                                                  for v in d.get('result') or []]),
                 skip_errors='no-email-variables'))
        add(step(mf.updateEmailVariable,
                 lambda c: {'emailId': c['email_id'], 'variableName': c['email_vars'][0],
                            'value': 'world'},
                 skip_if=lambda c: None if c.get('email_vars') else 'no variables on email'))

        def save_email_sections(ctx, data):
            sections = data.get('result') or []
            modules = [s for s in sections if str(s.get('contentType')) == 'Module']
            texts = [s for s in sections if str(s.get('contentType')) in ('Text', 'HTML')]
            ctx['email_modules'] = [m.get('htmlId') for m in modules]
            ctx['email_text_section'] = texts[0].get('htmlId') if texts else None

        add(step(mf.getEmailContent, lambda c: {'emailId': c['email_id']},
                 save=save_email_sections))
        add(step(mf.addEmailModule,
                 lambda c: {'emailId': c['email_id'], 'moduleId': c['email_modules'][0],
                            'name': 'MCPTEST Module Copy', 'index': 1},
                 skip_if=lambda c: None if c.get('email_modules') else 'email has no modules',
                 skip_on=[('611', 'no-modular-editor')],
                 save=lambda c, d: c.__setitem__('added_module',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step(mf.renameEmailModule,
                 lambda c: {'emailId': c['email_id'], 'moduleId': c['added_module'],
                            'name': 'MCPTEST Module Renamed'},
                 skip_if=lambda c: None if c.get('added_module') else 'no module was added'))
        add(step(mf.duplicateEmailModule,
                 lambda c: {'emailId': c['email_id'], 'moduleId': c['email_modules'][0],
                            'name': 'MCPTEST Module Dupe'},
                 skip_if=lambda c: None if c.get('email_modules') else 'email has no modules',
                 save=lambda c, d: c.__setitem__('dupe_module',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step(mf.rearrangeEmailModules,
                 lambda c: {'emailId': c['email_id'],
                            'positions': [{'index': i, 'moduleId': m} for i, m in enumerate(
                                reversed([m for m in [c['email_modules'][0],
                                                      c.get('added_module'),
                                                      c.get('dupe_module')]
                                          + c['email_modules'][1:] if m]))]},
                 skip_if=lambda c: None if c.get('email_modules') else 'email has no modules',
                 skip_errors='rearrange-rejected'))
        add(step(mf.deleteEmailModule,
                 lambda c: {'emailId': c['email_id'], 'moduleId': c['dupe_module']},
                 skip_if=lambda c: None if c.get('dupe_module') else 'no duplicated module'))

        def save_segmentation(ctx, data):
            for seg in data.get('result') or []:
                if seg.get('status') == 'approved':
                    ctx['seg_id'] = seg['id']
                    break

        add(step(mf.browseSegmentations, save=save_segmentation))
        add(step(mf.getSegments, lambda c: {'segmentationId': c['seg_id']},
                 skip_if=lambda c: None if c.get('seg_id') else 'no approved segmentation',
                 save=lambda c, d: c.__setitem__('segments',
                                                 [s['name'] for s in d.get('result') or []])))
        add(step(lambda **kw: R.email_section_to_dc(**kw),
                 lambda c: {'email_id': c['email_id'], 'html_id': c['email_text_section'],
                            'seg_id': c['seg_id']},
                 infra=True, name='infra:email_section_to_dc',
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

        add(step(mf.getEmailContent,
                 lambda c: {'emailId': c['email_id'], 'status': 'draft'},
                 name='getEmailContent(draft)', save=save_email_dc))
        add(step(mf.getEmailDynamicContent,
                 lambda c: {'emailId': c['email_id'],
                            'dynamicContentId': str(c['email_dc_id'])},
                 skip_if=lambda c: None if c.get('email_dc_id') else 'no dynamic content section'))
        add(step(mf.updateEmailDynamicContent,
                 lambda c: {'emailId': c['email_id'],
                            'dynamicContentId': str(c['email_dc_id']),
                            'segment': [s for s in c.get('segments', []) if s != 'Default'][0],
                            'contentType': 'HTML', 'value': '<p>MCPTEST segment content</p>'},
                 skip_if=lambda c: (None if (c.get('email_dc_id') and
                                             [s for s in c.get('segments', []) if s != 'Default'])
                                    else 'no dynamic content section / segments')))
        add(step(mf.updateEmailFullContent,
                 lambda c: {'emailId': c['email_id'],
                            'htmlContent': '<html><body><p>MCPTEST full content</p></body></html>'},
                 skip_errors='not-supported-for-modular-email',
                 notes='fullContent rejects module-based (editor 2.0) emails'))
        add(step(mf.sendSampleEmail,
                 lambda c: {'emailId': c['email_id'], 'emailAddress': SAMPLE_EMAIL_TO}))
        add(step(mf.previewEmail, lambda c: {'emailId': c['email_id']}))
        add(step(mf.getEmailCcFields))
        add(step(lambda **kw: R.approve_email(**kw),
                 lambda c: {'email_id': c['email_id']},
                 infra=True, name='infra:approve_email'))
        add(step(mf.updateEmailHeaders,
                 lambda c: {'emailId': c['email_id'],
                            'subject': f'MCPTEST draft subject {sfx}'},
                 name='updateEmailHeaders(draft)',
                 notes='creates a draft on the approved email'))
        add(step(mf.discardEmailDraft, lambda c: {'emailId': c['email_id']}))
        add(step(mf.cloneEmail,
                 lambda c: {'emailId': c['email_id'], 'name': name('EMAIL_CLONE'),
                            'folderId': c['ds_emails']},
                 save=_save_first_id('email_clone_id')))
        add(step(mf.unapproveEmail, lambda c: {'emailId': c['email_id']}))
        add(step(mf.updateEmailTemplateContent,
                 lambda c: {'templateId': c['tpl_id'],
                            'htmlContent': EMAIL_TEMPLATE_HTML.replace(
                                'Hello from text one.', 'Hello from text one (draft).')},
                 notes='creates a draft on the approved template'))
        add(step(mf.discardEmailTemplateDraft, lambda c: {'templateId': c['tpl_id']}))

        # ============================================================ H. files (no delete API)
        file_name = f"MCPTEST_LEG_file_{sfx}.txt"

        def save_file_folder(ctx, data):
            for file in data.get('result') or []:
                folder = file.get('folder') or {}
                if folder.get('id'):
                    ctx['file_folder'] = folder['id']
                    return

        add(step(mf.browseFiles, {'maxReturn': 10}, save=save_file_folder))
        add(step(mf.uploadFile,
                 lambda c: {'name': file_name, 'folderId': c['file_folder'],
                            'fileContent': f'MCPTEST_LEG suite run {sfx}\n',
                            'insertOnly': True,
                            'description': 'MCPTEST suite file (files cannot be deleted via API)'},
                 skip_if=lambda c: None if c.get('file_folder') else 'no existing files folder found',
                 save=_save_first_id('file_id'),
                 notes='unique per-run name: overwrites hit the multipart 709 bug below'))
        add(step(mf.getFileByName, lambda c: {'name': file_name}, skip_if=_need('file_id')))
        add(step(mf.getFileById, lambda c: {'fileId': c['file_id']}, skip_if=_need('file_id')))
        add(step(mf.replaceFileContent,
                 lambda c: {'fileId': c['file_id'], 'fileName': file_name,
                            'fileContent': f'MCPTEST_LEG suite run {sfx} (replaced)\n'},
                 skip_if=_need('file_id'),
                 skip_on=[('709', 'KNOWN-BUG-709-multipart-mime (uploadFile/replaceFileContent '
                                  'send no per-part Content-Type, so the stored mimeType is the '
                                  'request envelope type and replace can never match it)')]))

        # ============================================================ I. landing pages + redirects
        add(step(mf.createLandingPageTemplate,
                 lambda c: {'name': name('LPT'), 'folderId': c['ds_lpt'],
                            'description': 'MCPTEST_LEG LP template',
                            'templateType': 'freeForm'},
                 save=_save_first_id('lpt_id')))
        add(step(mf.browseLandingPageTemplates, {'maxReturn': 5}))
        add(step(mf.getLandingPageTemplateById, lambda c: {'templateId': c['lpt_id']}))
        add(step(mf.getLandingPageTemplateByName, lambda c: {'name': name('LPT')}))
        add(step(mf.updateLandingPageTemplate,
                 lambda c: {'templateId': c['lpt_id'],
                            'description': f'MCPTEST_LEG updated {sfx}'}))
        add(step(mf.updateLandingPageTemplateContent,
                 lambda c: {'templateId': c['lpt_id'], 'htmlContent': LP_TEMPLATE_HTML}))
        add(step(mf.getLandingPageTemplateContent, lambda c: {'templateId': c['lpt_id']}))
        add(step(mf.approveLandingPageTemplate, lambda c: {'templateId': c['lpt_id']}))
        add(step(mf.cloneLandingPageTemplate,
                 lambda c: {'templateId': c['lpt_id'], 'name': name('LPT_CLONE'),
                            'folderId': c['ds_lpt']},
                 save=_save_first_id('lpt_clone_id')))
        add(step(mf.updateLandingPageTemplateContent,
                 lambda c: {'templateId': c['lpt_id'],
                            'htmlContent': LP_TEMPLATE_HTML.replace(
                                'template body.', 'template body (draft).')},
                 name='updateLandingPageTemplateContent(draft)',
                 notes='creates a draft on the approved LP template'))
        add(step(mf.discardLandingPageTemplateDraft, lambda c: {'templateId': c['lpt_id']}))
        add(step(mf.createLandingPage,
                 lambda c: {'name': name('LP'), 'folderId': c['ds_lp'],
                            'templateId': c['lpt_id'],
                            'description': 'MCPTEST_LEG landing page'},
                 save=_save_first_id('lp_id'), skip_errors='lp-create-unavailable'))
        add(step(mf.browseLandingPages, {'maxReturn': 5}))
        add(step(mf.getLandingPageById, lambda c: {'landingPageId': c['lp_id']}))
        add(step(mf.getLandingPageByName, lambda c: {'name': name('LP')}))
        add(step(mf.updateLandingPage,
                 lambda c: {'landingPageId': c['lp_id'], 'title': f'MCPTEST title {sfx}'}))
        add(step(mf.addLandingPageContentSection,
                 lambda c: {'landingPageId': c['lp_id'], 'contentId': f'mcptest-sec-{sfx}',
                            'contentType': 'HTML', 'value': '<p>MCPTEST section</p>',
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

        add(step(mf.getLandingPageContent, lambda c: {'landingPageId': c['lp_id']},
                 save=save_lp_section))
        add(step(mf.updateLandingPageContentSection,
                 lambda c: {'landingPageId': c['lp_id'], 'contentId': str(c['lp_section_id']),
                            'contentType': 'HTML', 'value': '<p>MCPTEST updated section</p>'},
                 skip_if=lambda c: None if c.get('lp_section_id') else 'no LP content section'))
        add(step(mf.updateLandingPageContentSection,
                 lambda c: {'landingPageId': c['lp_id'], 'contentId': str(c['lp_section_id']),
                            'contentType': 'DynamicContent', 'value': str(c['seg_id'])},
                 name='updateLandingPageContentSection(DC)',
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

        add(step(mf.getLandingPageContent,
                 lambda c: {'landingPageId': c['lp_id'], 'status': 'draft'},
                 name='getLandingPageContent(draft)', save=save_lp_dc))
        add(step(mf.getLandingPageFullContent, lambda c: {'landingPageId': c['lp_id']},
                 skip_errors='lp-full-content-unavailable'))
        add(step(mf.getLandingPageVariables, lambda c: {'landingPageId': c['lp_id']},
                 skip_errors='freeform-lp-has-no-variables'))
        add(step(mf.updateLandingPageVariable,
                 lambda c: {'landingPageId': c['lp_id'], 'variableId': 'none', 'value': 'x'},
                 skip_if=lambda c: 'freeForm landing page has no variables (guided only)'))
        add(step(mf.updateLandingPageDynamicContent,
                 lambda c: {'landingPageId': c['lp_id'],
                            'dynamicContentId': str(c['lp_dc_id']),
                            'segment': [s for s in c.get('segments', []) if s != 'Default'][0],
                            'contentType': 'HTML', 'value': '<p>MCPTEST DC</p>'},
                 skip_if=lambda c: (None if c.get('lp_dc_id') else
                                    'no dynamic content section on landing page')))
        add(step(mf.getLandingPageDynamicContent,
                 lambda c: {'landingPageId': c['lp_id'],
                            'dynamicContentId': str(c['lp_dc_id'])},
                 skip_if=lambda c: (None if c.get('lp_dc_id') else
                                    'no dynamic content section on landing page')))
        add(step(mf.deleteLandingPageContentSection,
                 lambda c: {'landingPageId': c['lp_id'], 'contentId': str(c['lp_section_id'])},
                 skip_if=lambda c: None if c.get('lp_section_id') else 'no LP content section'))
        add(step(mf.approveLandingPage, lambda c: {'landingPageId': c['lp_id']},
                 skip_errors='lp-approve-unavailable',
                 after=lambda c, s, d: c.__setitem__('lp_approved', s == PASS),
                 notes='needs an LP domain (CNAME) on some instances'))
        add(step(mf.addLandingPageContentSection,
                 lambda c: {'landingPageId': c['lp_id'], 'contentId': f'mcptest-d2-{sfx}',
                            'contentType': 'HTML', 'value': '<p>MCPTEST draft2</p>',
                            'layout': {'left': 10, 'top': 120, 'width': 300, 'height': 80}},
                 name='addLandingPageContentSection(draft2)',
                 skip_if=lambda c: None if c.get('lp_approved') else 'landing page never approved',
                 skip_errors='lp-section-add-rejected',
                 notes='creates a draft on the approved LP for discardDraft'))
        add(step(mf.discardLandingPageDraft, lambda c: {'landingPageId': c['lp_id']},
                 skip_if=lambda c: None if c.get('lp_approved') else
                 'LP never approved (discarding a draft-only LP deletes it)',
                 skip_errors='no-lp-draft'))
        add(step(mf.cloneLandingPage,
                 lambda c: {'landingPageId': c['lp_id'], 'name': name('LP_CLONE'),
                            'folderId': c['ds_lp'], 'templateId': c['lpt_id']},
                 save=_save_first_id('lp_clone_id'),
                 notes='this instance requires the template param on LP clone'))
        add(step(mf.unapproveLandingPage, lambda c: {'landingPageId': c['lp_id']},
                 skip_if=lambda c: None if c.get('lp_approved') else 'landing page never approved',
                 retries=3,
                 notes='approval propagates asynchronously; retry a few times'))
        add(step(mf.getLandingPageDomains,
                 save=lambda c, d: c.__setitem__('lp_domains',
                                                 [r.get('domain') or r.get('name')
                                                  for r in d.get('result') or []])))
        add(step(mf.browseRedirectRules, {'maxReturn': 5}))
        add(step(mf.createRedirectRule,
                 lambda c: {'hostname': c['lp_domains'][0],
                            'fromType': 'path', 'fromValue': f'/mcptest-leg-from-{sfx}.html',
                            'toType': 'path', 'toValue': f'/mcptest-leg-to-{sfx}.html'},
                 skip_if=lambda c: None if c.get('lp_domains') else 'no LP domains configured',
                 save=_save_first_id('redirect_id'), skip_errors='redirect-create-rejected'))
        add(step(mf.getRedirectRuleById, lambda c: {'ruleId': c['redirect_id']},
                 skip_if=_need('redirect_id')))
        add(step(mf.updateRedirectRule,
                 lambda c: {'ruleId': c['redirect_id'],
                            'toType': 'path', 'toValue': f'/mcptest-leg-to2-{sfx}.html'},
                 skip_if=_need('redirect_id')))
        add(step(mf.deleteRedirectRule, lambda c: {'ruleId': c['redirect_id']},
                 skip_if=_need('redirect_id')))

        # ============================================================ J. snippets
        add(step(lambda **kw: R.create_snippet(**kw),
                 lambda c: {'name': name('SNIP'), 'folder_id': c['ds_snip']},
                 infra=True, name='infra:create_snippet', save=_save_first_id('snippet_id')))
        add(step(lambda **kw: R.update_snippet_content(**kw),
                 lambda c: {'snippet_id': c['snippet_id'], 'html': '<p>MCPTEST snippet</p>'},
                 infra=True, name='infra:update_snippet_content'))
        add(step(lambda **kw: R.approve_snippet(**kw),
                 lambda c: {'snippet_id': c['snippet_id']},
                 infra=True, name='infra:approve_snippet'))
        add(step(lambda **kw: R.update_snippet_content(**kw),
                 lambda c: {'snippet_id': c['snippet_id'],
                            'html': '<p>MCPTEST snippet draft</p>'},
                 infra=True, name='infra:update_snippet_content(draft)'))
        add(step(mf.discardSnippetDraft, lambda c: {'snippetId': c['snippet_id']}))
        add(step(mf.unapproveSnippet, lambda c: {'snippetId': c['snippet_id']}))

        # ============================================================ K. custom activity types (+ aliases)
        def save_act_types(ctx, data):
            ctx['act_type_pre_existing'] = any(
                t.get('apiName') == ACT_TYPE for t in data.get('result') or [])

        def act_create_after(ctx, status, data):
            ctx['act_ok'] = status == PASS or ctx.get('act_type_pre_existing')

        act_gate = lambda c: None if c.get('act_ok') else 'activity type unavailable (create failed)'

        add(step(mf.getCustomActivityTypes, save=save_act_types))
        add(step(mf.createCustomActivityType,
                 {'apiName': ACT_TYPE, 'name': 'MCPTEST Leg Activity',
                  'filterName': 'MCPTEST Leg Activity Filter',
                  'triggerName': 'MCPTEST Leg Activity Trigger',
                  'primaryAttribute': {'apiName': 'mcptestPrimary', 'name': 'MCPTEST Primary'},
                  'description': 'MCPTEST_LEG suite activity type'},
                 skip_on=[('already exist', 'pre-existing activity type')],
                 after=act_create_after))
        add(step(mf.describeCustomActivityType, {'apiName': ACT_TYPE, 'draft': True},
                 name='describeCustomActivityType(draft)',
                 skip_if=act_gate, skip_errors='no-activity-type-draft'))
        add(step(mf.updateCustomActivityType,
                 {'apiName': ACT_TYPE, 'description': f'MCPTEST_LEG updated {sfx}'},
                 skip_if=act_gate))
        add(step(mf.addCustomActivityTypeAttributes,
                 {'apiName': ACT_TYPE,
                  'attributes': [{'apiName': 'mcptestAttrA', 'name': 'MCPTEST Attr A',
                                  'dataType': 'string'},
                                 {'apiName': 'mcptestAttrB', 'name': 'MCPTEST Attr B',
                                  'dataType': 'string'}]},
                 skip_if=act_gate, skip_on=[('already exist', 'pre-existing attributes')]))
        add(step(mf.updateCustomActivityTypeAttributes,
                 {'apiName': ACT_TYPE,
                  'attributes': [{'apiName': 'mcptestAttrA', 'name': 'MCPTEST Attr A2',
                                  'dataType': 'string'}]},
                 skip_if=act_gate))
        add(step(mf.deleteCustomActivityTypeAttributes,
                 {'apiName': ACT_TYPE, 'attributes': [{'apiName': 'mcptestAttrB'}]},
                 skip_if=act_gate))
        add(step(mf.approveCustomActivityType, {'apiName': ACT_TYPE},
                 skip_if=act_gate, skip_on=[('no draft', 'act-type-already-approved')]))
        add(step(mf.describeCustomActivityType, {'apiName': ACT_TYPE},
                 skip_if=act_gate, save=_save_key('act_type_id', 'result', 0, 'id')))
        add(step(mf.addCustomActivities,
                 lambda c: {'activities': [{'leadId': c['lead1'],
                                            'activityTypeId': c['act_type_id'],
                                            'activityDate': _iso(now),
                                            'primaryAttributeValue': f'mcptest-{sfx}',
                                            'attributes': [{'name': 'mcptestAttrA',
                                                            'value': 'attr-value'}]}]},
                 skip_if=_need('act_type_id')))
        # alias chain (delegates to the Custom* functions; second draft cycle)
        add(step(mf.describeActivityType, {'apiName': ACT_TYPE}, skip_if=act_gate))
        add(step(mf.createActivityType,
                 {'apiName': ACT_TYPE, 'name': 'MCPTEST Leg Activity',
                  'filterName': 'MCPTEST Leg Activity Filter',
                  'triggerName': 'MCPTEST Leg Activity Trigger',
                  'primaryAttribute': {'apiName': 'mcptestPrimary', 'name': 'MCPTEST Primary'}},
                 skip_on=[('already exist', 'pre-existing activity type (alias create)')],
                 skip_if=act_gate))
        add(step(mf.updateActivityType,
                 {'apiName': ACT_TYPE, 'description': f'MCPTEST_LEG alias update {sfx}'},
                 skip_if=act_gate))
        add(step(mf.addActivityTypeAttributes,
                 {'apiName': ACT_TYPE,
                  'attributes': [{'apiName': 'mcptestAttrC', 'name': 'MCPTEST Attr C',
                                  'dataType': 'string'}]},
                 skip_if=act_gate, skip_on=[('already exist', 'pre-existing attributes')]))
        add(step(mf.updateActivityTypeAttributes,
                 {'apiName': ACT_TYPE,
                  'attributes': [{'apiName': 'mcptestAttrC', 'name': 'MCPTEST Attr C2',
                                  'dataType': 'string'}]},
                 skip_if=act_gate))
        add(step(mf.approveActivityType, {'apiName': ACT_TYPE},
                 skip_if=act_gate,
                 skip_on=[('no draft', 'act-type-already-approved'),
                          ('internal error', 'marketo-internal-error-on-reapprove')],
                 notes='approves the attrC draft (approving a draft whose attrs were '
                       'added and deleted in the same cycle 611s)'))
        add(step(mf.deleteActivityTypeAttributes,
                 {'apiName': ACT_TYPE, 'attributes': [{'apiName': 'mcptestAttrC'}]},
                 skip_if=act_gate))
        add(step(mf.approveCustomActivityType, {'apiName': ACT_TYPE},
                 name='approveCustomActivityType(attrC-delete)',
                 skip_if=act_gate,
                 skip_on=[('no draft', 'act-type-already-approved'),
                          ('internal error', 'marketo-internal-error-on-reapprove')],
                 notes='re-approve so attrC removal lands and reruns stay clean'))
        add(step(mf.addActivities,
                 lambda c: {'activities': [{'leadId': c['lead2'],
                                            'activityTypeId': c['act_type_id'],
                                            'activityDate': _iso(now),
                                            'primaryAttributeValue': f'mcptest-alias-{sfx}',
                                            'attributes': [{'name': 'mcptestAttrA',
                                                            'value': 'attr-value'}]}]},
                 skip_if=_need('act_type_id')))
        add(step(mf.updateCustomActivityType,
                 {'apiName': ACT_TYPE, 'description': f'MCPTEST draft {sfx}'},
                 name='updateCustomActivityType(draft)', skip_if=act_gate,
                 notes='creates a draft on the approved type'))
        add(step(mf.discardCustomActivityTypeDraft, {'apiName': ACT_TYPE}, skip_if=act_gate))
        add(step(mf.updateActivityType,
                 {'apiName': ACT_TYPE, 'description': f'MCPTEST draft2 {sfx}'},
                 name='updateActivityType(draft2)', skip_if=act_gate))
        add(step(mf.discardActivityTypeDraft, {'apiName': ACT_TYPE},
                 skip_if=act_gate, skip_errors='no-activity-type-draft'))

        # ============================================================ L. CRM objects
        add(step(mf.describeCompanies, skip_errors='crm-unavailable',
                 after=_flag_skip('no_crm')))
        crm_gate = _group_gate('no_crm', 'crm-synced instance (companies API unavailable)')
        add(step(mf.syncCompanies,
                 {'records': [{'externalCompanyId': f'mcptest-leg-co-{sfx}',
                               'company': 'MCPTEST Leg Co'}]}, skip_if=crm_gate))
        add(step(mf.queryCompanies,
                 {'filterType': 'externalCompanyId', 'filterValues': f'mcptest-leg-co-{sfx}'},
                 skip_if=crm_gate))
        add(step(mf.getCompanyFields, {'batchSize': 5}, skip_if=crm_gate))
        add(step(mf.getCompanyFieldByName, {'fieldApiName': 'externalCompanyId'},
                 skip_if=crm_gate))
        add(step(mf.deleteCompanies,
                 {'records': [{'externalCompanyId': f'mcptest-leg-co-{sfx}'}]},
                 skip_if=crm_gate))
        add(step(mf.describeOpportunities, skip_if=crm_gate))
        add(step(mf.syncOpportunities,
                 {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}',
                               'name': 'MCPTEST Leg Opp'}]}, skip_if=crm_gate))
        add(step(mf.queryOpportunities,
                 {'filterType': 'externalOpportunityId',
                  'filterValues': f'mcptest-leg-opp-{sfx}'}, skip_if=crm_gate))
        add(step(mf.getOpportunityFields, {'batchSize': 5}, skip_if=crm_gate))
        add(step(mf.getOpportunityFieldByName, {'fieldApiName': 'externalOpportunityId'},
                 skip_if=crm_gate))
        add(step(mf.describeOpportunityRoles, skip_if=crm_gate))
        add(step(mf.syncOpportunityRoles,
                 lambda c: {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}',
                                         'leadId': c['lead1'], 'role': 'MCPTEST'}]},
                 skip_if=crm_gate))
        add(step(mf.queryOpportunityRoles,
                 lambda c: {'filterType': 'leadId', 'filterValues': str(c['lead1'])},
                 skip_if=crm_gate))
        add(step(mf.deleteOpportunityRoles,
                 lambda c: {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}',
                                         'leadId': c['lead1'], 'role': 'MCPTEST'}]},
                 skip_if=crm_gate))
        add(step(mf.deleteOpportunities,
                 {'records': [{'externalOpportunityId': f'mcptest-leg-opp-{sfx}'}]},
                 skip_if=crm_gate))
        add(step(mf.describeSalesPersons, skip_if=crm_gate))
        add(step(mf.syncSalesPersons,
                 {'records': [{'externalSalesPersonId': f'mcptest-leg-sp-{sfx}',
                               'email': f'mcptest_leg_sp_{sfx}@example.invalid',
                               'firstName': 'MCP', 'lastName': 'SalesLeg'}]},
                 skip_if=crm_gate))
        add(step(mf.querySalesPersons,
                 {'filterType': 'externalSalesPersonId',
                  'filterValues': f'mcptest-leg-sp-{sfx}'}, skip_if=crm_gate))
        add(step(mf.deleteSalesPersons,
                 {'records': [{'externalSalesPersonId': f'mcptest-leg-sp-{sfx}'}]},
                 skip_if=crm_gate))

    # ================================================================ M. custom object type (needed by full + both groups)
    if full:
        add(step(mf.listCustomObjectTypes))
        add(step(mf.getCustomObjectFieldTypes))
        add(step(mf.getCustomObjectLinkableObjects))
    add(step(mf.syncCustomObjectType,
             {'apiName': CO_TYPE, 'displayName': 'MCPTEST Leg CO',
              'pluralName': 'MCPTEST Leg COs', 'action': 'createOrUpdate',
              'description': 'MCPTEST_LEG suite custom object'},
             skip_errors='co-schema-unavailable', after=_flag_skip('no_co_schema')))
    co_gate = _group_gate('no_co_schema', 'custom-object schema API unavailable')
    add(step(mf.addCustomObjectTypeFields,
             {'apiName': CO_TYPE,
              'fields': [{'name': 'mcptestKey', 'displayName': 'MCPTEST Key',
                          'dataType': 'string', 'isDedupeField': True},
                         {'name': 'mcptestVal', 'displayName': 'MCPTEST Val',
                          'dataType': 'string'}]},
             skip_if=co_gate,
             skip_on=[('already exist', 'pre-existing CO fields'),
                      ('dedupe fields cannot be added', 'pre-existing CO fields')]))
    add(step(mf.approveCustomObjectType, {'apiName': CO_TYPE}, skip_if=co_gate,
             skip_on=[('no draft', 'co-already-approved')]))
    add(step(mf.syncCustomObjects,
             {'objectApiName': CO_TYPE,
              'records': [{'mcptestKey': f'k1-{sfx}', 'mcptestVal': 'v1'}]},
             skip_if=co_gate, after=_flag_skip('no_co_records')))
    co_rec_gate = _group_gate('no_co_records', 'custom-object records unavailable')

    if full:
        add(step(mf.describeCustomObjectType, {'apiName': CO_TYPE, 'state': 'draft'},
                 name='describeCustomObjectType(draft)',
                 skip_if=co_gate, skip_errors='no-co-draft'))
        add(step(mf.updateCustomObjectTypeField,
                 {'apiName': CO_TYPE, 'fieldApiName': 'mcptestVal',
                  'updates': {'description': f'MCPTEST_LEG updated {sfx}'}},
                 skip_if=co_gate, skip_errors='co-field-update-rejected'))
        add(step(mf.listCustomObjects, {'names': CO_TYPE}, skip_if=co_gate))
        add(step(mf.describeCustomObject, {'objectApiName': CO_TYPE}, skip_if=co_gate))
        add(step(mf.getCustomObjectTypeDependents, {'apiName': CO_TYPE}, skip_if=co_gate))
        add(step(mf.queryCustomObjects,
                 {'objectApiName': CO_TYPE, 'filterType': 'mcptestKey',
                  'filterValues': f'k1-{sfx}'}, skip_if=co_rec_gate))
        # object aliases (read + a second record lifecycle + tmp fields)
        add(step(mf.listObjects, {'names': CO_TYPE}, skip_if=co_gate))
        add(step(mf.listObjectTypes, {'names': CO_TYPE}, skip_if=co_gate))
        add(step(mf.describeObject, {'objectApiName': CO_TYPE}, skip_if=co_gate))
        add(step(mf.describeObjectType, {'apiName': CO_TYPE}, skip_if=co_gate))
        add(step(mf.getObjectFieldTypes, skip_if=co_gate))
        add(step(mf.getObjectLinkableObjects, skip_if=co_gate))
        add(step(mf.getObjectTypeDependents, {'apiName': CO_TYPE}, skip_if=co_gate))
        add(step(mf.syncObjectType,
                 {'apiName': CO_TYPE, 'displayName': 'MCPTEST Leg CO',
                  'action': 'createOrUpdate',
                  'description': f'MCPTEST_LEG alias sync {sfx}'}, skip_if=co_gate))
        add(step(mf.syncObjects,
                 {'objectApiName': CO_TYPE,
                  'records': [{'mcptestKey': f'k3-{sfx}', 'mcptestVal': 'v3'}]},
                 skip_if=co_rec_gate))
        add(step(mf.queryObjects,
                 {'objectApiName': CO_TYPE, 'filterType': 'mcptestKey',
                  'filterValues': f'k3-{sfx}'}, skip_if=co_rec_gate))
        add(step(mf.deleteObjects,
                 {'objectApiName': CO_TYPE, 'records': [{'mcptestKey': f'k3-{sfx}'}]},
                 skip_if=co_rec_gate))
        add(step(mf.addObjectTypeFields,
                 {'apiName': CO_TYPE,
                  'fields': [{'name': 'mcptestTmp2', 'displayName': 'MCPTEST Tmp2',
                              'dataType': 'string'}]},
                 skip_if=co_gate, skip_on=[('already exist', 'pre-existing CO fields')]))
        add(step(mf.updateObjectTypeField,
                 {'apiName': CO_TYPE, 'fieldApiName': 'mcptestTmp2',
                  'updates': {'description': f'MCPTEST_LEG alias {sfx}'}},
                 skip_if=co_gate, skip_errors='co-field-update-rejected'))
        add(step(mf.deleteObjectTypeFields,
                 {'apiName': CO_TYPE, 'fieldNames': ['mcptestTmp2']},
                 skip_if=co_gate, skip_errors='co-delete-field-rejected'))
        add(step(mf.approveObjectType, {'apiName': CO_TYPE}, skip_if=co_gate,
                 skip_on=[('no draft', 'co-already-approved')]))
        add(step(mf.addCustomObjectTypeFields,
                 {'apiName': CO_TYPE,
                  'fields': [{'name': 'mcptestTmp', 'displayName': 'MCPTEST Tmp',
                              'dataType': 'string'}]},
                 name='addCustomObjectTypeFields(tmp)', skip_if=co_gate,
                 skip_on=[('already exist', 'pre-existing CO fields')],
                 notes='creates a draft so deleteFields/discardDraft have a target'))
        add(step(mf.deleteCustomObjectTypeFields,
                 {'apiName': CO_TYPE, 'fieldNames': ['mcptestTmp']},
                 skip_if=co_gate, skip_errors='co-delete-field-rejected'))
        add(step(mf.discardCustomObjectTypeDraft, {'apiName': CO_TYPE},
                 skip_if=co_gate, skip_errors='no-co-draft'))
        add(step(mf.discardObjectTypeDraft, {'apiName': CO_TYPE},
                 skip_if=co_gate, skip_errors='no-co-draft'))

        # ============================================================ N. named accounts / ABM
        add(step(mf.describeNamedAccounts,
                 skip_on=[('abm', 'abm-not-enabled')], skip_errors='abm-unavailable',
                 after=_flag_skip('no_abm')))
        abm_gate = _group_gate('no_abm', 'ABM not enabled on this subscription')
        add(step(mf.getNamedAccountFields, {'batchSize': 5}, skip_if=abm_gate))
        add(step(mf.getNamedAccountFieldByName, {'fieldApiName': 'name'}, skip_if=abm_gate))
        add(step(mf.syncNamedAccounts,
                 {'records': [{'name': name('NA'), 'domainName': 'mcptest.invalid'}]},
                 skip_if=abm_gate, save=_save_key('na_guid', 'result', 0, 'marketoGUID')))
        add(step(mf.queryNamedAccounts,
                 {'filterType': 'name', 'filterValues': name('NA'),
                  'fields': 'name,marketoGUID'}, skip_if=abm_gate))
        add(step(mf.syncNamedAccountLists,
                 {'records': [{'name': name('NAL')}], 'action': 'createOnly'},
                 skip_if=abm_gate, save=_save_key('nal_id', 'result', 0, 'marketoGUID')))
        add(step(mf.queryNamedAccountLists,
                 {'filterType': 'dedupeFields', 'filterValues': name('NAL')},
                 skip_if=abm_gate))
        add(step(mf.addNamedAccountListMembers,
                 lambda c: {'listId': str(c['nal_id']), 'accountIds': [c['na_guid']]},
                 skip_if=_need('nal_id', 'na_guid')))
        add(step(mf.getNamedAccountListMembers,
                 lambda c: {'listId': str(c['nal_id'])}, skip_if=_need('nal_id')))
        add(step(mf.removeNamedAccountListMembers,
                 lambda c: {'listId': str(c['nal_id']), 'accountIds': [c['na_guid']]},
                 skip_if=_need('nal_id', 'na_guid')))
        add(step(mf.deleteNamedAccountLists,
                 lambda c: {'records': [{'id': c['nal_id']}], 'deleteBy': 'idField'},
                 skip_if=_need('nal_id')))
        add(step(mf.deleteNamedAccounts,
                 lambda c: {'records': [{'id': c['na_guid']}], 'deleteBy': 'idField'},
                 skip_if=_need('na_guid')))

    # ================================================================ O. bulk import group
    if full or group == GROUP_IMPORT:
        add(step(mf.importLeadsCsv,
                 {'csvContent': f'email,firstName,lastName\n{email(5)},MCP,ImportFive\n'
                                f'{email(6)},MCP,ImportSix\n'},
                 save=_save_key('lead_batch', 'result', 0, 'batchId')))
        add(step(lambda **kw: R.lead_import_status(**kw),
                 lambda c: {'batch_id': c['lead_batch']},
                 infra=True, name='infra:lead_import_status', skip_if=_need('lead_batch'),
                 poll={'done': _job_done, 'flag': 'lead_import_done'}))
        add(step(mf.getLeadImportFailures, lambda c: {'batchId': c['lead_batch']},
                 skip_if=_need('lead_batch')))
        add(step(mf.getLeadImportWarnings, lambda c: {'batchId': c['lead_batch']},
                 skip_if=_need('lead_batch')))
        add(step(mf.importProgramMembersCsv,
                 lambda c: {'programId': c['program_id'],
                            'programMemberStatus': c['statuses'][0],
                            'csvContent': f'email\n{email(7)}\n'},
                 save=_save_key('pm_batch', 'result', 0, 'batchId')))
        add(step(mf.getProgramMemberImportStatus,
                 lambda c: {'batchId': c['pm_batch']}, skip_if=_need('pm_batch'),
                 poll={'done': _job_done, 'flag': 'pm_import_done'}))
        add(step(mf.getProgramMemberImportFailures,
                 lambda c: {'batchId': c['pm_batch']}, skip_if=_need('pm_batch')))
        add(step(mf.getProgramMemberImportWarnings,
                 lambda c: {'batchId': c['pm_batch']}, skip_if=_need('pm_batch')))
        add(step(mf.importCustomObjectsCsv,
                 {'objectApiName': CO_TYPE,
                  'csvContent': f'mcptestKey,mcptestVal\nk2-{sfx},v2\n'},
                 skip_if=co_rec_gate, save=_save_key('co_batch', 'result', 0, 'batchId')))
        add(step(mf.getCustomObjectImportStatus,
                 lambda c: {'objectApiName': CO_TYPE, 'batchId': c['co_batch']},
                 skip_if=_need('co_batch'),
                 poll={'done': _job_done, 'flag': 'co_import_done'}))
        add(step(mf.getCustomObjectImportFailures,
                 lambda c: {'objectApiName': CO_TYPE, 'batchId': c['co_batch']},
                 skip_if=_need('co_batch')))
        add(step(mf.getCustomObjectImportWarnings,
                 lambda c: {'objectApiName': CO_TYPE, 'batchId': c['co_batch']},
                 skip_if=_need('co_batch')))
        # alias import chain (second tiny batch)
        add(step(mf.importObjectsCsv,
                 {'objectApiName': CO_TYPE,
                  'csvContent': f'mcptestKey,mcptestVal\nk4-{sfx},v4\n'},
                 skip_if=co_rec_gate, save=_save_key('co_batch2', 'result', 0, 'batchId')))
        add(step(mf.getObjectImportStatus,
                 lambda c: {'objectApiName': CO_TYPE, 'batchId': c['co_batch2']},
                 skip_if=_need('co_batch2'),
                 poll={'done': _job_done, 'flag': 'co_import2_done'}))
        add(step(mf.getObjectImportFailures,
                 lambda c: {'objectApiName': CO_TYPE, 'batchId': c['co_batch2']},
                 skip_if=_need('co_batch2')))
        add(step(mf.getObjectImportWarnings,
                 lambda c: {'objectApiName': CO_TYPE, 'batchId': c['co_batch2']},
                 skip_if=_need('co_batch2')))
        add(step(mf.lookupLead,
                 {'filterType': 'email',
                  'filterValues': f'{email(5)},{email(6)},{email(7)}', 'fields': 'id,email'},
                 name='lookupLead(imported)',
                 save=lambda c, d: c.__setitem__('imported_lead_ids',
                                                 [r['id'] for r in d.get('result') or []]),
                 notes='resolve imported lead ids for cleanup'))

    # ================================================================ P. bulk export group
    if full or group == GROUP_EXPORT:
        add(step(mf.listLeadExportJobs, {'batchSize': 10}))
        add(step(lambda **kw: R.create_lead_export_job(**kw),
                 lambda c: {'fields': ['email', 'firstName'],
                            'start_at': _iso(run_start - timedelta(minutes=10)),
                            'end_at': _iso(datetime.now(timezone.utc))},
                 infra=True, name='infra:create_lead_export_job',
                 save=_save_key('lead_export', 'result', 0, 'exportId'),
                 notes='created (not enqueued) purely so cancelLeadExportJob has a target'))
        add(step(mf.cancelLeadExportJob, lambda c: {'exportId': c['lead_export']},
                 skip_if=_need('lead_export')))
        # activities: window covers only this run's own activities
        add(step(mf.createActivityExportJob,
                 lambda c: {'startAt': _iso(run_start - timedelta(minutes=5)),
                            'endAt': _iso(datetime.now(timezone.utc))},
                 save=_save_key('act_export', 'result', 0, 'exportId'),
                 notes='tiny window: a few minutes around this run'))
        add(step(mf.enqueueActivityExportJob, lambda c: {'exportId': c['act_export']},
                 skip_if=_need('act_export'),
                 skip_on=[('1029', 'export-queue-full')]))
        add(step(mf.getActivityExportJobStatus,
                 lambda c: {'exportId': c['act_export']}, skip_if=_need('act_export'),
                 poll={'done': _job_done, 'flag': 'act_export_done'}))
        add(step(mf.getActivityExportFile, lambda c: {'exportId': c['act_export']},
                 skip_if=lambda c: (None if (c.get('act_export') and c.get('act_export_done'))
                                    else 'export job still pending after poll window')))
        add(step(mf.createActivityExportJob,
                 lambda c: {'startAt': _iso(run_start - timedelta(minutes=5)),
                            'endAt': _iso(datetime.now(timezone.utc))},
                 name='createActivityExportJob(cancel-target)',
                 save=_save_key('act_export2', 'result', 0, 'exportId')))
        add(step(mf.cancelActivityExportJob, lambda c: {'exportId': c['act_export2']},
                 skip_if=_need('act_export2')))
        add(step(mf.listActivityExportJobs, {'batchSize': 10}))
        # program members: scoped to this run's program
        if not full:
            add(step(mf.describeProgramMembers,
                     save=lambda c, d: c.__setitem__(
                         'pm_export_fields',
                         [n for n in ('leadId', 'program', 'programId', 'statusName',
                                      'reachedSuccess')
                          if n in {f.get('name') for f in
                                   ((d.get('result') or [{}])[0].get('fields') or [])}][:2]
                         or ['leadId', 'program'])))
        add(step(mf.createProgramMemberExportJob,
                 lambda c: {'fields': c.get('pm_export_fields', ['leadId', 'program']),
                            'programId': c['program_id']},
                 save=_save_key('pm_export', 'result', 0, 'exportId'),
                 notes='scoped to this run\'s program'))
        add(step(mf.enqueueProgramMemberExportJob,
                 lambda c: {'exportId': c['pm_export']}, skip_if=_need('pm_export'),
                 skip_on=[('1029', 'export-queue-full')]))
        add(step(mf.getProgramMemberExportJobStatus,
                 lambda c: {'exportId': c['pm_export']}, skip_if=_need('pm_export'),
                 poll={'done': _job_done, 'flag': 'pm_export_done'}))
        add(step(mf.getProgramMemberExportFile,
                 lambda c: {'exportId': c['pm_export']},
                 skip_if=lambda c: (None if (c.get('pm_export') and c.get('pm_export_done'))
                                    else 'export job still pending after poll window')))
        add(step(mf.createProgramMemberExportJob,
                 lambda c: {'fields': c.get('pm_export_fields', ['leadId', 'program']),
                            'programId': c['program_id']},
                 name='createProgramMemberExportJob(cancel-target)',
                 save=_save_key('pm_export2', 'result', 0, 'exportId')))
        add(step(mf.cancelProgramMemberExportJob,
                 lambda c: {'exportId': c['pm_export2']}, skip_if=_need('pm_export2')))
        add(step(mf.listProgramMemberExportJobs, {'batchSize': 10}))
        # custom objects: filter scoped to the last hour (this run's records)
        co_filter = lambda: {'updatedAt': {'startAt': _iso(run_start - timedelta(hours=1)),
                                           'endAt': _iso(datetime.now(timezone.utc)
                                                         + timedelta(minutes=5))}}
        add(step(mf.createCustomObjectExportJob,
                 lambda c: {'objectApiName': CO_TYPE,
                            'fields': ['mcptestKey', 'mcptestVal'],
                            'exportFilter': co_filter()},
                 skip_if=co_rec_gate,
                 save=_save_key('co_export', 'result', 0, 'exportId')))
        add(step(mf.enqueueCustomObjectExportJob,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export']},
                 skip_if=_need('co_export'), skip_on=[('1029', 'export-queue-full')]))
        add(step(mf.getCustomObjectExportJobStatus,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export']},
                 skip_if=_need('co_export'),
                 poll={'done': _job_done, 'flag': 'co_export_done'}))
        add(step(mf.getCustomObjectExportFile,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export']},
                 skip_if=lambda c: (None if (c.get('co_export') and c.get('co_export_done'))
                                    else 'export job still pending after poll window')))
        add(step(mf.createCustomObjectExportJob,
                 lambda c: {'objectApiName': CO_TYPE, 'fields': ['mcptestKey'],
                            'exportFilter': co_filter()},
                 name='createCustomObjectExportJob(cancel-target)', skip_if=co_rec_gate,
                 save=_save_key('co_export2', 'result', 0, 'exportId')))
        add(step(mf.cancelCustomObjectExportJob,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export2']},
                 skip_if=_need('co_export2')))
        add(step(mf.listCustomObjectExportJobs, {'objectApiName': CO_TYPE},
                 skip_if=co_gate))
        # alias export chain: create -> enqueue -> status -> cancel; file via primary
        add(step(mf.createObjectExportJob,
                 lambda c: {'objectApiName': CO_TYPE, 'fields': ['mcptestKey'],
                            'exportFilter': co_filter()},
                 skip_if=co_rec_gate,
                 save=_save_key('co_export3', 'result', 0, 'exportId')))
        add(step(mf.enqueueObjectExportJob,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export3']},
                 skip_if=_need('co_export3'), skip_on=[('1029', 'export-queue-full')]))
        add(step(mf.getObjectExportJobStatus,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export3']},
                 skip_if=_need('co_export3')))
        add(step(mf.cancelObjectExportJob,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export3']},
                 skip_if=_need('co_export3'), skip_errors='job-not-cancellable'))
        add(step(mf.getObjectExportFile,
                 lambda c: {'objectApiName': CO_TYPE, 'exportId': c['co_export']},
                 skip_if=lambda c: (None if (c.get('co_export') and c.get('co_export_done'))
                                    else 'export job still pending after poll window'),
                 notes='alias file fetch reuses the completed primary job'))
        add(step(mf.listObjectExportJobs, {'objectApiName': CO_TYPE}, skip_if=co_gate))

    # ================================================================ Q. users + Asset v2 (full only)
    if full:
        add(step(mf.listWorkspaces, skip_errors='user-mgmt-permission-missing',
                 after=_flag_skip('no_user_mgmt'),
                 save=lambda c, d: c.__setitem__('workspace_id',
                                                 (d.get('result') or [{}])[0].get('id', 1))))
        um_gate = _group_gate('no_user_mgmt',
                              'user-management permission missing (603) on API role')
        add(step(mf.listUsers, {'pageSize': 5}, skip_if=um_gate,
                 save=lambda c, d: c.__setitem__('first_user_id',
                                                 (d.get('result') or [{}])[0].get('userid'))))
        add(step(mf.getUserById, lambda c: {'userId': c['first_user_id']}, skip_if=um_gate))
        add(step(mf.listUserRoles, skip_if=um_gate,
                 save=lambda c, d: c.__setitem__('role_id',
                                                 (d.get('result') or [{}])[0].get('id'))))
        add(step(mf.getUserRoles, lambda c: {'userId': c['first_user_id']}, skip_if=um_gate))
        add(step(mf.inviteUser,
                 lambda c: {'emailAddress': INVITE_EMAIL, 'firstName': 'MCP',
                            'lastName': 'LegInvite', 'apiOnly': True,
                            'expiresAt': _iso(now + timedelta(days=1)),
                            'reason': 'MCPTEST_LEG suite',
                            'userRoleWorkspaces': [{'accessRoleId': c['role_id'],
                                                    'workspaceId': c['workspace_id']}]},
                 skip_if=um_gate,
                 after=lambda c, s, d: c.__setitem__('invited', s == PASS)))
        invited_gate = lambda c: (None if c.get('invited')
                                  else 'safety: only the suite-invited user may be touched')
        add(step(mf.getUserInvite, {'userId': INVITE_EMAIL}, skip_if=invited_gate))
        add(step(mf.updateUser, {'userId': INVITE_EMAIL, 'lastName': 'LegInviteUpdated'},
                 skip_if=invited_gate, skip_errors='pending-user-not-updatable'))
        add(step(mf.addUserRoles,
                 lambda c: {'userId': INVITE_EMAIL,
                            'roleWorkspaces': [{'accessRoleId': c['role_id'],
                                                'workspaceId': c['workspace_id']}]},
                 skip_if=invited_gate, skip_errors='pending-user-roles-unmodifiable'))
        add(step(mf.removeUserRoles,
                 lambda c: {'userId': INVITE_EMAIL,
                            'roleWorkspaces': [{'accessRoleId': c['role_id'],
                                                'workspaceId': c['workspace_id']}]},
                 skip_if=invited_gate, skip_errors='pending-user-roles-unmodifiable'))
        add(step(mf.deleteUserInvite, {'userId': INVITE_EMAIL}, skip_if=invited_gate))
        add(step(mf.deleteUser, {'userId': INVITE_EMAIL}, skip_if=invited_gate,
                 skip_errors='invited-user-not-deletable'))

        add(step(mf.browseEmailTemplates2,
                 lambda c: {'workspaceId': c.get('workspace_id', 1)},
                 skip_on=[('704', 'v2-unavailable: x-app-type header required'),
                          ('expecting value', 'v2-unavailable (non-JSON response)')],
                 skip_errors='v2-unavailable', after=_flag_skip('no_v2')))
        v2_gate = _group_gate(
            'no_v2', 'Asset v2 unavailable (704 x-app-type header / Emails 2.0 not enabled)')
        for fn, args, save in [
            (mf.getEmail2ById, lambda c: {'emailId': c['email_id']}, None),
            (mf.createEmail2,
             lambda c: {'name': name('EMAIL2'), 'appData': {'folderId': c['ds_emails']},
                        'emailHeaders': {'subject': 'MCPTEST', 'fromName': 'MCPTEST',
                                         'fromEmail': SAMPLE_EMAIL_TO,
                                         'replyTo': SAMPLE_EMAIL_TO}},
             _save_key('email2_id', 'result', 0, 'id')),
            (mf.updateEmail2,
             lambda c: {'emailId': c['email2_id'], 'description': 'MCPTEST'}, None),
            (mf.cloneEmail2,
             lambda c: {'emailId': c['email2_id'], 'name': name('EMAIL2_CLONE'),
                        'folderId': c['ds_emails']}, None),
            (mf.transitionEmail2State,
             lambda c: {'emailId': c['email2_id'], 'action': 'approve'}, None),
            (mf.getEmail2UsedBy, lambda c: {'emailId': c['email2_id']}, None),
            (mf.deleteEmail2, lambda c: {'emailId': c['email2_id']}, None),
            (mf.getEmailTemplate2ById, lambda c: {'templateId': c['tpl_id']}, None),
            (mf.createEmailTemplate2,
             lambda c: {'name': name('TPL2'), 'appData': {'folderId': c['ds_etpl']}},
             _save_key('tpl2_id', 'result', 0, 'id')),
            (mf.updateEmailTemplate2,
             lambda c: {'templateId': c['tpl2_id'], 'description': 'MCPTEST'}, None),
            (mf.cloneEmailTemplate2,
             lambda c: {'templateId': c['tpl2_id'], 'name': name('TPL2_CLONE'),
                        'folderId': c['ds_etpl']}, None),
            (mf.transitionEmailTemplate2State,
             lambda c: {'templateId': c['tpl2_id'], 'action': 'approve'}, None),
            (mf.getEmailTemplate2UsedBy, lambda c: {'templateId': c['tpl2_id']}, None),
            (mf.deleteEmailTemplate2, lambda c: {'templateId': c['tpl2_id']}, None),
            (mf.browseFragments, lambda c: {'workspaceId': c.get('workspace_id', 1)}, None),
            (mf.getFragmentById, lambda c: {'fragmentId': c['fragment_id']}, None),
            (mf.createFragment,
             lambda c: {'name': name('FRAG'), 'appData': {'folderId': c['ds_emails']},
                        'settings': {}},
             _save_key('fragment_id', 'result', 0, 'id')),
            (mf.updateFragment,
             lambda c: {'fragmentId': c['fragment_id'], 'description': 'MCPTEST'}, None),
            (mf.cloneFragment,
             lambda c: {'fragmentId': c['fragment_id'], 'name': name('FRAG_CLONE'),
                        'folderId': c['ds_emails']}, None),
            (mf.transitionFragmentState,
             lambda c: {'fragmentId': c['fragment_id'], 'action': 'approve'}, None),
            (mf.getFragmentUsedBy, lambda c: {'fragmentId': c['fragment_id']}, None),
            (mf.deleteFragment, lambda c: {'fragmentId': c['fragment_id']}, None),
        ]:
            add(step(fn, args, skip_if=v2_gate, skip_errors='v2-schema', save=save,
                     notes='pragmatic minimal-body attempt; validation errors -> SKIP'))

        # second merge path already covered; legacy merge covered by chain above

    # ================================================================ R. cleanup
    def delete_leads_args(ctx):
        ids = [ctx.get(k) for k in ('lead1', 'lead2', 'lead3', 'lead4')]
        if not ctx.get('dup1_merged'):
            ids.append(ctx.get('dup1'))
        ids += ctx.get('imported_lead_ids', [])
        ids = [i for i in ids if i]
        if not ids:
            raise KeyError('lead ids')
        return {'leadIds': ids}

    add(step(mf.deleteLeads, delete_leads_args))
    if full:
        add(step(mf.getDeletedLeads, {'sinceDatetime': _iso(now - timedelta(hours=1))}))
        add(step(mf.deleteStaticList, lambda c: {'listId': c['list_id']}))
        add(step(mf.deleteSmartList, lambda c: {'smartListId': c['sl_id']}))
        add(step(mf.deleteSmartCampaign, lambda c: {'campaignId': c['sc_clone_id']},
                 name='deleteSmartCampaign(clone)'))
        add(step(mf.deleteSmartCampaign, lambda c: {'campaignId': c['sc_id']}))
        add(step(mf.deleteProgram, lambda c: {'programId': c['program_clone_id']},
                 name='deleteProgram(clone)'))
        add(step(mf.deleteProgram, lambda c: {'programId': c['email_program_id']},
                 name='deleteProgram(email)'))
    add(step(mf.deleteProgram, lambda c: {'programId': c['program_id']}))
    if full:
        add(step(mf.deleteSnippet, lambda c: {'snippetId': c['snippet_id']}))
        add(step(mf.deleteForm, lambda c: {'formId': c['form_id']}))
        add(step(mf.unapproveEmail, lambda c: {'emailId': c['email_clone_id']},
                 name='unapproveEmail(clone)', skip_errors='clone-not-approved'))
        add(step(mf.deleteEmail, lambda c: {'emailId': c['email_clone_id']},
                 name='deleteEmail(clone)'))
        add(step(mf.deleteEmail, lambda c: {'emailId': c['email_id']}))
        add(step(mf.unapproveEmailTemplate, lambda c: {'templateId': c['tpl_id']}))
        add(step(mf.deleteEmailTemplate, lambda c: {'templateId': c['tpl_clone_id']},
                 name='deleteEmailTemplate(clone)'))
        add(step(mf.deleteEmailTemplate, lambda c: {'templateId': c['tpl_id']}))
        add(step(mf.unapproveLandingPage, lambda c: {'landingPageId': c['lp_id']},
                 name='unapproveLandingPage(cleanup)', skip_errors='lp-not-approved',
                 notes='defensive: LP must be unapproved before deletion'))
        add(step(mf.deleteLandingPage, lambda c: {'landingPageId': c['lp_clone_id']},
                 name='deleteLandingPage(clone)'))
        add(step(mf.deleteLandingPage, lambda c: {'landingPageId': c['lp_id']},
                 retries=2))
        add(step(mf.unapproveLandingPageTemplate, lambda c: {'templateId': c['lpt_id']},
                 skip_errors='lpt-not-approved'))
        add(step(mf.deleteLandingPageTemplate, lambda c: {'templateId': c['lpt_clone_id']},
                 name='deleteLandingPageTemplate(clone)'))
        add(step(mf.deleteLandingPageTemplate, lambda c: {'templateId': c['lpt_id']}))
        add(step(mf.deleteActivityType, {'apiName': ACT_TYPE},
                 skip_errors='activity-type-in-use',
                 notes='types with recent activity records cannot be deleted; reused next run'))
        add(step(mf.deleteCustomActivityType, {'apiName': ACT_TYPE},
                 skip_errors='activity-type-in-use-or-gone'))
    # CO records + type
    add(step(mf.deleteCustomObjects,
             lambda c: {'objectApiName': CO_TYPE,
                        'records': [{'mcptestKey': f'k1-{sfx}'}, {'mcptestKey': f'k2-{sfx}'},
                                    {'mcptestKey': f'k4-{sfx}'}]},
             skip_if=co_rec_gate))
    if full:
        add(step(mf.deleteObjectType, {'apiName': CO_TYPE},
                 skip_if=co_gate, skip_errors='co-type-has-records'))
        add(step(mf.deleteCustomObjectType, {'apiName': CO_TYPE},
                 skip_if=co_gate, skip_errors='co-type-has-records-or-gone',
                 notes='record deletion is async; type delete may need a later run'))
        for key in ('ds_forms', 'ds_emails', 'ds_etpl', 'ds_lp', 'ds_lpt', 'ds_snip'):
            add(step(mf.deleteFolder, (lambda k: lambda c: {'folderId': c[k]})(key),
                     name=f'deleteFolder({key})'))
    add(step(mf.deleteFolder, lambda c: {'folderId': c['ma_folder']},
             name='deleteFolder(ma)'))

    return steps


# Shared token holder so closures inside build_full_steps (tag discovery,
# base_url_override demo) always see the current token.
SuiteRunner_token = {'token': None}


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


def run_auto_suite(group=None):
    """The non-interactive full-coverage suite (or one bulk group)."""
    sfx = datetime.now().strftime("%m%d%H%M%S")
    try:
        token = marketo_functions.getToken()
    except Exception as exc:
        print(f"FATAL: getToken() failed: {exc}")
        sys.exit(2)
    executed_functions.add('getToken')
    SuiteRunner_token['token'] = token
    holder = SuiteRunner_token
    R = RestInfra(holder)

    label = group or 'full'
    print(f"Run suffix: {sfx}  |  mode: {label}")
    print("\n--- Sweep: clearing MCPTEST_LEG_* leftovers (start) ---")
    sweep_mcptest_leg(holder, R)

    steps = build_full_steps(sfx, R, group)
    print(f"\n--- Running {len(steps)} steps ---")
    started = time.time()
    runner = SuiteRunner(holder)
    ctx = {}
    for st in steps:
        try:
            runner.run_step(st, ctx)
        except Exception as exc:  # never let one step abort the suite
            runner.records.append((st['name'], 'ENGINE', FAIL,
                                   f"engine error: {type(exc).__name__}: {exc}", 0.0))
            print(f"F [{len(runner.records):3d}] ENGINE {st['name']} FAIL ({exc})", flush=True)

    print("\n--- Sweep: clearing MCPTEST_LEG_* leftovers (end) ---")
    holder['token'] = marketo_functions.getToken()
    sweep_mcptest_leg(holder, R)

    enforce = group is None
    uncovered = print_coverage(enforce=enforce)
    counts = print_engine_summary(runner.records, uncovered, time.time() - started, enforce)
    if skip_reasons:
        print("\nSkipped tests (interactive-helper skips):")
        for nm, reason in skip_reasons:
            print(f"  - {nm}: {reason}")
    sys.exit(1 if (counts[FAIL] or (enforce and uncovered)) else 0)


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Test suite for marketo_functions.py")
    parser.add_argument('--auto', action='store_true',
                        help="Run the FULL-COVERAGE suite non-interactively "
                             "(creates MCPTEST_LEG_* assets, always cleans up, "
                             "exits non-zero on FAIL or uncovered functions)")
    parser.add_argument('--group', choices=[GROUP_EXPORT, GROUP_IMPORT],
                        help="Run only the bulk-export or bulk-import steps "
                             "plus minimal prerequisites (implies --auto)")
    args = parser.parse_args()
    AUTO_MODE = args.auto or bool(args.group)

    if not ensure_credentials():
        print("ERROR: Marketo credentials not found in environment, .env, or .env.sandbox")
        sys.exit(1)

    load_test_config()

    print("=" * 60)
    print("Marketo Functions - Direct Test Suite")
    print("=" * 60)

    if AUTO_MODE:
        mode = args.group or 'full coverage'
        print(f"\nMode: AUTO ({mode}, non-interactive)")
        run_auto_suite(args.group)
    else:
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

        print_coverage(enforce=False)

        if skip_reasons:
            print("\nSkipped tests:")
            for name, reason in skip_reasons:
                print(f"  - {name}: {reason}")
