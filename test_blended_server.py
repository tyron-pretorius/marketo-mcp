"""
Smoke tests for the blended Marketo MCP server (mcp_server_blended.py).

Run it with no arguments and choose a mode at the menu:

    python3 test_blended_server.py

  Live mode
      Requires real Marketo credentials (read from .env, falling back to
      .env.sandbox, or set MARKETO_CLIENT_ID / MARKETO_CLIENT_SECRET /
      MARKETO_MUNCHKIN_ID env vars, else prompted) and the blended
      server already running on http://localhost:8000/mcp. Lists tools and
      calls one custom tool (custom_browse_landing_pages). Calling proxied
      native tools end-to-end additionally requires your Munchkin ID to be
      allowlisted in Adobe's beta.

  Full suite
      Comprehensive end-to-end suite against a REAL Marketo sandbox. Starts
      the blended server itself (subprocess, PORT=8000), connects with the
      X-Marketo-* headers (read from the environment, .env, or .env.sandbox), and
      exercises EVERY custom_* tool plus a native-tool smoke set
      (browse_folders, browse_channels, describe_lead, get_leads_by_filter,
      browse_programs, browse_forms, browse_smart_campaigns, browse_lists,
      browse_emails2, get_activity_types, browse_smart_lists,
      browse_snippets). A handful of further native tools are used only as
      infrastructure (create_folder, create_program, create_form, ...);
      any native tools beyond those are out of scope for this suite.

      All assets it creates are named MCPTEST_FULL_* and are deleted at the
      end (except Marketo objects the API cannot delete: lead fields and
      program-member fields use fixed names with reuse-if-exists semantics;
      Design Studio files get one tiny per-run file that cannot be removed).

      After picking this mode you are prompted for three optional settings
      (press Enter to accept the default):
        - Dry run: print the planned steps and the coverage check without
          making any API call.
        - Run suffix: embedded in asset names so reruns never collide
          (defaults to a timestamp).
        - Group: run only the steps tagged with that group plus their
          minimal prerequisites (asset setup + cleanup). Available groups:
          bulk-export, bulk-import. Leave blank to run everything and assert
          full custom-tool coverage.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import dotenv
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

BLENDED_URL = "http://localhost:8000/mcp"


# ============================================================================
# Live mode
# ============================================================================

def _get_live_headers() -> dict:
    _load_env_files()
    client_id = os.environ.get("MARKETO_CLIENT_ID") or input("Marketo Client ID: ").strip()
    client_secret = os.environ.get("MARKETO_CLIENT_SECRET") or input("Marketo Client Secret: ").strip()
    munchkin_id = os.environ.get("MARKETO_MUNCHKIN_ID") or input("Marketo Munchkin ID (e.g. 123-ABC-456): ").strip()
    return {
        "X-Marketo-Client-Id": client_id,
        "X-Marketo-Client-Secret": client_secret,
        "X-Marketo-Munchkin-Id": munchkin_id,
    }


async def _live_checks(headers: dict):
    async with Client(StreamableHttpTransport(BLENDED_URL, headers=headers)) as client:
        tools = sorted(t.name for t in await client.list_tools())
        custom = [t for t in tools if t.startswith("custom_")]
        native = [t for t in tools if not t.startswith("custom_")]
        print(f"Tools listed: {len(native)} native, {len(custom)} custom")
        print("Custom tools:", ", ".join(custom))
        if not native:
            print("NOTE: no native tools listed — is your Munchkin ID allowlisted for Adobe's beta?")

        print("\nCalling custom_browse_landing_pages (direct REST path)...")
        result = await client.call_tool("custom_browse_landing_pages", {"max_return": 3})
        print(result.data if hasattr(result, "data") else result)

        if "browse_programs" in native:
            print("\nCalling browse_programs (proxied native path)...")
            result = await client.call_tool("browse_programs", {})
            print(result.data if hasattr(result, "data") else result)


def run_live_mode():
    headers = _get_live_headers()
    asyncio.run(_live_checks(headers))


# ============================================================================
# Full mode — exhaustive custom-tool suite against a real Marketo sandbox
# ============================================================================

FULL_PORT = 8000
FULL_URL = f"http://localhost:{FULL_PORT}/mcp"
CALL_TIMEOUT = 120          # seconds per tool call
POLL_INTERVAL = 5           # seconds between export/import job polls
POLL_TIMEOUT = 90           # max seconds to wait on a single job
SAMPLE_EMAIL_TO = "tyron.pretorius+mcptest@knak.com"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

# Fixed-name objects that Marketo cannot delete via API: reuse across runs.
LEAD_FIELD = "mcptestFullField1"
PM_FIELD = "mcptestFullPmField1"
ACT_TYPE = "mcptestfullact1"
CO_TYPE = "mcptest_full_co"


def _load_env_files():
    """Populate MARKETO_* env vars from .env (preferred), then .env.sandbox.

    load_dotenv never overrides a variable already present in the real
    environment, and the first file loaded wins over later ones, so the
    precedence is: real env vars > .env > .env.sandbox.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    dotenv.load_dotenv(os.path.join(here, ".env"))
    dotenv.load_dotenv(os.path.join(here, ".env.sandbox"))


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_result(result):
    """Normalize a fastmcp CallToolResult.

    Custom tools return structured dicts via .data. Native (proxied) tools
    return markdown text with an embedded ```json block — extract and parse
    it. Raw-text tools (CSV downloads) come back as plain strings.
    """
    data = getattr(result, "data", None)
    if data is not None:
        return data
    text = "".join(getattr(block, "text", "") for block in (result.content or []))
    match = re.search(r"```json\s*(.*?)\s*```", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except ValueError:
            pass
    return text


def _marketo_errors(data):
    """Return (codes, message_text) for a structured Marketo error payload."""
    if not isinstance(data, dict):
        return [], ""
    errs = data.get("errors") or []
    codes = [str(e.get("code")) for e in errs if isinstance(e, dict)]
    msgs = " | ".join(str(e.get("message", "")) for e in errs if isinstance(e, dict))
    if data.get("error"):
        msgs = (msgs + " | " + str(data["error"])).strip(" |")
    return codes, msgs


def _job_status(data):
    """Best-effort status string from a bulk job status/import response.

    Handles both dict envelopes ({'result': [{'status': ...}]}) and the bare
    lists some native tools return as structured content."""
    if isinstance(data, dict):
        data = data.get("result") or []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get("status", "")).lower()
    return ""


def _job_done(data):
    return _job_status(data) in ("complete", "completed", "failed")


def _is_error_payload(data):
    if not isinstance(data, dict):
        return False
    if data.get("success") is False:
        return True
    if data.get("errors"):
        return True
    if "error" in data and data.get("error"):
        return True
    return False


# Step groups selectable with `full --group NAME`. A step tagged with one or
# more groups runs when that group is selected; untagged steps only run in the
# default (run-everything) mode. Prerequisite/cleanup steps shared by both
# bulk groups are tagged with BULK_BOTH.
BULK_EXPORT = "bulk-export"
BULK_IMPORT = "bulk-import"
BULK_BOTH = (BULK_EXPORT, BULK_IMPORT)
AVAILABLE_GROUPS = (BULK_EXPORT, BULK_IMPORT)


# Tool-name verb prefixes that mutate Marketo state. Used to infer whether a
# step is a write when its builder does not pass write= explicitly.
_WRITE_VERBS = (
    "create", "update", "delete", "clone", "approve", "unapprove", "add",
    "remove", "sync", "push", "merge", "submit", "import", "upload", "replace",
    "discard", "activate", "deactivate", "associate", "change", "invite",
    "rename", "duplicate", "rearrange", "reorder", "schedule", "trigger",
    "enqueue", "cancel", "transition", "send", "set",
)


def _infer_write(tool):
    """Best-effort read/write classification from the tool-name verb.

    custom_* tools carry the verb after the prefix; native tools start with the
    verb. Browse/get/list/describe/query/facet/preview/is_member/used_by are
    reads; the verbs in _WRITE_VERBS mutate state."""
    base = tool[len("custom_"):] if tool.startswith("custom_") else tool
    verb = base.split("_", 1)[0]
    return verb in _WRITE_VERBS


def step(tool, args=None, *, save=None, skip_if=None, skip_on=(), skip_errors=None,
         native=False, smoke=False, poll=None, after=None, notes="", groups=(),
         write=None):
    """Build one suite step.

    tool        MCP tool name.
    args        dict, or callable(ctx) -> dict. A KeyError inside the callable
                marks the step SKIP (dependency was never created).
    save        callable(ctx, data) run after a PASS; raising marks FAIL.
    skip_if     callable(ctx) -> falsy | reason-string, evaluated pre-call.
    skip_on     iterable of (match, reason): match is a Marketo error code or
                a lowercase message substring; a matching error -> SKIP.
    skip_errors reason string: ANY structured Marketo error (except auth 601/
                602) -> SKIP with this reason. For state/feature-dependent
                steps where errors are documented-expected outcomes.
    native      proxied native tool (infrastructure for the custom suite).
    smoke       part of the designated native smoke set.
    poll        {'done': fn(data)->bool, 'flag': ctx_key} — re-call every
                POLL_INTERVAL until done() or POLL_TIMEOUT; ctx[flag]=done.
    after       callable(ctx, status, data) always run, even on SKIP/FAIL.
    groups      group names this step belongs to (for `full --group NAME`).
    write       True if the step mutates Marketo state, False if it is a pure
                read. Defaults to a verb-based inference from the tool name.
                The read-only run executes only write=False steps; the
                write-only run executes the create/update/delete lifecycle.
    """
    return {
        "tool": tool, "args": args or {}, "save": save, "skip_if": skip_if,
        "skip_on": tuple(skip_on), "skip_errors": skip_errors, "native": native,
        "smoke": smoke, "poll": poll, "after": after, "notes": notes,
        "groups": frozenset(groups),
        "write": _infer_write(tool) if write is None else write,
    }


def _classify(st, data):
    """Classify a parsed tool result into (status, reason)."""
    if isinstance(data, str) and (st["native"] or st["smoke"]):
        # Native tools answer in markdown; some report errors as plain text
        # (no MCP error and no JSON block) — e.g. "Missing required tags...".
        if "❌" in data or ("✅" not in data and "success" not in data.lower()):
            low = data.lower()
            for match, reason in st["skip_on"]:
                if str(match).lower() in low:
                    return SKIP, f"{reason}: {data[:140]}"
            if st["skip_errors"]:
                return SKIP, f"{st['skip_errors']}: {data[:140]}"
            return FAIL, data[:200]
        return PASS, ""
    if not _is_error_payload(data):
        return PASS, ""
    codes, msgs = _marketo_errors(data)
    low = msgs.lower()
    for match, reason in st["skip_on"]:
        if str(match) in codes or str(match).lower() in low:
            return SKIP, f"{reason}: {msgs[:140]}"
    if st["skip_errors"] and not ({"601", "602"} & set(codes)):
        return SKIP, f"{st['skip_errors']}: {msgs[:140]}"
    if "603" in codes:
        return SKIP, f"permission(603): {msgs[:140]}"
    if "704" in codes:
        return SKIP, f"v2-unavailable(704): {msgs[:140]}"
    return FAIL, msgs[:200] or json.dumps(data)[:200]


class FullSuiteRunner:
    def __init__(self, url, headers):
        self.url = url
        self.headers = headers
        self.client = None
        self.records = []  # (tool, kind, status, reason, seconds)

    async def connect(self):
        if self.client is not None:
            try:
                await self.client.__aexit__(None, None, None)
            except Exception:
                pass
        self.client = Client(StreamableHttpTransport(self.url, headers=self.headers))
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
        """Call a tool; reconnect once on transport-level failures."""
        try:
            return await self.client.call_tool(tool, args, timeout=CALL_TIMEOUT)
        except ToolError:
            raise
        except Exception:
            await self.connect()
            return await self.client.call_tool(tool, args, timeout=CALL_TIMEOUT)

    async def run_step(self, st, ctx):
        tool = st["tool"]
        kind = "NATIVE-SMOKE" if st["smoke"] else ("NATIVE" if st["native"] else "CUSTOM")

        if st["skip_if"]:
            reason = st["skip_if"](ctx)
            if reason:
                self.records.append((tool, kind, SKIP, str(reason), 0.0))
                if st["after"]:
                    st["after"](ctx, SKIP, None)
                return

        try:
            args = st["args"](ctx) if callable(st["args"]) else dict(st["args"])
        except KeyError as exc:
            self.records.append((tool, kind, SKIP, f"dependency missing: {exc}", 0.0))
            if st["after"]:
                st["after"](ctx, SKIP, None)
            return

        started = time.time()
        status, reason, data = await self._execute(st, tool, args)

        if status == PASS and st["poll"]:
            deadline = started + POLL_TIMEOUT

            def _done(payload):
                try:
                    return bool(st["poll"]["done"](payload))
                except Exception:
                    return False

            while not _done(data) and time.time() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                status, reason, data = await self._execute(st, tool, args)
                if status != PASS:
                    break
            if st["poll"].get("flag"):
                ctx[st["poll"]["flag"]] = bool(status == PASS and _done(data))

        if status == PASS and st["save"]:
            try:
                st["save"](ctx, data)
            except Exception as exc:
                status, reason = FAIL, f"save failed ({type(exc).__name__}: {exc}); data={json.dumps(data, default=str)[:200]}"

        secs = time.time() - started
        self.records.append((tool, kind, status, reason, secs))
        if st["after"]:
            st["after"](ctx, status, data)
        marker = {PASS: ".", SKIP: "s", FAIL: "F"}[status]
        print(f"{marker} [{len(self.records):3d}] {kind:<12} {tool:<55} {status}"
              + (f"  ({reason[:90]})" if reason else ""), flush=True)

    async def _execute(self, st, tool, args):
        try:
            result = await self._call(tool, args)
        except ToolError as exc:
            msg = str(exc)
            low = msg.lower()
            for match, reason in st["skip_on"]:
                if str(match).lower() in low:
                    return SKIP, f"{reason}: {msg[:140]}", None
            if st["skip_errors"]:
                return SKIP, f"{st['skip_errors']}: {msg[:140]}", None
            return FAIL, f"ToolError: {msg[:200]}", None
        except Exception as exc:
            return FAIL, f"{type(exc).__name__}: {exc}", None
        data = _parse_result(result)
        status, reason = _classify(st, data)
        return status, reason, data


# ---------------------------------------------------------------------------
# Suite definition helpers
# ---------------------------------------------------------------------------

def _rows(data):
    """Result rows from either a {'result': [...]} envelope or a bare list.

    Some native (proxied) tools return the result array directly as their
    structured content (e.g. get_leads_by_filter, bulk_export_create) instead
    of the usual REST envelope."""
    if isinstance(data, dict):
        return data.get("result") or []
    if isinstance(data, list):
        return data
    return []


def _save_key(key, *path):
    """save= helper: ctx[key] = data[path[0]][path[1]]..."""
    def _save(ctx, data):
        value = data
        for part in path:
            value = value[part]
        ctx[key] = value
    return _save


def _save_first_id(key):
    return _save_key(key, "result", 0, "id")


def _need(*keys):
    """skip_if= helper: skip when any ctx key is missing/falsy."""
    def _check(ctx):
        for key in keys:
            if not ctx.get(key):
                return f"dependency missing: {key}"
        return None
    return _check


def _flag_skip(flag):
    """after= helper: record that a probe step was SKIPped (gates its group)."""
    def _after(ctx, status, data):
        if status == SKIP:
            ctx[flag] = True
    return _after


def _group_gate(flag, reason):
    def _check(ctx):
        return reason if ctx.get(flag) else None
    return _check


# NOTE: mktoModule-based (modular / Email Editor 2.0) templates are rejected at
# approveDraft time in this sandbox with "709: There is a problem with the email
# template content" no matter the markup shape (table/tr/div modules, with or
# without mktoContainer, all probed via direct REST). The suite therefore uses
# a plain editor-1.0 template with mktoText sections + a mktoString variable;
# the email-module steps SKIP with "email has no modules".
EMAIL_TEMPLATE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MCPTEST_FULL template</title>
<meta class="mktoString" id="mcptestVar" mktoname="MCPTEST Var" default="hello">
</head>
<body>
<div class="mktoText" id="textone" mktoname="Text One">Hello from section one.</div>
<div class="mktoText" id="texttwo" mktoname="Text Two">Hello from section two.</div>
</body>
</html>
"""

# freeForm LP templates must contain a body div with class="mktoContent",
# otherwise approveDraft fails with "1101 ... missing element : body div.mktoContent".
LP_TEMPLATE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MCPTEST_FULL LP template</title>
</head>
<body>
<div class="mktoContent" id="content">MCPTEST_FULL landing page template body.</div>
</body>
</html>
"""


def build_full_steps(sfx):
    """Return the dependency-ordered list of suite steps.

    Asset names embed the run suffix so reruns never collide; objects the API
    cannot delete (lead/PM fields, activity type, CO type, the Design Studio
    file) use fixed names with reuse-if-exists semantics.
    """
    now = datetime.now(timezone.utc)
    email = lambda n: f"mcptest_full_{sfx}_{n}@example.invalid"
    name = lambda label: f"MCPTEST_FULL_{label}_{sfx}"
    steps = []
    add = steps.append

    # ------------------------------------------------------------------ A. native smoke + discovery
    def save_roots(ctx, data):
        for folder in data.get("result") or []:
            if folder.get("path") == "/Marketing Activities":
                ctx["ma_root"] = folder["id"]
            elif folder.get("path") == "/Design Studio":
                ctx["ds_root"] = folder["id"]
        if "ma_root" not in ctx or "ds_root" not in ctx:
            raise KeyError("Marketing Activities / Design Studio roots not found")

    def save_channel(ctx, data):
        best = None
        for ch in data.get("result") or []:
            if ch.get("applicableProgramType") != "program":
                continue
            statuses = [s["name"] for s in ch.get("progressionStatuses") or []
                        if not s.get("hidden") and s.get("step", 0) > 0]
            if len(statuses) >= 2 and (best is None or ch["name"] == "Chat"):
                best = (ch["name"], statuses)
        if not best:
            raise KeyError("no program-type channel with >=2 statuses")
        ctx["channel"], ctx["statuses"] = best

    add(step("browse_folders", {"maxReturn": 50}, save=save_roots, smoke=True,
             groups=BULK_BOTH))
    add(step("browse_channels", {"maxReturn": 200}, save=save_channel, smoke=True,
             groups=BULK_BOTH))
    add(step("describe_lead", smoke=True))
    add(step("get_leads_by_filter",
             {"filterType": "email", "filterValues": [email(1)]}, smoke=True))
    add(step("browse_programs", {"maxReturn": 5}, smoke=True))
    add(step("browse_forms", {"maxReturn": 5}, smoke=True))
    add(step("browse_smart_campaigns", {"maxReturn": 5}, smoke=True))
    add(step("browse_lists", {"maxReturn": 5}, smoke=True))
    add(step("browse_emails2", {"maxReturn": 5}, smoke=True,
             skip_errors="emails2-native-unavailable"))
    add(step("get_activity_types", smoke=True))
    add(step("browse_smart_lists", {"maxReturn": 5}, smoke=True))
    add(step("browse_snippets", {"maxReturn": 5}, smoke=True))

    # ------------------------------------------------------------------ B. folders
    # Zone roots reject create_folder. Marketing folders go under the Default
    # workspace zone; Design Studio is partitioned per asset type, so the
    # suite needs one scratch folder under each content root it touches.
    def save_ma_parent(ctx, data):
        for folder in data.get("result") or []:
            if folder.get("path") == "/Marketing Activities/Default":
                ctx["ma_parent"] = folder["id"]
                return
        ctx["ma_parent"] = ctx["ma_root"]

    DS_ROOTS = {
        "ds_forms_root": "/Design Studio/Default/Forms",
        "ds_emails_root": "/Design Studio/Default/Emails",
        "ds_etpl_root": "/Design Studio/Default/Emails/Templates",
        "ds_lp_root": "/Design Studio/Default/Landing Pages",
        "ds_lpt_root": "/Design Studio/Default/Landing Pages/Templates",
        "ds_snip_root": "/Design Studio/Default/Snippets",
    }

    def save_ds_roots(ctx, data):
        paths = {f.get("path"): f["id"] for f in data.get("result") or []}
        for key, path in DS_ROOTS.items():
            if path in paths:
                ctx[key] = paths[path]
        missing = [p for k, p in DS_ROOTS.items() if k not in ctx]
        if missing:
            raise KeyError(f"Design Studio content roots not found: {missing}")

    add(step("browse_folders", lambda c: {"root": c["ma_root"], "maxDepth": 1, "maxReturn": 200},
             save=save_ma_parent, native=True, groups=BULK_BOTH,
             notes="find the Default workspace zone under Marketing Activities"))
    add(step("browse_folders", lambda c: {"root": c["ds_root"], "maxDepth": 3, "maxReturn": 200},
             save=save_ds_roots, native=True,
             notes="find the per-asset-type Design Studio content roots"))
    add(step("create_folder",
             lambda c: {"name": name("MA"), "parent": {"id": c["ma_parent"], "type": "Folder"},
                        "description": "MCPTEST full-suite scratch folder"},
             save=_save_first_id("ma_folder"), native=True, groups=BULK_BOTH))
    for ctx_key, root_key, label in [
        ("ds_forms", "ds_forms_root", "FORMS"),
        ("ds_emails", "ds_emails_root", "EMAILS"),
        ("ds_etpl", "ds_etpl_root", "ETPL"),
        ("ds_lp", "ds_lp_root", "LP"),
        ("ds_lpt", "ds_lpt_root", "LPT"),
        ("ds_snip", "ds_snip_root", "SNIP"),
    ]:
        add(step("create_folder",
                 (lambda ck, rk, lb: lambda c: {
                     "name": name(lb), "parent": {"id": c[rk], "type": "Folder"},
                     "description": "MCPTEST full-suite scratch folder"})(ctx_key, root_key, label),
                 save=_save_first_id(ctx_key), native=True))

    # ------------------------------------------------------------------ C. leads + lead schema
    def save_lead_ids(ctx, data):
        ids = [r["id"] for r in data["result"] if r.get("status") in ("created", "updated")]
        if len(ids) < 3:
            raise KeyError(f"expected 3 created leads, got {data['result']}")
        ctx["lead1"], ctx["lead2"], ctx["lead3"] = ids[:3]

    add(step("custom_sync_leads",
             {"leads": [{"email": email(1), "firstName": "MCP", "lastName": "TestOne"},
                        {"email": email(2), "firstName": "MCP", "lastName": "TestTwo"},
                        {"email": email(3), "firstName": "MCP", "lastName": "TestThree"}]},
             save=save_lead_ids, groups=(BULK_EXPORT,)))
    add(step("custom_get_lead_by_id", lambda c: {"lead_id": c["lead1"], "fields": "id,email"}))

    # Field-honoring lead lookup — the reason this custom tool exists is that
    # the native get_leads_by_filter ignores its field argument and returns a
    # fixed default set. Assert a requested non-default field round-trips, so
    # this step FAILs (not silently passes) if field selection ever regresses.
    def _assert_field_selection(ctx, data):
        rows = data.get("result") or []
        if rows and "leadScore" not in rows[0]:
            raise AssertionError(
                "custom_get_leads_by_filter dropped the requested fields "
                f"(got keys {sorted(rows[0])})")
    add(step("custom_get_leads_by_filter",
             lambda c: {"filter_type": "email", "filter_values": [email(1)],
                        "fields": ["id", "email", "leadStatus", "leadScore"]},
             save=_assert_field_selection))
    add(step("custom_describe_lead2"))
    add(step("custom_get_lead_fields", {"batch_size": 5}))
    add(step("custom_get_lead_field_by_name", {"field_api_name": "email"}))
    add(step("custom_create_lead_fields",
             {"fields": [{"displayName": "MCPTEST Full Field1", "name": LEAD_FIELD,
                          "dataType": "string", "description": "MCPTEST suite field"}]},
             skip_on=[("already exist", "pre-existing lead field"),
                      ("1003", "pre-existing lead field")],
             notes="lead fields cannot be deleted via API; fixed name, reuse-if-exists"))
    add(step("custom_update_lead_field",
             {"field_api_name": LEAD_FIELD,
              "updates": {"description": f"MCPTEST updated {sfx}"}}))
    add(step("custom_get_lead_partitions"))
    add(step("custom_update_lead_partitions",
             lambda c: {"assignments": [{"id": c["lead1"], "partitionName": "Default"}]}))
    add(step("custom_get_lead_changes", lambda c: {"lead_id": c["lead1"], "days_back": 1}))
    add(step("custom_get_lead_activities_by_email", {"email": email(1), "days_back": 1}))
    add(step("custom_associate_lead",
             lambda c: {"lead_id": c["lead1"],
                        "cookie": "id:287-GTJ-838&token:_mch-test-mcptest-full"},
             skip_errors="needs-real-cookie",
             notes="fabricated Munchkin cookie; non-auth errors are expected"))
    add(step("custom_get_lead_list_membership", lambda c: {"lead_id": c["lead1"]}))
    add(step("custom_get_lead_program_membership", lambda c: {"lead_id": c["lead1"]}))
    add(step("custom_get_lead_smart_campaign_membership", lambda c: {"lead_id": c["lead1"]}))

    # ------------------------------------------------------------------ D. program + program members
    def save_required_tag_names(ctx, data):
        ctx["req_tag_names"] = [
            tag["tagType"] for tag in data.get("result") or []
            if tag.get("required")
            and "program" in str(tag.get("applicableProgramTypes", ""))]
        ctx["program_tags"] = []

    def save_tag_value(ctx, data):
        for tag in data.get("result") or []:
            values = re.findall(r"[\w-]+", str(tag.get("allowableValues", "")))
            if values:
                ctx.setdefault("program_tags", []).append(
                    {"tagType": tag["tagType"], "tagValue": values[0]})

    add(step("browse_tag_types", {"maxReturn": 200}, native=True,
             save=save_required_tag_names, groups=BULK_BOTH,
             notes="discover required program tags (e.g. 'Team')"))
    for tag_idx in (0, 1):
        add(step("get_tag_type_by_name",
                 (lambda i: lambda c: {"name": c["req_tag_names"][i]})(tag_idx),
                 skip_if=(lambda i: lambda c: (None if len(c.get("req_tag_names", [])) > i
                                               else "no further required program tags"))(tag_idx),
                 native=True, save=save_tag_value, groups=BULK_BOTH,
                 notes="fetch a valid value for a required program tag"))

    def create_program_args(c):
        args = {"name": name("PROG"), "folder": {"id": c["ma_folder"], "type": "Folder"},
                "type": "Default", "channel": c["channel"],
                "description": "MCPTEST full-suite program"}
        if c.get("program_tags"):
            args["tags"] = c["program_tags"]
        return args

    add(step("create_program", create_program_args,
             save=_save_first_id("program_id"), native=True, groups=BULK_BOTH))
    add(step("custom_change_lead_program_status",
             lambda c: {"program_id": c["program_id"], "lead_ids": [c["lead1"]],
                        "status": c["statuses"][0]},
             groups=(BULK_EXPORT,)))
    add(step("custom_push_leads",
             lambda c: {"leads": [{"email": email(4), "firstName": "MCP",
                                   "lastName": "TestFour"}],
                        "lookup_field": "email", "program_name": name("PROG"),
                        "program_status": c["statuses"][0]},
             save=_save_key("lead4", "result", 0, "id"),
             notes="push.json requires programName, so this runs after create_program"))
    add(step("custom_get_leads_by_program",
             lambda c: {"program_id": c["program_id"], "fields": "id,email"}))
    add(step("custom_sync_program_member_status",
             lambda c: {"program_id": c["program_id"], "status_name": c["statuses"][0],
                        "lead_ids": [c["lead2"]]}))
    add(step("custom_query_program_members",
             lambda c: {"program_id": c["program_id"], "filter_type": "leadId",
                        "filter_values": f"{c['lead1']},{c['lead2']}"}))
    add(step("custom_create_program_member_fields",
             {"fields": [{"displayName": "MCPTEST Full PM Field1", "name": PM_FIELD,
                          "dataType": "string", "description": "MCPTEST suite PM field"}]},
             skip_on=[("already exist", "pre-existing PM field"),
                      ("1003", "pre-existing PM field")],
             notes="PM fields cannot be deleted via API; fixed name, reuse-if-exists"))
    add(step("custom_get_program_member_field_by_name", {"field_api_name": PM_FIELD}))
    add(step("custom_update_program_member_field",
             {"field_api_name": PM_FIELD,
              "updates": [{"description": f"MCPTEST updated {sfx}"}]}))
    add(step("custom_sync_program_member_data",
             lambda c: {"program_id": c["program_id"],
                        "members": [{"leadId": c["lead1"], PM_FIELD: f"value-{sfx}"}]},
             skip_on=[("1006", "no-pm-field"), ("invalid field", "no-pm-field")]))
    add(step("custom_delete_program_members",
             lambda c: {"program_id": c["program_id"], "lead_ids": [c["lead2"]]}))
    add(step("custom_unapprove_email_program",
             lambda c: {"program_id": c["program_id"]},
             skip_errors="not-an-email-program",
             notes="program is type Default; unapprove only applies to Email programs"))

    # ------------------------------------------------------------------ E. static list (lives in the program)
    add(step("create_list",
             lambda c: {"name": name("LIST"), "folder": {"id": c["program_id"], "type": "Program"}},
             save=_save_first_id("list_id"), native=True))
    add(step("add_leads_to_list",
             lambda c: {"listId": c["list_id"], "id": [c["lead1"], c["lead2"]]}, native=True))
    add(step("custom_is_member_of_list",
             lambda c: {"list_id": c["list_id"], "lead_ids": [c["lead1"], c["lead2"]]}))
    add(step("custom_remove_leads_from_list",
             lambda c: {"list_id": c["list_id"], "lead_ids": [c["lead2"]]}))

    # ------------------------------------------------------------------ F. forms (Design Studio)
    add(step("create_form",
             lambda c: {"name": name("FORM"), "folder": {"id": c["ds_forms"], "type": "Folder"},
                        "description": "MCPTEST full-suite form"},
             save=_save_first_id("form_id"), native=True))
    add(step("add_field_to_form", lambda c: {"id": c["form_id"], "fieldId": "Email"},
             skip_on=[("already exist", "email-field-pre-existing")], native=True))
    add(step("add_field_to_form", lambda c: {"id": c["form_id"], "fieldId": "FirstName"},
             skip_on=[("already exist", "firstname-field-pre-existing")], native=True,
             notes="new forms come with Email + FirstName pre-added in this instance"))
    add(step("approve_form", lambda c: {"id": c["form_id"]}, native=True))
    add(step("custom_submit_form",
             lambda c: {"form_id": c["form_id"],
                        "lead_form_fields": {"Email": email(1), "FirstName": "MCP"},
                        "visitor_data": {"pageURL": "https://example.invalid/mcptest"}}))
    add(step("custom_update_form_submit_button",
             lambda c: {"form_id": c["form_id"], "label": "MCPTEST Go",
                        "waiting_label": "Sending..."}))
    add(step("get_thank_you_page", lambda c: {"id": c["form_id"]}, native=True))
    add(step("custom_update_form_thank_you_pages",
             lambda c: {"form_id": c["form_id"],
                        "rules": [{"default": True, "followupType": "url",
                                   "followupValue": "https://example.com/mcptest-thanks"}]},
             notes="API rejects followupValue=null (611), even for type 'none'; "
                   "a url rule is the only round-trippable shape"))
    add(step("custom_delete_form_field",
             lambda c: {"form_id": c["form_id"], "field_id": "FirstName"}))
    add(step("add_field_set", lambda c: {"id": c["form_id"], "label": "MCPTEST FS"},
             native=True,
             save=lambda c, d: c.__setitem__("fieldset_id",
                                             (d.get("result") or [{}])[0].get("id"))))
    add(step("custom_delete_form_fieldset_field",
             lambda c: {"form_id": c["form_id"], "field_set_id": str(c["fieldset_id"]),
                        "field_id": "LastName"},
             skip_if=lambda c: None if c.get("fieldset_id") else "no fieldset created",
             skip_errors="no-fieldset-field",
             notes="API has no way to place a field inside a fieldset; expected to skip"))
    add(step("custom_discard_form_draft", lambda c: {"form_id": c["form_id"]}))

    # ------------------------------------------------------------------ G. email templates + emails
    add(step("custom_create_email_template",
             lambda c: {"name": name("TPL"), "folder_id": c["ds_etpl"],
                        "html_content": EMAIL_TEMPLATE_HTML,
                        "description": "MCPTEST full-suite template"},
             save=_save_first_id("tpl_id")))
    add(step("custom_browse_email_templates", {"max_return": 5}))
    add(step("custom_get_email_template_by_id", lambda c: {"template_id": c["tpl_id"]}))
    add(step("custom_get_email_template_by_name", lambda c: {"name": name("TPL")}))
    add(step("custom_get_email_template_content", lambda c: {"template_id": c["tpl_id"]}))
    add(step("custom_update_email_template",
             lambda c: {"template_id": c["tpl_id"], "description": f"MCPTEST updated {sfx}"}))
    add(step("custom_approve_email_template", lambda c: {"template_id": c["tpl_id"]}))
    add(step("custom_get_email_template_used_by", lambda c: {"template_id": c["tpl_id"]}))
    add(step("custom_clone_email_template",
             lambda c: {"template_id": c["tpl_id"], "name": name("TPL_CLONE"),
                        "folder_id": c["ds_etpl"]},
             save=_save_first_id("tpl_clone_id")))
    add(step("create_email",
             lambda c: {"name": name("EMAIL"), "template": c["tpl_id"],
                        "folder": {"id": c["ds_emails"], "type": "Folder"},
                        "subject": "MCPTEST full-suite subject",
                        "fromName": "MCPTEST", "fromEmail": SAMPLE_EMAIL_TO},
             save=_save_first_id("email_id"), native=True))
    add(step("custom_update_email",
             lambda c: {"email_id": c["email_id"], "description": f"MCPTEST {sfx}"}))
    add(step("custom_update_email_headers",
             lambda c: {"email_id": c["email_id"], "subject": f"MCPTEST subject {sfx}",
                        "reply_to": SAMPLE_EMAIL_TO}))
    add(step("custom_get_email_variables", lambda c: {"email_id": c["email_id"]},
             save=lambda c, d: c.__setitem__("email_vars",
                                             [v.get("name") or v.get("id")
                                              for v in d.get("result") or []]),
             skip_errors="no-email-variables"))
    add(step("custom_update_email_variable",
             lambda c: {"email_id": c["email_id"], "variable_name": c["email_vars"][0],
                        "value": "world"},
             skip_if=lambda c: None if c.get("email_vars") else "no variables on email"))

    def save_email_sections(ctx, data):
        ctx["email_sections"] = data.get("result") or []
        modules = [s for s in ctx["email_sections"] if str(s.get("contentType")) == "Module"]
        texts = [s for s in ctx["email_sections"]
                 if str(s.get("contentType")) in ("Text", "HTML")]
        ctx["email_modules"] = [m.get("htmlId") for m in modules]
        ctx["email_text_section"] = texts[0].get("htmlId") if texts else None

    add(step("get_email_content", lambda c: {"id": c["email_id"]},
             save=save_email_sections, native=True))
    add(step("custom_add_email_module",
             lambda c: {"email_id": c["email_id"], "module_id": c["email_modules"][0],
                        "name": "MCPTEST Module Copy", "index": 1},
             skip_if=lambda c: None if c.get("email_modules") else "email has no modules",
             skip_on=[("611", "no-modular-editor")],
             save=lambda c, d: c.__setitem__("added_module",
                                             (d.get("result") or [{}])[0].get("id"))))
    add(step("custom_rename_email_module",
             lambda c: {"email_id": c["email_id"], "module_id": c["added_module"],
                        "name": "MCPTEST Module Renamed"},
             skip_if=lambda c: None if c.get("added_module") else "no module was added"))
    add(step("custom_duplicate_email_module",
             lambda c: {"email_id": c["email_id"], "module_id": c["email_modules"][0],
                        "name": "MCPTEST Module Dupe"},
             skip_if=lambda c: None if c.get("email_modules") else "email has no modules",
             save=lambda c, d: c.__setitem__("dupe_module",
                                             (d.get("result") or [{}])[0].get("id"))))
    add(step("custom_rearrange_email_modules",
             lambda c: {"email_id": c["email_id"],
                        "positions": [{"index": i, "moduleId": m} for i, m in enumerate(
                            reversed([m for m in [c["email_modules"][0],
                                                  c.get("added_module"),
                                                  c.get("dupe_module")] + c["email_modules"][1:]
                                      if m]))]},
             skip_if=lambda c: None if c.get("email_modules") else "email has no modules",
             skip_errors="rearrange-rejected"))
    add(step("custom_delete_email_module",
             lambda c: {"email_id": c["email_id"], "module_id": c["dupe_module"]},
             skip_if=lambda c: None if c.get("dupe_module") else "no duplicated module"))

    def save_segmentation(ctx, data):
        for seg in data.get("result") or []:
            if seg.get("status") == "approved":
                ctx["seg_id"] = seg["id"]
                break

    add(step("custom_browse_segmentations", save=save_segmentation))
    add(step("custom_get_segments", lambda c: {"segmentation_id": c["seg_id"]},
             skip_if=lambda c: None if c.get("seg_id") else "no approved segmentation",
             save=lambda c, d: c.__setitem__("segments",
                                             [s["name"] for s in d.get("result") or []])))
    add(step("update_email_content",
             lambda c: {"id": c["email_id"], "htmlId": c["email_text_section"],
                        "type": "DynamicContent", "value": str(c["seg_id"])},
             skip_if=lambda c: (None if (c.get("seg_id") and c.get("email_text_section"))
                                else "needs a segmentation and a text section"),
             native=True, skip_errors="dynamic-content-conversion-rejected"))

    def save_email_dc(ctx, data):
        for section in data.get("result") or []:
            if str(section.get("contentType")) == "DynamicContent":
                value = section.get("value")
                ctx["email_dc_id"] = value if isinstance(value, (str, int)) else section.get("htmlId")
                break

    add(step("get_email_content", lambda c: {"id": c["email_id"], "status": "draft"},
             save=save_email_dc, native=True))
    add(step("custom_get_email_dynamic_content",
             lambda c: {"email_id": c["email_id"], "dynamic_content_id": str(c["email_dc_id"])},
             skip_if=lambda c: None if c.get("email_dc_id") else "no dynamic content section"))
    add(step("custom_update_email_dynamic_content",
             lambda c: {"email_id": c["email_id"], "dynamic_content_id": str(c["email_dc_id"]),
                        "segment": [s for s in c.get("segments", []) if s != "Default"][0],
                        "type": "HTML", "value": "<p>MCPTEST segment content</p>"},
             skip_if=lambda c: (None if (c.get("email_dc_id") and
                                         [s for s in c.get("segments", []) if s != "Default"])
                                else "no dynamic content section / segments")))
    add(step("custom_update_email_full_content",
             lambda c: {"email_id": c["email_id"],
                        "html_content": "<html><body><p>MCPTEST full content</p></body></html>"},
             skip_errors="not-supported-for-modular-email",
             notes="fullContent rejects module-based (editor 2.0) emails"))
    add(step("custom_send_sample_email",
             lambda c: {"email_id": c["email_id"], "email_address": SAMPLE_EMAIL_TO}))
    add(step("custom_preview_email", lambda c: {"email_id": c["email_id"]}))
    add(step("custom_get_email_cc_fields"))
    add(step("approve_email", lambda c: {"id": c["email_id"]}, native=True))
    add(step("custom_update_email_headers",
             lambda c: {"email_id": c["email_id"], "subject": f"MCPTEST draft subject {sfx}"},
             notes="creates a draft on the approved email"))
    add(step("custom_discard_email_draft", lambda c: {"email_id": c["email_id"]}))
    add(step("custom_clone_email",
             lambda c: {"email_id": c["email_id"], "name": name("EMAIL_CLONE"),
                        "folder_id": c["ds_emails"]},
             save=_save_first_id("email_clone_id")))
    add(step("custom_unapprove_email", lambda c: {"email_id": c["email_id"]}))
    add(step("custom_update_email_template_content",
             lambda c: {"template_id": c["tpl_id"],
                        "html_content": EMAIL_TEMPLATE_HTML.replace(
                            "Hello from module one.", "Hello from module one (draft).")},
             notes="creates a draft on the approved template"))
    add(step("custom_discard_email_template_draft", lambda c: {"template_id": c["tpl_id"]}))

    # ------------------------------------------------------------------ H. landing page templates + landing pages
    add(step("custom_create_landing_page_template",
             lambda c: {"name": name("LPT"), "folder_id": c["ds_lpt"],
                        "description": "MCPTEST full-suite LP template",
                        "template_type": "freeForm"},
             save=_save_first_id("lpt_id")))
    add(step("custom_browse_landing_page_templates", {"max_return": 5}))
    add(step("custom_get_landing_page_template_by_id", lambda c: {"template_id": c["lpt_id"]}))
    add(step("custom_get_landing_page_template_by_name", lambda c: {"name": name("LPT")}))
    add(step("custom_update_landing_page_template",
             lambda c: {"template_id": c["lpt_id"], "description": f"MCPTEST updated {sfx}"}))
    add(step("custom_update_landing_page_template_content",
             lambda c: {"template_id": c["lpt_id"], "html_content": LP_TEMPLATE_HTML}))
    add(step("custom_get_landing_page_template_content", lambda c: {"template_id": c["lpt_id"]}))
    add(step("custom_approve_landing_page_template", lambda c: {"template_id": c["lpt_id"]}))
    add(step("custom_clone_landing_page_template",
             lambda c: {"template_id": c["lpt_id"], "name": name("LPT_CLONE"),
                        "folder_id": c["ds_lpt"]},
             save=_save_first_id("lpt_clone_id")))
    add(step("custom_update_landing_page_template_content",
             lambda c: {"template_id": c["lpt_id"],
                        "html_content": LP_TEMPLATE_HTML.replace(
                            "template body.", "template body (draft).")},
             notes="creates a draft on the approved LP template"))
    add(step("custom_discard_landing_page_template_draft",
             lambda c: {"template_id": c["lpt_id"]}))
    add(step("custom_create_landing_page",
             lambda c: {"name": name("LP"), "folder_id": c["ds_lp"],
                        "template_id": c["lpt_id"],
                        "description": "MCPTEST full-suite landing page"},
             save=_save_first_id("lp_id"), skip_errors="lp-create-unavailable"))
    add(step("custom_browse_landing_pages", {"max_return": 5}))
    add(step("custom_get_landing_page_by_id", lambda c: {"landing_page_id": c["lp_id"]}))
    add(step("custom_get_landing_page_by_name", lambda c: {"name": name("LP")}))
    add(step("custom_update_landing_page",
             lambda c: {"landing_page_id": c["lp_id"], "title": f"MCPTEST title {sfx}"}))
    add(step("custom_add_landing_page_content_section",
             lambda c: {"landing_page_id": c["lp_id"], "content_id": f"mcptest-sec-{sfx}",
                        "content_type": "HTML", "value": "<p>MCPTEST section</p>",
                        "layout": {"left": 10, "top": 10, "width": 300, "height": 80}},
             skip_errors="lp-section-add-rejected"))

    def save_lp_section(ctx, data):
        sections = data.get("result") or []
        for section in sections:
            if str(section.get("type", "")).upper() in ("HTML", "RICHTEXT"):
                ctx["lp_section_id"] = section["id"]
                return
        if sections:
            ctx["lp_section_id"] = sections[0]["id"]

    add(step("custom_get_landing_page_content",
             lambda c: {"landing_page_id": c["lp_id"]}, save=save_lp_section))
    add(step("custom_update_landing_page_content_section",
             lambda c: {"landing_page_id": c["lp_id"], "content_id": str(c["lp_section_id"]),
                        "content_type": "HTML", "value": "<p>MCPTEST updated section</p>"},
             skip_if=lambda c: None if c.get("lp_section_id") else "no LP content section"))
    add(step("custom_update_landing_page_content_section",
             lambda c: {"landing_page_id": c["lp_id"], "content_id": str(c["lp_section_id"]),
                        "content_type": "DynamicContent", "value": str(c["seg_id"])},
             skip_if=lambda c: (None if (c.get("lp_section_id") and c.get("seg_id"))
                                else "needs an LP section and a segmentation"),
             skip_errors="lp-dc-conversion-rejected",
             notes="converts the HTML section to dynamic content"))

    def save_lp_dc(ctx, data):
        for section in data.get("result") or []:
            if str(section.get("type", "")) == "DynamicContent":
                value = section.get("content") or section.get("value")
                ctx["lp_dc_id"] = value if isinstance(value, (str, int)) else section.get("id")
                break

    add(step("custom_get_landing_page_content",
             lambda c: {"landing_page_id": c["lp_id"], "status": "draft"}, save=save_lp_dc))
    add(step("custom_get_landing_page_full_content", lambda c: {"landing_page_id": c["lp_id"]},
             skip_errors="lp-full-content-unavailable"))
    add(step("custom_get_landing_page_variables", lambda c: {"landing_page_id": c["lp_id"]},
             skip_errors="freeform-lp-has-no-variables"))
    add(step("custom_update_landing_page_variable",
             lambda c: {"landing_page_id": c["lp_id"], "variable_id": "none", "value": "x"},
             skip_if=lambda c: "freeForm landing page has no variables (guided only)"))
    add(step("custom_update_landing_page_dynamic_content",
             lambda c: {"landing_page_id": c["lp_id"],
                        "dynamic_content_id": str(c["lp_dc_id"]),
                        "segment": [s for s in c.get("segments", []) if s != "Default"][0],
                        "content_type": "HTML", "value": "<p>MCPTEST DC</p>"},
             skip_if=lambda c: (None if c.get("lp_dc_id") else
                                "no dynamic content section on landing page")))
    add(step("custom_get_landing_page_dynamic_content",
             lambda c: {"landing_page_id": c["lp_id"],
                        "dynamic_content_id": str(c["lp_dc_id"])},
             skip_if=lambda c: (None if c.get("lp_dc_id") else
                                "no dynamic content section on landing page")))
    add(step("custom_delete_landing_page_content_section",
             lambda c: {"landing_page_id": c["lp_id"], "content_id": str(c["lp_section_id"])},
             skip_if=lambda c: None if c.get("lp_section_id") else "no LP content section"))
    add(step("custom_approve_landing_page", lambda c: {"landing_page_id": c["lp_id"]},
             skip_errors="lp-approve-unavailable",
             after=lambda c, s, d: c.__setitem__("lp_approved", s == PASS),
             notes="needs an LP domain (CNAME)"))
    # Lifecycle order matters: make+discard a draft and clone while the page
    # is still approved, THEN unapprove (an unapproved page's draft is its
    # only version — discarding it would delete the page outright).
    add(step("custom_update_landing_page",
             lambda c: {"landing_page_id": c["lp_id"], "description": f"draft for discard {sfx}"},
             skip_if=lambda c: None if c.get("lp_approved") else "landing page never approved",
             notes="creates a fresh draft on the approved page"))
    add(step("custom_discard_landing_page_draft", lambda c: {"landing_page_id": c["lp_id"]},
             skip_errors="no-lp-draft"))
    add(step("custom_clone_landing_page",
             lambda c: {"landing_page_id": c["lp_id"], "name": name("LP_CLONE"),
                        "folder_id": c["ds_lp"], "template_id": c["lpt_id"]},
             save=_save_first_id("lp_clone_id"),
             notes="Marketo requires a template id when cloning a landing page"))
    add(step("custom_unapprove_landing_page", lambda c: {"landing_page_id": c["lp_id"]},
             skip_if=lambda c: None if c.get("lp_approved") else "landing page never approved",
             skip_errors="lp-state"))
    add(step("custom_get_landing_page_domains",
             save=lambda c, d: c.__setitem__("lp_domains",
                                             [r.get("domain") or r.get("name")
                                              for r in d.get("result") or []])))
    add(step("custom_browse_redirect_rules", {"max_return": 5}))
    add(step("custom_create_redirect_rule",
             lambda c: {"hostname": c["lp_domains"][0],
                        "from_type": "path", "from_value": f"/mcptest-full-from-{sfx}.html",
                        "to_type": "path", "to_value": f"/mcptest-full-to-{sfx}.html"},
             skip_if=lambda c: None if c.get("lp_domains") else "no LP domains configured",
             save=_save_first_id("redirect_id"), skip_errors="redirect-create-rejected"))
    add(step("custom_get_redirect_rule_by_id", lambda c: {"rule_id": c["redirect_id"]},
             skip_if=_need("redirect_id")))
    add(step("custom_update_redirect_rule",
             lambda c: {"rule_id": c["redirect_id"],
                        "to_type": "path", "to_value": f"/mcptest-full-to2-{sfx}.html"},
             skip_if=_need("redirect_id")))
    add(step("custom_delete_redirect_rule", lambda c: {"rule_id": c["redirect_id"]},
             skip_if=_need("redirect_id")))

    # ------------------------------------------------------------------ I. smart campaigns / smart lists / snippets
    def save_sc_id(ctx, data):
        # Native create_smart_campaign answers {"campaign": {...}} rather than
        # the usual {"result": [...]} envelope.
        if isinstance(data, dict) and isinstance(data.get("campaign"), dict):
            ctx["sc_id"] = data["campaign"]["id"]
        else:
            ctx["sc_id"] = _rows(data)[0]["id"]

    add(step("create_smart_campaign",
             lambda c: {"name": name("SC"), "folder": {"id": c["ma_folder"], "type": "Folder"}},
             save=save_sc_id, native=True))
    add(step("custom_clone_smart_campaign",
             lambda c: {"campaign_id": c["sc_id"], "name": name("SC_CLONE"),
                        "folder_id": c["ma_folder"]},
             save=_save_first_id("sc_clone_id")))
    add(step("activate_smart_campaign", lambda c: {"id": c["sc_id"]},
             native=True, skip_errors="campaign-not-activatable",
             notes="campaign has no triggers/flow; activation error is expected"))
    add(step("custom_deactivate_smart_campaign", lambda c: {"campaign_id": c["sc_id"]},
             skip_errors="campaign-not-active"))
    add(step("create_smart_list",
             lambda c: {"name": name("SL"),
                        "folder": json.dumps({"id": c["program_id"], "type": "Program"})},
             save=_save_first_id("sl_id"), native=True, skip_errors="smart-list-create"))
    add(step("create_snippet",
             lambda c: {"name": name("SNIP"), "type": "HTML",
                        "folder": {"id": c["ds_snip"], "type": "Folder"}},
             save=_save_first_id("snippet_id"), native=True))
    add(step("update_snippet_content",
             lambda c: {"id": c["snippet_id"], "type": "HTML",
                        "content": "<p>MCPTEST snippet</p>"}, native=True))
    add(step("approve_snippet", lambda c: {"id": c["snippet_id"]}, native=True))
    add(step("update_snippet_content",
             lambda c: {"id": c["snippet_id"], "type": "HTML",
                        "content": "<p>MCPTEST snippet draft</p>"}, native=True,
             notes="creates a draft on the approved snippet"))
    add(step("custom_discard_snippet_draft", lambda c: {"snippet_id": c["snippet_id"]}))
    add(step("custom_unapprove_snippet", lambda c: {"snippet_id": c["snippet_id"]}))

    # ------------------------------------------------------------------ J. files (no delete API: tiny per-run file, cannot be cleaned up)
    # TOOL BUG (marketo_rest/email_tools.py): custom_upload_file /
    # custom_replace_file_content send the multipart file part WITHOUT a
    # per-part Content-Type, so Marketo stores the request envelope type
    # ("multipart/form-data; boundary=...") as the file's mimeType. Inserting
    # a NEW file still works, but any overwrite/replace then fails with 709
    # ("Update file type must be the same as the original file") because the
    # boundary differs on every request. The suite therefore uploads a unique
    # per-run file (insert path) and documents replace as a tool bug.
    file_name = f"MCPTEST_FULL_file_{sfx}.txt"

    def save_file_folder(ctx, data):
        for file in data.get("result") or []:
            folder = file.get("folder") or {}
            if folder.get("id"):
                ctx["file_folder"] = folder["id"]
                return

    add(step("custom_browse_files", {"max_return": 10}, save=save_file_folder))
    add(step("custom_upload_file",
             lambda c: {"name": file_name, "folder_id": c["file_folder"],
                        "file_content": f"MCPTEST full suite run {sfx}\n",
                        "insert_only": True,
                        "description": "MCPTEST suite file (files cannot be deleted via API)"},
             skip_if=lambda c: None if c.get("file_folder") else "no existing files folder found",
             save=_save_first_id("file_id"),
             notes="unique per-run name: overwrites hit tool bug 709 (see section comment)"))
    add(step("custom_get_file_by_name", lambda c: {"name": file_name},
             skip_if=_need("file_id")))
    add(step("custom_get_file_by_id", lambda c: {"file_id": c["file_id"]},
             skip_if=_need("file_id")))
    add(step("custom_replace_file_content",
             lambda c: {"file_id": c["file_id"], "file_name": file_name,
                        "file_content": f"MCPTEST full suite run {sfx} (replaced)\n"},
             skip_if=_need("file_id"),
             skip_on=[("709", "TOOL-BUG-709-multipart-mime (no per-part Content-Type; "
                              "replace can never match the stored mimeType)")]))

    # ------------------------------------------------------------------ K. tokens
    add(step("create_token",
             lambda c: {"id": c["ma_folder"], "name": "MCPTEST_FULL_token", "type": "text",
                        "value": "MCPTEST token value"}, native=True))
    add(step("custom_delete_token",
             lambda c: {"folder_id": c["ma_folder"], "name": "MCPTEST_FULL_token",
                        "token_type": "text"}))

    # ------------------------------------------------------------------ L. custom activity types (fixed apiName, reuse-if-exists)
    def save_act_types(ctx, data):
        ctx["act_type_pre_existing"] = any(
            t.get("apiName") == ACT_TYPE for t in data.get("result") or [])

    def act_create_after(ctx, status, data):
        ctx["act_ok"] = status == PASS or ctx.get("act_type_pre_existing")

    act_gate = lambda c: None if c.get("act_ok") else "activity type unavailable (create failed)"

    add(step("custom_get_custom_activity_types", save=save_act_types))
    add(step("custom_create_custom_activity_type",
             {"api_name": ACT_TYPE, "name": "MCPTEST Full Activity",
              "filter_name": "MCPTEST Full Activity Filter",
              "trigger_name": "MCPTEST Full Activity Trigger",
              "primary_attribute": {"apiName": "mcptestPrimary", "name": "MCPTEST Primary"},
              "description": "MCPTEST suite activity type"},
             skip_on=[("already exist", "pre-existing activity type")],
             after=act_create_after,
             notes="primaryAttribute dataType must be omitted (API forces string)"))
    add(step("custom_describe_custom_activity_type", {"api_name": ACT_TYPE, "draft": True},
             skip_if=act_gate, skip_errors="no-activity-type-draft"))
    add(step("custom_update_custom_activity_type",
             {"api_name": ACT_TYPE, "description": f"MCPTEST updated {sfx}"},
             skip_if=act_gate))
    add(step("custom_add_custom_activity_type_attributes",
             {"api_name": ACT_TYPE,
              "attributes": [{"apiName": "mcptestAttrA", "name": "MCPTEST Attr A",
                              "dataType": "string"},
                             {"apiName": "mcptestAttrB", "name": "MCPTEST Attr B",
                              "dataType": "string"}]},
             skip_if=act_gate, skip_on=[("already exist", "pre-existing attributes")]))
    add(step("custom_update_custom_activity_type_attributes",
             {"api_name": ACT_TYPE,
              "attributes": [{"apiName": "mcptestAttrA", "name": "MCPTEST Attr A2",
                              "dataType": "string"}]},
             skip_if=act_gate))
    add(step("custom_delete_custom_activity_type_attributes",
             {"api_name": ACT_TYPE, "attributes": [{"apiName": "mcptestAttrB"}]},
             skip_if=act_gate))
    add(step("custom_approve_custom_activity_type", {"api_name": ACT_TYPE},
             skip_if=act_gate, skip_on=[("no draft", "act-type-already-approved")]))

    def save_act_type_id(ctx, data):
        ctx["act_type_id"] = data["result"][0]["id"]

    add(step("custom_describe_custom_activity_type", {"api_name": ACT_TYPE},
             skip_if=act_gate, save=save_act_type_id))
    add(step("custom_add_custom_activities",
             lambda c: {"activities": [{"leadId": c["lead1"],
                                        "activityTypeId": c["act_type_id"],
                                        "activityDate": _iso(now),
                                        "primaryAttributeValue": f"mcptest-{sfx}",
                                        "attributes": [{"name": "mcptestAttrA",
                                                        "value": "attr-value"}]}]},
             skip_if=_need("act_type_id")))
    add(step("custom_update_custom_activity_type",
             {"api_name": ACT_TYPE, "description": f"MCPTEST draft {sfx}"},
             skip_if=act_gate, notes="creates a draft on the approved type"))
    add(step("custom_discard_custom_activity_type_draft", {"api_name": ACT_TYPE},
             skip_if=act_gate))

    # ------------------------------------------------------------------ M. CRM objects (no native CRM sync in sandbox)
    add(step("custom_describe_companies", after=_flag_skip("no_crm")))
    crm_gate = _group_gate("no_crm", "crm-synced instance (companies API unavailable)")
    add(step("custom_sync_companies",
             {"records": [{"externalCompanyId": f"mcptest-co-{sfx}",
                           "company": "MCPTEST Full Co"}]}, skip_if=crm_gate))
    add(step("custom_query_companies",
             {"filter_type": "externalCompanyId", "filter_values": f"mcptest-co-{sfx}"},
             skip_if=crm_gate))
    add(step("custom_get_company_fields", {"batch_size": 5}, skip_if=crm_gate))
    add(step("custom_get_company_field_by_name", {"field_api_name": "externalCompanyId"},
             skip_if=crm_gate))
    add(step("custom_delete_companies",
             {"records": [{"externalCompanyId": f"mcptest-co-{sfx}"}]}, skip_if=crm_gate))
    add(step("custom_describe_opportunities", skip_if=crm_gate))
    add(step("custom_sync_opportunities",
             {"records": [{"externalOpportunityId": f"mcptest-opp-{sfx}",
                           "name": "MCPTEST Full Opp"}]}, skip_if=crm_gate))
    add(step("custom_query_opportunities",
             {"filter_type": "externalOpportunityId", "filter_values": f"mcptest-opp-{sfx}"},
             skip_if=crm_gate))
    add(step("custom_get_opportunity_fields", {"batch_size": 5}, skip_if=crm_gate))
    add(step("custom_get_opportunity_field_by_name",
             {"field_api_name": "externalOpportunityId"}, skip_if=crm_gate))
    add(step("custom_describe_opportunity_roles", skip_if=crm_gate))
    add(step("custom_sync_opportunity_roles",
             lambda c: {"records": [{"externalOpportunityId": f"mcptest-opp-{sfx}",
                                     "leadId": c["lead1"], "role": "MCPTEST"}]},
             skip_if=crm_gate))
    add(step("custom_query_opportunity_roles",
             lambda c: {"filter_type": "leadId", "filter_values": str(c["lead1"])},
             skip_if=crm_gate))
    add(step("custom_delete_opportunity_roles",
             lambda c: {"records": [{"externalOpportunityId": f"mcptest-opp-{sfx}",
                                     "leadId": c["lead1"], "role": "MCPTEST"}]},
             skip_if=crm_gate))
    add(step("custom_delete_opportunities",
             {"records": [{"externalOpportunityId": f"mcptest-opp-{sfx}"}]}, skip_if=crm_gate))
    add(step("custom_describe_sales_persons", skip_if=crm_gate))
    add(step("custom_sync_sales_persons",
             {"records": [{"externalSalesPersonId": f"mcptest-sp-{sfx}",
                           "email": f"mcptest_sp_{sfx}@example.invalid",
                           "firstName": "MCP", "lastName": "SalesTest"}]}, skip_if=crm_gate))
    add(step("custom_query_sales_persons",
             {"filter_type": "externalSalesPersonId", "filter_values": f"mcptest-sp-{sfx}"},
             skip_if=crm_gate))
    add(step("custom_delete_sales_persons",
             {"records": [{"externalSalesPersonId": f"mcptest-sp-{sfx}"}]}, skip_if=crm_gate))

    # ------------------------------------------------------------------ N. custom objects (fixed apiName, reuse-if-exists)
    add(step("custom_list_custom_object_types"))
    add(step("custom_get_custom_object_field_types"))
    add(step("custom_get_custom_object_linkable_objects"))
    add(step("custom_sync_custom_object_type",
             {"api_name": CO_TYPE, "display_name": "MCPTEST Full CO",
              "plural_name": "MCPTEST Full COs", "action": "createOrUpdate",
              "description": "MCPTEST suite custom object"},
             after=_flag_skip("no_co_schema"), groups=BULK_BOTH))
    co_gate = _group_gate("no_co_schema", "custom-object schema API unavailable")
    add(step("custom_describe_custom_object_type", {"api_name": CO_TYPE, "state": "draft"},
             skip_if=co_gate, skip_errors="no-co-draft"))
    add(step("custom_add_custom_object_type_fields",
             {"api_name": CO_TYPE,
              "fields": [{"name": "mcptestKey", "displayName": "MCPTEST Key",
                          "dataType": "string", "isDedupeField": True},
                         {"name": "mcptestVal", "displayName": "MCPTEST Val",
                          "dataType": "string"}]},
             skip_if=co_gate,
             skip_on=[("already exist", "pre-existing CO fields"),
                      ("dedupe fields cannot be added",
                       "pre-existing approved CO type (fields already in place)")],
             groups=BULK_BOTH))
    add(step("custom_update_custom_object_type_field",
             {"api_name": CO_TYPE, "field_api_name": "mcptestVal",
              "updates": {"description": f"MCPTEST updated {sfx}"}},
             skip_if=co_gate, skip_errors="co-field-update-rejected"))
    add(step("custom_approve_custom_object_type", {"api_name": CO_TYPE}, skip_if=co_gate,
             skip_on=[("no draft", "co-already-approved")], groups=BULK_BOTH))
    add(step("custom_list_custom_objects", {"names": CO_TYPE}, skip_if=co_gate))
    add(step("custom_describe_custom_object", {"object_api_name": CO_TYPE}, skip_if=co_gate))
    add(step("custom_get_custom_object_type_dependents", {"api_name": CO_TYPE},
             skip_if=co_gate))
    add(step("custom_sync_custom_objects",
             {"object_api_name": CO_TYPE,
              "records": [{"mcptestKey": f"k1-{sfx}", "mcptestVal": "v1"}]},
             skip_if=co_gate, after=_flag_skip("no_co_records"),
             groups=(BULK_EXPORT,)))
    co_rec_gate = _group_gate("no_co_records", "custom-object records unavailable")
    add(step("custom_query_custom_objects",
             {"object_api_name": CO_TYPE, "filter_type": "mcptestKey",
              "filter_values": f"k1-{sfx}"}, skip_if=co_rec_gate))
    add(step("custom_import_custom_objects_csv",
             {"object_api_name": CO_TYPE,
              "csv_content": f"mcptestKey,mcptestVal\nk2-{sfx},v2\n"},
             skip_if=co_rec_gate, save=_save_key("co_batch", "result", 0, "batchId"),
             groups=(BULK_IMPORT,)))
    add(step("custom_get_custom_object_import_status",
             lambda c: {"object_api_name": CO_TYPE, "batch_id": c["co_batch"]},
             skip_if=_need("co_batch"),
             poll={"done": _job_done,
                   "flag": "co_import_done"},
             groups=(BULK_IMPORT,)))
    add(step("custom_get_custom_object_import_failures",
             lambda c: {"object_api_name": CO_TYPE, "batch_id": c["co_batch"]},
             skip_if=_need("co_batch"), groups=(BULK_IMPORT,)))
    add(step("custom_get_custom_object_import_warnings",
             lambda c: {"object_api_name": CO_TYPE, "batch_id": c["co_batch"]},
             skip_if=_need("co_batch"), groups=(BULK_IMPORT,)))
    add(step("custom_create_custom_object_export_job",
             lambda c: {"object_api_name": CO_TYPE,
                        "fields": ["mcptestKey", "mcptestVal"],
                        "filter": {"updatedAt": {"startAt": _iso(now - timedelta(minutes=2)),
                                                 "endAt": _iso(datetime.now(timezone.utc)
                                                               + timedelta(minutes=1))}}},
             skip_if=co_rec_gate, save=_save_key("co_export", "result", 0, "exportId"),
             groups=(BULK_EXPORT,),
             notes="CO export only accepts an updatedAt (or list) filter; "
                   "minutes-wide window around this run's records keeps the job tiny"))
    add(step("custom_enqueue_custom_object_export_job",
             lambda c: {"object_api_name": CO_TYPE, "export_id": c["co_export"]},
             skip_if=_need("co_export"), groups=(BULK_EXPORT,)))
    add(step("custom_get_custom_object_export_job_status",
             lambda c: {"object_api_name": CO_TYPE, "export_id": c["co_export"]},
             skip_if=_need("co_export"),
             poll={"done": _job_done,
                   "flag": "co_export_done"},
             groups=(BULK_EXPORT,)))
    add(step("custom_get_custom_object_export_file",
             lambda c: {"object_api_name": CO_TYPE, "export_id": c["co_export"]},
             skip_if=lambda c: (None if (c.get("co_export") and c.get("co_export_done"))
                                else "export job still pending after poll window"),
             groups=(BULK_EXPORT,)))
    add(step("custom_create_custom_object_export_job",
             lambda c: {"object_api_name": CO_TYPE, "fields": ["mcptestKey"],
                        "filter": {"updatedAt": {"startAt": _iso(now - timedelta(minutes=2)),
                                                 "endAt": _iso(datetime.now(timezone.utc)
                                                               + timedelta(minutes=1))}}},
             skip_if=co_rec_gate, save=_save_key("co_export2", "result", 0, "exportId"),
             groups=(BULK_EXPORT,),
             notes="second job, created only to exercise cancel"))
    add(step("custom_cancel_custom_object_export_job",
             lambda c: {"object_api_name": CO_TYPE, "export_id": c["co_export2"]},
             skip_if=_need("co_export2"), groups=(BULK_EXPORT,)))
    add(step("custom_list_custom_object_export_jobs", {"object_api_name": CO_TYPE},
             skip_if=co_gate, groups=(BULK_EXPORT,)))
    add(step("custom_delete_custom_objects",
             {"object_api_name": CO_TYPE,
              "records": [{"mcptestKey": f"k1-{sfx}"}, {"mcptestKey": f"k2-{sfx}"}]},
             skip_if=co_rec_gate, groups=BULK_BOTH))
    add(step("custom_add_custom_object_type_fields",
             {"api_name": CO_TYPE,
              "fields": [{"name": "mcptestTmp", "displayName": "MCPTEST Tmp",
                          "dataType": "string"}]},
             skip_if=co_gate, notes="creates a draft so deleteField has a target"))
    add(step("custom_delete_custom_object_type_fields",
             {"api_name": CO_TYPE, "field_names": ["mcptestTmp"]},
             skip_if=co_gate, skip_errors="co-delete-field-rejected"))
    add(step("custom_discard_custom_object_type_draft", {"api_name": CO_TYPE},
             skip_if=co_gate, skip_errors="no-co-draft"))

    # ------------------------------------------------------------------ O. named accounts / ABM
    add(step("custom_describe_named_accounts",
             skip_on=[("abm", "abm-not-enabled")], after=_flag_skip("no_abm")))
    abm_gate = _group_gate("no_abm", "ABM not enabled on this subscription")
    add(step("custom_get_named_account_fields", {"batch_size": 5}, skip_if=abm_gate))
    add(step("custom_get_named_account_field_by_name", {"field_api_name": "name"},
             skip_if=abm_gate))
    add(step("custom_sync_named_accounts",
             {"records": [{"name": name("NA"), "domainName": "mcptest.invalid"}]},
             skip_if=abm_gate,
             save=_save_key("na_guid", "result", 0, "marketoGUID")))
    add(step("custom_query_named_accounts",
             {"filter_type": "name", "filter_values": name("NA"), "fields": "name,marketoGUID"},
             skip_if=abm_gate))
    add(step("custom_sync_named_account_lists",
             {"records": [{"name": name("NAL")}], "action": "createOnly"}, skip_if=abm_gate,
             save=_save_key("nal_id", "result", 0, "marketoGUID")))
    add(step("custom_query_named_account_lists",
             {"filter_type": "dedupeFields", "filter_values": name("NAL")}, skip_if=abm_gate))
    add(step("custom_add_named_account_list_members",
             lambda c: {"list_id": str(c["nal_id"]), "account_ids": [c["na_guid"]]},
             skip_if=_need("nal_id", "na_guid")))
    add(step("custom_get_named_account_list_members",
             lambda c: {"list_id": str(c["nal_id"])}, skip_if=_need("nal_id")))
    add(step("custom_remove_named_account_list_members",
             lambda c: {"list_id": str(c["nal_id"]), "account_ids": [c["na_guid"]]},
             skip_if=_need("nal_id", "na_guid")))
    add(step("custom_delete_named_account_lists",
             lambda c: {"records": [{"id": c["nal_id"]}], "delete_by": "idField"},
             skip_if=_need("nal_id")))
    add(step("custom_delete_named_accounts",
             lambda c: {"records": [{"id": c["na_guid"]}], "delete_by": "idField"},
             skip_if=_need("na_guid")))

    # ------------------------------------------------------------------ P. bulk leads / activities / program members
    add(step("custom_import_leads_csv",
             {"csv_content": f"email,firstName,lastName\n{email(5)},MCP,ImportFive\n"
                             f"{email(6)},MCP,ImportSix\n"},
             save=_save_key("lead_batch", "result", 0, "batchId"),
             groups=(BULK_IMPORT,), notes="tiny import: 2 CSV rows"))
    add(step("get_import_status", lambda c: {"batchId": c["lead_batch"]},
             skip_if=_need("lead_batch"), native=True,
             poll={"done": _job_done,
                   "flag": "lead_import_done"},
             groups=(BULK_IMPORT,)))
    add(step("custom_get_lead_import_failures", lambda c: {"batch_id": c["lead_batch"]},
             skip_if=_need("lead_batch"), groups=(BULK_IMPORT,)))
    add(step("custom_get_lead_import_warnings", lambda c: {"batch_id": c["lead_batch"]},
             skip_if=_need("lead_batch"), groups=(BULK_IMPORT,)))
    add(step("get_leads_by_filter",
             {"filterType": "email", "filterValues": [email(5), email(6)],
              "properties": ["id", "email"]},
             native=True,
             save=lambda c, d: c.__setitem__("imported_lead_ids",
                                             [r["id"] for r in _rows(d)]),
             groups=(BULK_IMPORT,),
             notes="resolve imported lead ids for cleanup"))
    add(step("custom_list_lead_export_jobs", {"batch_size": 10},
             groups=(BULK_EXPORT,)))
    add(step("bulk_export_create",
             lambda c: {"fields": ["email", "firstName"],
                        "startAt": _iso(now - timedelta(minutes=2)),
                        "endAt": _iso(datetime.now(timezone.utc))},
             native=True,
             save=lambda c, d: c.__setitem__("lead_export", _rows(d)[0]["exportId"]),
             groups=(BULK_EXPORT,),
             notes="created (not enqueued) purely so the custom cancel tool has a "
                   "target; minutes-wide window around this run's leads keeps it tiny"))
    add(step("custom_cancel_lead_export_job", lambda c: {"export_id": c["lead_export"]},
             skip_if=_need("lead_export"), groups=(BULK_EXPORT,)))

    # Discover a tiny set of activity type ids to scope the export to. Without
    # this, the createdAt window alone could still match a large volume of
    # activity on a busy instance; pinning activity_type_ids caps the export at
    # a handful of rows regardless of instance traffic. Prefer the custom
    # activity type this run generates (set in section L when running `full`);
    # always add a couple of common standard types (Visit Webpage / Fill Out
    # Form / Click Email) so the scope holds in `--group bulk-export` too.
    def save_act_type_ids(ctx, data):
        # get_activity_types (native) may answer a bare list or a {'result': []}
        # envelope; _rows handles both.
        rows = _rows(data)
        wanted = {"visit webpage", "fill out form", "click email"}
        ids = [t["id"] for t in rows
               if str(t.get("name", "")).strip().lower() in wanted]
        if ctx.get("act_type_id"):
            ids.append(ctx["act_type_id"])
        # Fall back to the first activity type if none of the common ones exist,
        # so the export is still scoped (never an unscoped full-window pull).
        if not ids and rows:
            ids = [rows[0]["id"]]
        ctx["act_export_type_ids"] = ids

    add(step("get_activity_types", native=True, save=save_act_type_ids,
             groups=(BULK_EXPORT,),
             notes="discover activity_type_ids to cap the activity export"))

    def activity_export_args(c):
        # createdAt window of a few minutes around this run's activities, AND
        # scoped to a handful of activity type ids — the type scope is the hard
        # cap that keeps this job tiny no matter how busy the instance is.
        args = {"start_at": _iso(now - timedelta(minutes=2)),
                "end_at": _iso(datetime.now(timezone.utc))}
        if c.get("act_export_type_ids"):
            args["activity_type_ids"] = c["act_export_type_ids"]
        return args

    add(step("custom_create_activity_export_job", activity_export_args,
             save=_save_key("act_export", "result", 0, "exportId"),
             groups=(BULK_EXPORT,),
             notes="tiny job: createdAt window of a few minutes AND scoped to a "
                   "handful of activity_type_ids (caps it regardless of traffic)"))
    add(step("custom_enqueue_activity_export_job", lambda c: {"export_id": c["act_export"]},
             skip_if=_need("act_export"), groups=(BULK_EXPORT,)))
    add(step("custom_get_activity_export_job_status",
             lambda c: {"export_id": c["act_export"]}, skip_if=_need("act_export"),
             poll={"done": _job_done,
                   "flag": "act_export_done"},
             groups=(BULK_EXPORT,)))
    add(step("custom_get_activity_export_file", lambda c: {"export_id": c["act_export"]},
             skip_if=lambda c: (None if (c.get("act_export") and c.get("act_export_done"))
                                else "export job still pending after poll window"),
             groups=(BULK_EXPORT,)))
    add(step("custom_create_activity_export_job", activity_export_args,
             save=_save_key("act_export2", "result", 0, "exportId"),
             groups=(BULK_EXPORT,),
             notes="second tiny job (same activity_type_ids scope), created only "
                   "to exercise cancel"))
    add(step("custom_cancel_activity_export_job", lambda c: {"export_id": c["act_export2"]},
             skip_if=_need("act_export2"), groups=(BULK_EXPORT,)))
    add(step("custom_list_activity_export_jobs", {"batch_size": 10},
             groups=(BULK_EXPORT,)))

    def save_pm_fields(ctx, data):
        names = [f.get("name") for f in _rows(data)]
        preferred = [n for n in ("leadId", "program", "programId", "statusName",
                                 "reachedSuccess") if n in names]
        ctx["pm_export_fields"] = preferred[:2] if len(preferred) >= 2 else ["leadId", "program"]

    add(step("get_program_member_fields", {"maxReturn": 200}, native=True,
             save=save_pm_fields, groups=(BULK_EXPORT,)))
    add(step("custom_create_program_member_export_job",
             lambda c: {"fields": c.get("pm_export_fields", ["leadId", "program"]),
                        "program_id": c["program_id"]},
             save=_save_key("pm_export", "result", 0, "exportId"),
             groups=(BULK_EXPORT,),
             notes="tiny job: filtered to the suite's own program"))
    add(step("custom_enqueue_program_member_export_job",
             lambda c: {"export_id": c["pm_export"]}, skip_if=_need("pm_export"),
             groups=(BULK_EXPORT,)))
    add(step("custom_get_program_member_export_job_status",
             lambda c: {"export_id": c["pm_export"]}, skip_if=_need("pm_export"),
             poll={"done": _job_done,
                   "flag": "pm_export_done"},
             groups=(BULK_EXPORT,)))
    add(step("custom_get_program_member_export_file",
             lambda c: {"export_id": c["pm_export"]},
             skip_if=lambda c: (None if (c.get("pm_export") and c.get("pm_export_done"))
                                else "export job still pending after poll window"),
             groups=(BULK_EXPORT,)))
    add(step("custom_create_program_member_export_job",
             lambda c: {"fields": c.get("pm_export_fields", ["leadId", "program"]),
                        "program_id": c["program_id"]},
             save=_save_key("pm_export2", "result", 0, "exportId"),
             groups=(BULK_EXPORT,),
             notes="second job, created only to exercise cancel"))
    add(step("custom_cancel_program_member_export_job",
             lambda c: {"export_id": c["pm_export2"]}, skip_if=_need("pm_export2"),
             groups=(BULK_EXPORT,)))
    add(step("custom_list_program_member_export_jobs", {"batch_size": 10},
             groups=(BULK_EXPORT,)))
    add(step("custom_import_program_members_csv",
             lambda c: {"program_id": c["program_id"],
                        "program_member_status": c["statuses"][0],
                        "csv_content": f"email\n{email(7)}\n"},
             save=_save_key("pm_batch", "result", 0, "batchId"),
             groups=(BULK_IMPORT,), notes="tiny import: 1 CSV row"))
    add(step("custom_get_program_member_import_status",
             lambda c: {"batch_id": c["pm_batch"]}, skip_if=_need("pm_batch"),
             poll={"done": _job_done,
                   "flag": "pm_import_done"},
             groups=(BULK_IMPORT,)))
    add(step("custom_get_program_member_import_failures",
             lambda c: {"batch_id": c["pm_batch"]}, skip_if=_need("pm_batch"),
             groups=(BULK_IMPORT,)))
    add(step("custom_get_program_member_import_warnings",
             lambda c: {"batch_id": c["pm_batch"]}, skip_if=_need("pm_batch"),
             groups=(BULK_IMPORT,)))
    add(step("get_leads_by_filter",
             {"filterType": "email", "filterValues": [email(7)], "properties": ["id", "email"]},
             native=True,
             save=lambda c, d: c.__setitem__("pm_lead_ids",
                                             [r["id"] for r in _rows(d)]),
             groups=(BULK_IMPORT,),
             notes="resolve PM-imported lead id for cleanup"))

    # ------------------------------------------------------------------ Q. stats
    add(step("custom_get_daily_usage"))
    add(step("custom_get_weekly_usage"))
    add(step("custom_get_daily_errors"))
    add(step("custom_get_weekly_errors"))

    # ------------------------------------------------------------------ R. user management + Asset v2 (Emails 2.0)
    add(step("custom_list_workspaces", after=_flag_skip("no_user_mgmt"),
             save=lambda c, d: c.__setitem__("workspace_id",
                                             (d.get("result") or [{}])[0].get("id", 1))))
    um_gate = _group_gate("no_user_mgmt",
                          "user-management permission missing (603) on API role")
    add(step("custom_list_users", {"page_size": 5}, skip_if=um_gate,
             save=lambda c, d: c.__setitem__("first_user_id",
                                             (d.get("result") or [{}])[0].get("userid"))))
    add(step("custom_get_user_by_id", lambda c: {"user_id": c["first_user_id"]},
             skip_if=um_gate))
    add(step("custom_list_user_roles", skip_if=um_gate,
             save=lambda c, d: c.__setitem__("role_id",
                                             (d.get("result") or [{}])[0].get("id"))))
    add(step("custom_get_user_roles", lambda c: {"user_id": c["first_user_id"]},
             skip_if=um_gate))
    invite_email = "tyron.pretorius+mcptestinvite@knak.com"
    add(step("custom_invite_user",
             lambda c: {"email_address": invite_email, "first_name": "MCP",
                        "last_name": "TestInvite", "api_only": True,
                        "expires_at": _iso(now + timedelta(days=1)),
                        "reason": "MCPTEST suite",
                        "user_role_workspaces": [{"accessRoleId": c["role_id"],
                                                  "workspaceId": c["workspace_id"]}]},
             skip_if=um_gate,
             after=lambda c, s, d: c.__setitem__("invited", s == PASS)))
    add(step("custom_get_user_invite", {"user_id": invite_email},
             skip_if=lambda c: None if c.get("invited") else "invite was not created"))
    add(step("custom_update_user",
             {"user_id": invite_email, "last_name": "TestInviteUpdated"},
             skip_if=lambda c: None if c.get("invited") else
             "safety: only the suite-invited user may be updated",
             skip_errors="pending-user-not-updatable"))
    add(step("custom_add_user_roles",
             lambda c: {"user_id": invite_email,
                        "role_workspaces": [{"accessRoleId": c["role_id"],
                                             "workspaceId": c["workspace_id"]}]},
             skip_if=lambda c: None if c.get("invited") else
             "safety: only the suite-invited user may be modified",
             skip_errors="pending-user-roles-unmodifiable"))
    add(step("custom_remove_user_roles",
             lambda c: {"user_id": invite_email,
                        "role_workspaces": [{"accessRoleId": c["role_id"],
                                             "workspaceId": c["workspace_id"]}]},
             skip_if=lambda c: None if c.get("invited") else
             "safety: only the suite-invited user may be modified",
             skip_errors="pending-user-roles-unmodifiable"))
    add(step("custom_delete_user_invite", {"user_id": invite_email},
             skip_if=lambda c: None if c.get("invited") else "invite was not created"))
    add(step("custom_delete_user", {"user_id": invite_email},
             skip_if=lambda c: None if c.get("invited") else
             "safety: only the suite-invited user may be deleted",
             skip_errors="invited-user-not-deletable"))

    add(step("custom_browse_email_templates2",
             lambda c: {"workspace_id": c.get("workspace_id", 1)},
             skip_on=[("704", "v2-unavailable: x-app-type header required"),
                      ("non-json", "v2-unavailable")],
             after=_flag_skip("no_v2")))
    v2_gate = _group_gate(
        "no_v2", "Asset v2 unavailable (704 x-app-type header / Emails 2.0 not enabled)")
    for tool, args in [
        ("custom_get_email2_by_id", lambda c: {"email_id": c["email_id"]}),
        ("custom_create_email2",
         lambda c: {"name": name("EMAIL2"), "app_data": {"folderId": c["ds_emails"]},
                    "headers": {"subject": "MCPTEST", "fromName": "MCPTEST",
                                "fromEmail": SAMPLE_EMAIL_TO, "replyTo": SAMPLE_EMAIL_TO}}),
        ("custom_update_email2",
         lambda c: {"email_id": c["email2_id"], "description": "MCPTEST"}),
        ("custom_clone_email2",
         lambda c: {"email_id": c["email2_id"], "name": name("EMAIL2_CLONE"),
                    "folder_id": c["ds_emails"]}),
        ("custom_transition_email2_state",
         lambda c: {"email_id": c["email2_id"], "action": "approve"}),
        ("custom_get_email2_used_by", lambda c: {"email_id": c["email2_id"]}),
        ("custom_delete_email2", lambda c: {"email_id": c["email2_id"]}),
        ("custom_get_email_template2_by_id", lambda c: {"template_id": c["tpl_id"]}),
        ("custom_create_email_template2",
         lambda c: {"name": name("TPL2"), "app_data": {"folderId": c["ds_etpl"]}}),
        ("custom_update_email_template2",
         lambda c: {"template_id": c["tpl2_id"], "description": "MCPTEST"}),
        ("custom_clone_email_template2",
         lambda c: {"template_id": c["tpl2_id"], "name": name("TPL2_CLONE"),
                    "folder_id": c["ds_etpl"]}),
        ("custom_transition_email_template2_state",
         lambda c: {"template_id": c["tpl2_id"], "action": "approve"}),
        ("custom_get_email_template2_used_by", lambda c: {"template_id": c["tpl2_id"]}),
        ("custom_delete_email_template2", lambda c: {"template_id": c["tpl2_id"]}),
        ("custom_browse_fragments", lambda c: {"workspace_id": c.get("workspace_id", 1)}),
        ("custom_get_fragment_by_id", lambda c: {"fragment_id": c["fragment_id"]}),
        ("custom_create_fragment",
         lambda c: {"name": name("FRAG"), "app_data": {"folderId": c["ds_emails"]},
                    "settings": {}}),
        ("custom_update_fragment",
         lambda c: {"fragment_id": c["fragment_id"], "description": "MCPTEST"}),
        ("custom_clone_fragment",
         lambda c: {"fragment_id": c["fragment_id"], "name": name("FRAG_CLONE"),
                    "folder_id": c["ds_emails"]}),
        ("custom_transition_fragment_state",
         lambda c: {"fragment_id": c["fragment_id"], "action": "approve"}),
        ("custom_get_fragment_used_by", lambda c: {"fragment_id": c["fragment_id"]}),
        ("custom_delete_fragment", lambda c: {"fragment_id": c["fragment_id"]}),
    ]:
        save = None
        if tool == "custom_create_email2":
            save = _save_key("email2_id", "result", 0, "id")
        elif tool == "custom_create_email_template2":
            save = _save_key("tpl2_id", "result", 0, "id")
        elif tool == "custom_create_fragment":
            save = _save_key("fragment_id", "result", 0, "id")
        add(step(tool, args, skip_if=v2_gate, skip_errors="v2-schema", save=save,
                 notes="pragmatic minimal-body attempt; validation errors recorded as SKIP"))

    # ------------------------------------------------------------------ S. merge + cleanup
    add(step("custom_merge_leads",
             lambda c: {"winning_lead_id": c["lead2"], "losing_lead_ids": [c["lead3"]]},
             after=lambda c, s, d: c.__setitem__("lead3_merged", s == PASS)))

    def delete_leads_args(ctx):
        ids = [ctx.get(k) for k in ("lead1", "lead2", "lead4")]
        if not ctx.get("lead3_merged"):
            ids.append(ctx.get("lead3"))
        ids += ctx.get("imported_lead_ids", []) + ctx.get("pm_lead_ids", [])
        ids = [i for i in ids if i]
        if not ids:
            raise KeyError("lead ids")
        return {"lead_ids": ids}

    add(step("custom_delete_leads", delete_leads_args, groups=BULK_BOTH))
    add(step("custom_get_deleted_leads",
             {"since_datetime": _iso(now - timedelta(hours=1))}))
    add(step("custom_delete_static_list", lambda c: {"list_id": c["list_id"]}))
    add(step("custom_delete_smart_list", lambda c: {"smart_list_id": c["sl_id"]}))
    add(step("custom_delete_smart_campaign", lambda c: {"campaign_id": c["sc_clone_id"]}))
    add(step("custom_delete_smart_campaign", lambda c: {"campaign_id": c["sc_id"]}))
    add(step("custom_delete_program", lambda c: {"program_id": c["program_id"]},
             groups=BULK_BOTH))
    add(step("custom_delete_snippet", lambda c: {"snippet_id": c["snippet_id"]}))
    add(step("custom_delete_form", lambda c: {"form_id": c["form_id"]}))
    add(step("custom_unapprove_email", lambda c: {"email_id": c["email_clone_id"]},
             skip_errors="clone-not-approved", notes="clone may already be a draft"))
    add(step("custom_delete_email", lambda c: {"email_id": c["email_clone_id"]}))
    add(step("custom_delete_email", lambda c: {"email_id": c["email_id"]}))
    add(step("custom_unapprove_email_template", lambda c: {"template_id": c["tpl_id"]}))
    add(step("custom_delete_email_template", lambda c: {"template_id": c["tpl_clone_id"]}))
    add(step("custom_delete_email_template", lambda c: {"template_id": c["tpl_id"]}))
    add(step("custom_delete_landing_page", lambda c: {"landing_page_id": c["lp_clone_id"]}))
    add(step("custom_delete_landing_page", lambda c: {"landing_page_id": c["lp_id"]}))
    add(step("custom_unapprove_landing_page_template", lambda c: {"template_id": c["lpt_id"]},
             skip_errors="lpt-not-approved"))
    add(step("custom_delete_landing_page_template",
             lambda c: {"template_id": c["lpt_clone_id"]}))
    add(step("custom_delete_landing_page_template", lambda c: {"template_id": c["lpt_id"]},
             skip_on=[("used in landing pages",
                       "TOOL-BUG-610-lp-unapprove-endpoint (template still used by the "
                       "undeletable approved LP)")]))
    add(step("custom_delete_custom_activity_type", {"api_name": ACT_TYPE},
             skip_errors="activity-type-in-use",
             notes="types with recent activity records cannot be deleted; reused next run"))
    add(step("custom_delete_custom_object_type", {"api_name": CO_TYPE},
             skip_if=co_gate, skip_errors="co-type-has-records",
             groups=BULK_BOTH,
             notes="record deletion is async; type delete may need a later run"))
    add(step("custom_delete_folder", lambda c: {"folder_id": c["ds_forms"]}))
    add(step("custom_delete_folder", lambda c: {"folder_id": c["ds_emails"]}))
    add(step("custom_delete_folder", lambda c: {"folder_id": c["ds_etpl"]}))
    add(step("custom_delete_folder", lambda c: {"folder_id": c["ds_lp"]},
             skip_on=[("not empty", "TOOL-BUG-610-lp-unapprove-endpoint (folder still "
                                    "holds the undeletable approved LP)")]))
    add(step("custom_delete_folder", lambda c: {"folder_id": c["ds_lpt"]},
             skip_on=[("not empty", "TOOL-BUG-610-lp-unapprove-endpoint (folder still "
                                    "holds the LP template used by the approved LP)")]))
    add(step("custom_delete_folder", lambda c: {"folder_id": c["ds_snip"]}))
    add(step("custom_delete_folder", lambda c: {"folder_id": c["ma_folder"]},
             groups=BULK_BOTH))

    return steps


# ---------------------------------------------------------------------------
# Read-only discovery pass
# ---------------------------------------------------------------------------
#
# A self-contained read pass that creates/updates/deletes NOTHING. It browses
# each asset type via the appropriate browse/native tool, takes the first
# existing result, and exercises the READ custom tools against it. A read step
# whose discovery turned up nothing SKIPs with a reason. Every step here is
# write=False; the runner refuses to execute any write=True step in read-only
# mode, so this pass is structurally incapable of mutating Marketo.

def _disc(key, *path, index=0):
    """save= helper for discovery: stash result[index] (or a nested field).

    With no path: ctx[key] = result[index] (the whole row).
    With a path:  ctx[key] = result[index][path...].
    """
    def _save(ctx, data):
        rows = _rows(data)
        if not rows:
            return
        value = rows[index]
        for part in path:
            value = value[part]
        ctx[key] = value
    return _save


def _have(*keys):
    """skip_if= helper: SKIP when a discovered dependency is absent."""
    def _check(ctx):
        for key in keys:
            if not ctx.get(key) and ctx.get(key) != 0:
                return f"nothing discovered for: {key}"
        return None
    return _check


def _r(tool, args=None, **kw):
    """A read step: forces write=False and defaults skip_errors so a feature/
    permission-gated read records SKIP (not FAIL) in the safe read-only pass."""
    kw.setdefault("write", False)
    kw.setdefault("skip_errors", "read-only probe")
    return step(tool, args, **kw)


def build_readonly_steps():
    """Discovery-driven, mutation-free read pass over every asset type."""
    steps = []
    add = steps.append

    # ---- folders -----------------------------------------------------------
    def save_first_folder(ctx, data):
        rows = _rows(data)
        if rows:
            ctx["ro_folder_id"] = rows[0]["id"]
            ctx["ro_folder_name"] = rows[0].get("name") or rows[0].get("folderName")
    add(_r("browse_folders", {"maxReturn": 50}, native=True, save=save_first_folder))
    add(_r("get_folder_by_id", lambda c: {"id": c["ro_folder_id"]}, native=True,
           skip_if=_have("ro_folder_id")))
    add(_r("get_folder_by_name", lambda c: {"name": c["ro_folder_name"]}, native=True,
           skip_if=_have("ro_folder_name")))
    add(_r("get_folder_content", lambda c: {"id": c["ro_folder_id"]}, native=True,
           skip_if=_have("ro_folder_id")))
    add(_r("get_tokens_by_folder",
           lambda c: {"id": c["ro_folder_id"], "folderType": "Folder"}, native=True,
           skip_if=_have("ro_folder_id")))

    # ---- lists (discovered early; also a source of a real lead id) --------
    def save_lists(ctx, data):
        ctx["ro_list_ids"] = [r["id"] for r in _rows(data)]
    add(_r("browse_lists", {"maxReturn": 30}, native=True, save=save_lists))

    # Native get_list_members on a populated list yields a real lead id without
    # creating anything. Lists can be empty, so walk the first several until one
    # has members; the worked-list id is kept for custom_is_member_of_list.
    def members_args(idx):
        def _build(c):
            ids = c.get("ro_list_ids") or []
            if idx >= len(ids) or c.get("ro_lead_id"):
                raise KeyError("no further list to probe / lead already found")
            return {"listId": ids[idx]}
        return _build

    def save_lead_from_members(idx):
        def _save(ctx, data):
            rows = _rows(data)
            if rows and not ctx.get("ro_lead_id"):
                ctx["ro_lead_id"] = rows[0]["id"]
                ctx["ro_lead_email"] = rows[0].get("email")
                ctx["ro_list_id"] = ctx["ro_list_ids"][idx]
        return _save

    for _i in range(8):
        add(_r("get_list_members", members_args(_i), native=True,
               save=save_lead_from_members(_i),
               notes="walk lists for a real lead id (stops once one is found)"))

    # ---- programs (discovered early; also a backup lead source) ------------
    add(_r("browse_programs", {"maxReturn": 5}, native=True,
           save=_disc("ro_program_id", "id")))
    add(_r("browse_programs", {"maxReturn": 5}, native=True,
           save=_disc("ro_program_name", "name")))

    def save_lead_from_program(ctx, data):
        # Backup: only set a lead id if the list path found none.
        if ctx.get("ro_lead_id"):
            return
        rows = _rows(data)
        if rows:
            ctx["ro_lead_id"] = rows[0]["id"]
            ctx["ro_lead_email"] = rows[0].get("email")
    add(_r("custom_get_leads_by_program",
           lambda c: {"program_id": c["ro_program_id"], "fields": "id,email"},
           skip_if=_have("ro_program_id"), save=save_lead_from_program))
    add(_r("custom_query_program_members",
           lambda c: {"program_id": c["ro_program_id"], "filter_type": "statusName",
                      "filter_values": "member"},
           skip_if=_have("ro_program_id")))

    # ---- leads / lead schema (uses the lead id discovered above) ----------
    add(_r("custom_get_leads_by_filter",
           lambda c: {"filter_type": "email", "filter_values": [c["ro_lead_email"]],
                      "fields": ["id", "email"]},
           skip_if=_have("ro_lead_email")))
    add(_r("custom_get_lead_by_id",
           lambda c: {"lead_id": c["ro_lead_id"], "fields": "id,email"},
           skip_if=_have("ro_lead_id")))
    add(_r("custom_describe_lead2"))
    add(_r("custom_get_lead_fields", {"batch_size": 5}))
    add(_r("custom_get_lead_field_by_name", {"field_api_name": "email"}))
    add(_r("custom_get_lead_partitions"))
    add(_r("custom_get_lead_changes",
           lambda c: {"lead_id": c["ro_lead_id"], "days_back": 1},
           skip_if=_have("ro_lead_id")))
    add(_r("custom_get_lead_activities_by_email",
           lambda c: {"email": c["ro_lead_email"], "days_back": 1},
           skip_if=_have("ro_lead_email")))
    add(_r("custom_get_lead_list_membership",
           lambda c: {"lead_id": c["ro_lead_id"]}, skip_if=_have("ro_lead_id")))
    add(_r("custom_get_lead_program_membership",
           lambda c: {"lead_id": c["ro_lead_id"]}, skip_if=_have("ro_lead_id")))
    add(_r("custom_get_lead_smart_campaign_membership",
           lambda c: {"lead_id": c["ro_lead_id"]}, skip_if=_have("ro_lead_id")))
    add(_r("custom_get_deleted_leads",
           {"since_datetime": _iso(datetime.now(timezone.utc) - timedelta(hours=1))}))

    # ---- smart campaigns ---------------------------------------------------
    add(_r("browse_smart_campaigns", {"maxReturn": 5}, native=True))

    # ---- smart lists -------------------------------------------------------
    add(_r("browse_smart_lists", {"maxReturn": 5}, native=True))

    # ---- snippets ----------------------------------------------------------
    add(_r("browse_snippets", {"maxReturn": 5}, native=True))

    # ---- forms -------------------------------------------------------------
    def save_form(ctx, data):
        rows = _rows(data)
        if rows:
            ctx["ro_form_id"] = rows[0]["id"]
    add(_r("browse_forms", {"maxReturn": 5}, native=True, save=save_form))

    # ---- landing pages -----------------------------------------------------
    def save_lp(ctx, data):
        rows = _rows(data)
        if rows:
            ctx["ro_lp_id"] = rows[0]["id"]
            ctx["ro_lp_name"] = rows[0].get("name")
    add(_r("custom_browse_landing_pages", {"max_return": 5}, save=save_lp))
    add(_r("custom_get_landing_page_by_id",
           lambda c: {"landing_page_id": c["ro_lp_id"]}, skip_if=_have("ro_lp_id")))
    add(_r("custom_get_landing_page_by_name",
           lambda c: {"name": c["ro_lp_name"]}, skip_if=_have("ro_lp_name")))
    add(_r("custom_get_landing_page_content",
           lambda c: {"landing_page_id": c["ro_lp_id"]}, skip_if=_have("ro_lp_id")))
    add(_r("custom_get_landing_page_full_content",
           lambda c: {"landing_page_id": c["ro_lp_id"]}, skip_if=_have("ro_lp_id")))
    add(_r("custom_get_landing_page_variables",
           lambda c: {"landing_page_id": c["ro_lp_id"]}, skip_if=_have("ro_lp_id")))
    add(_r("custom_get_landing_page_domains"))
    add(_r("custom_browse_redirect_rules", {"max_return": 5}))

    # ---- landing page templates -------------------------------------------
    def save_lpt(ctx, data):
        rows = _rows(data)
        if rows:
            ctx["ro_lpt_id"] = rows[0]["id"]
            ctx["ro_lpt_name"] = rows[0].get("name")
    add(_r("custom_browse_landing_page_templates", {"max_return": 5}, save=save_lpt))
    add(_r("custom_get_landing_page_template_by_id",
           lambda c: {"template_id": c["ro_lpt_id"]}, skip_if=_have("ro_lpt_id")))
    add(_r("custom_get_landing_page_template_by_name",
           lambda c: {"name": c["ro_lpt_name"]}, skip_if=_have("ro_lpt_name")))
    add(_r("custom_get_landing_page_template_content",
           lambda c: {"template_id": c["ro_lpt_id"]}, skip_if=_have("ro_lpt_id")))

    # ---- email templates ---------------------------------------------------
    def save_etpl(ctx, data):
        rows = _rows(data)
        if rows:
            ctx["ro_etpl_id"] = rows[0]["id"]
            ctx["ro_etpl_name"] = rows[0].get("name")
    add(_r("custom_browse_email_templates", {"max_return": 5}, save=save_etpl))
    add(_r("custom_get_email_template_by_id",
           lambda c: {"template_id": c["ro_etpl_id"]}, skip_if=_have("ro_etpl_id")))
    add(_r("custom_get_email_template_by_name",
           lambda c: {"name": c["ro_etpl_name"]}, skip_if=_have("ro_etpl_name")))
    add(_r("custom_get_email_template_content",
           lambda c: {"template_id": c["ro_etpl_id"]}, skip_if=_have("ro_etpl_id")))
    add(_r("custom_get_email_template_used_by",
           lambda c: {"template_id": c["ro_etpl_id"]}, skip_if=_have("ro_etpl_id")))

    # ---- emails ------------------------------------------------------------
    def save_email(ctx, data):
        rows = _rows(data)
        if rows:
            ctx["ro_email_id"] = rows[0]["id"]
    add(_r("browse_emails2", {"maxReturn": 5}, native=True, save=save_email))
    add(_r("get_email_content", lambda c: {"id": c["ro_email_id"]}, native=True,
           skip_if=_have("ro_email_id")))
    add(_r("custom_preview_email",
           lambda c: {"email_id": c["ro_email_id"]}, skip_if=_have("ro_email_id")))
    add(_r("custom_get_email_variables",
           lambda c: {"email_id": c["ro_email_id"]}, skip_if=_have("ro_email_id")))
    add(_r("custom_get_email_cc_fields"))

    # ---- list membership (list + lead discovered earlier) -----------------
    add(_r("custom_is_member_of_list",
           lambda c: {"list_id": c["ro_list_id"], "lead_ids": [c["ro_lead_id"]]},
           skip_if=_have("ro_list_id", "ro_lead_id")))

    # ---- files -------------------------------------------------------------
    def save_file(ctx, data):
        rows = _rows(data)
        if rows:
            ctx["ro_file_id"] = rows[0]["id"]
            ctx["ro_file_name"] = rows[0].get("name")
    add(_r("custom_browse_files", {"max_return": 10}, save=save_file))
    add(_r("custom_get_file_by_id",
           lambda c: {"file_id": c["ro_file_id"]}, skip_if=_have("ro_file_id")))
    add(_r("custom_get_file_by_name",
           lambda c: {"name": c["ro_file_name"]}, skip_if=_have("ro_file_name")))

    # ---- segmentations -----------------------------------------------------
    def save_seg(ctx, data):
        for seg in _rows(data):
            if seg.get("status") == "approved":
                ctx["ro_seg_id"] = seg["id"]
                return
        rows = _rows(data)
        if rows:
            ctx["ro_seg_id"] = rows[0]["id"]
    add(_r("custom_browse_segmentations", save=save_seg))
    add(_r("custom_get_segments",
           lambda c: {"segmentation_id": c["ro_seg_id"]}, skip_if=_have("ro_seg_id")))

    # ---- activity / custom-object / CRM schema (pure reads) ----------------
    add(_r("custom_get_custom_activity_types"))
    add(_r("custom_list_custom_object_types"))
    add(_r("custom_get_custom_object_field_types"))
    add(_r("custom_get_custom_object_linkable_objects"))
    add(_r("custom_describe_companies"))
    add(_r("custom_describe_opportunities"))
    add(_r("custom_describe_opportunity_roles"))
    add(_r("custom_describe_sales_persons"))
    add(_r("custom_describe_named_accounts", skip_on=[("abm", "abm-not-enabled")]))

    # ---- bulk job listings + usage stats (read-only) -----------------------
    add(_r("custom_list_lead_export_jobs", {"batch_size": 10}))
    add(_r("custom_list_activity_export_jobs", {"batch_size": 10}))
    add(_r("custom_list_program_member_export_jobs", {"batch_size": 10}))
    add(_r("custom_get_daily_usage"))
    add(_r("custom_get_weekly_usage"))
    add(_r("custom_get_daily_errors"))
    add(_r("custom_get_weekly_errors"))
    add(_r("custom_list_workspaces"))

    return steps


# ---------------------------------------------------------------------------
# Full-mode orchestration
# ---------------------------------------------------------------------------

def _full_headers():
    _load_env_files()
    missing = [k for k in ("MARKETO_CLIENT_ID", "MARKETO_CLIENT_SECRET", "MARKETO_MUNCHKIN_ID")
               if not os.environ.get(k)]
    if missing:
        print(f"Missing credentials ({', '.join(missing)}); set env vars or .env / .env.sandbox.")
        sys.exit(2)
    return {
        "X-Marketo-Client-Id": os.environ["MARKETO_CLIENT_ID"],
        "X-Marketo-Client-Secret": os.environ["MARKETO_CLIENT_SECRET"],
        "X-Marketo-Munchkin-Id": os.environ["MARKETO_MUNCHKIN_ID"],
    }


def _local_custom_tool_names():
    """All custom_* tool names, registered offline (for dry-run coverage)."""
    from fastmcp import FastMCP
    from custom_tools import register_custom_tools
    server = FastMCP("coverage-check")
    register_custom_tools(server)

    async def _list():
        return [t.name for t in await server.list_tools()]

    return sorted(asyncio.run(_list()))


def _coverage_report(steps, custom_tool_names):
    stepped = {s["tool"] for s in steps}
    uncovered = sorted(set(custom_tool_names) - stepped)
    return uncovered


def _print_summary(records, uncovered, elapsed):
    width = max((len(r[0]) for r in records), default=20)
    print("\n" + "=" * (width + 46))
    print(f"{'TOOL':<{width}}  {'KIND':<12} {'STATUS':<6} {'SECS':>6}  REASON")
    print("-" * (width + 46))
    for tool, kind, status, reason, secs in records:
        print(f"{tool:<{width}}  {kind:<12} {status:<6} {secs:>6.1f}  {reason[:100]}")
    counts = {PASS: 0, FAIL: 0, SKIP: 0}
    for _, _, status, _, _ in records:
        counts[status] += 1
    print("-" * (width + 46))
    print(f"TOTALS: {counts[PASS]} PASS, {counts[FAIL]} FAIL, {counts[SKIP]} SKIP, "
          f"{len(uncovered)} UNCOVERED  |  steps: {len(records)}  |  "
          f"wall clock: {elapsed/60:.1f} min")

    fails = [(t, r) for t, _, s, r, _ in records if s == FAIL]
    if fails:
        print("\nFAILURES:")
        for tool, reason in fails:
            print(f"  FAIL {tool}: {reason}")
    if uncovered:
        print("\nUNCOVERED custom tools (never stepped):")
        for tool in uncovered:
            print(f"  {tool}")
    skips = {}
    for tool, _, status, reason, _ in records:
        if status == SKIP:
            key = reason.split(":")[0]
            skips.setdefault(key, []).append(tool)
    if skips:
        print("\nSKIPS grouped by reason:")
        for key in sorted(skips):
            print(f"  [{key}] ({len(skips[key])}): {', '.join(skips[key])}")
    return counts


def _start_blended_server():
    env = {**os.environ, "PORT": str(FULL_PORT)}
    proc = subprocess.Popen(
        [sys.executable, "mcp_server_blended.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc


async def _wait_for_server(headers, timeout=30):
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            async with Client(StreamableHttpTransport(FULL_URL, headers=headers)) as client:
                await client.list_tools()
            return
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"blended server did not become ready: {last_exc}")


async def _run_full_suite(headers, steps, read_only=False):
    runner = FullSuiteRunner(FULL_URL, headers)
    await runner.connect()
    try:
        tool_names = await runner.list_tool_names()
        custom_names = sorted(t for t in tool_names if t.startswith("custom_"))
        native_count = len(tool_names) - len(custom_names)
        print(f"Connected: {native_count} native + {len(custom_names)} custom tools listed.")
        if native_count == 0:
            print("FATAL: no native tools listed — Munchkin ID not allowlisted for "
                  "Adobe's native MCP? The full suite needs native infrastructure tools.")
            return None, custom_names
        if read_only:
            # Hard guard: the read-only pass must never run a mutating step.
            offenders = [s["tool"] for s in steps if s["write"]]
            if offenders:
                raise AssertionError(
                    f"read-only run contains write steps: {offenders}")
        ctx = {}
        for st in steps:
            try:
                await runner.run_step(st, ctx)
            except Exception as exc:  # never let one step abort the suite
                runner.records.append((st["tool"], "CUSTOM", FAIL,
                                       f"engine error: {type(exc).__name__}: {exc}", 0.0))
                print(f"F [{len(runner.records):3d}] ENGINE       {st['tool']} FAIL ({exc})",
                      flush=True)
        return runner.records, custom_names
    finally:
        await runner.close()


def _plan_steps(mode, sfx, group=None):
    """Assemble the step list for a run mode.

    mode 'readonly' -> discovery read pass only (zero mutations).
    mode 'write'    -> the create/update/delete lifecycle (existing full suite).
    mode 'full'     -> read pass + write lifecycle (coverage asserted on union).
    A group filter (only meaningful for write/full) narrows to bulk steps.
    """
    readonly = build_readonly_steps()
    lifecycle = build_full_steps(sfx)
    if mode == "readonly":
        steps = readonly
    elif mode == "write":
        steps = lifecycle
    else:  # full
        steps = readonly + lifecycle
    if group:
        # Groups only apply to the write lifecycle's tagged bulk steps.
        steps = [s for s in steps if group in s["groups"]]
        print(f"Group '{group}': {len(steps)} steps selected "
              f"(bulk steps + minimal prerequisites/cleanup)")
    return steps


def run_full_mode(dry_run=False, suffix=None, group=None, mode="full"):
    sfx = suffix or datetime.now().strftime("%m%d%H%M%S")
    steps = _plan_steps(mode, sfx, group)
    read_only = mode == "readonly"

    custom_names = _local_custom_tool_names()
    # Full custom-tool coverage is only asserted for the run-everything FULL
    # mode (read pass ∪ write lifecycle). Read-only / write-only / group runs
    # intentionally cover a subset.
    enforce_coverage = mode == "full" and not group
    uncovered = _coverage_report(steps, custom_names) if enforce_coverage else []

    if dry_run:
        print(f"DRY RUN — mode={mode} — {len(steps)} planned steps "
              f"(run suffix {sfx}):\n")
        for i, st in enumerate(steps, 1):
            kind = "NATIVE-SMOKE" if st["smoke"] else ("NATIVE" if st["native"] else "CUSTOM")
            rw = "W" if st["write"] else "R"
            note = f"  -- {st['notes']}" if st["notes"] else ""
            print(f"[{i:3d}] {rw} {kind:<12} {st['tool']}{note}")
        if read_only:
            offenders = [s["tool"] for s in steps if s["write"]]
            print(f"\nRead-only plan: {len(steps)} steps, "
                  f"{len(offenders)} write steps (must be 0).")
            sys.exit(0 if not offenders else 1)
        if not enforce_coverage:
            print(f"\nmode={mode}{' group=' + group if group else ''}: "
                  f"{len(steps)} steps (full coverage check skipped)")
            sys.exit(0)
        custom_stepped = {s["tool"] for s in steps if not (s["native"] or s["smoke"])}
        print(f"\nCustom tools registered: {len(custom_names)}; "
              f"custom tools stepped: {len(custom_stepped & set(custom_names))}; "
              f"UNCOVERED: {len(uncovered)}")
        for tool in uncovered:
            print(f"  UNCOVERED {tool}")
        sys.exit(0 if not uncovered else 1)

    headers = _full_headers()
    print(f"Mode: {mode}  |  Run suffix: {sfx}  |  {len(steps)} steps planned")
    started = time.time()
    proc = _start_blended_server()
    try:
        asyncio.run(_wait_for_server(headers))
        records, server_custom = asyncio.run(
            _run_full_suite(headers, steps, read_only=read_only))
        if records is None:
            sys.exit(2)
        # Coverage is asserted against the *live* server's tool list
        # (only in the run-everything FULL mode).
        uncovered = _coverage_report(steps, server_custom) if enforce_coverage else []
        counts = _print_summary(records, uncovered, time.time() - started)
        sys.exit(0 if counts[FAIL] == 0 and not uncovered else 1)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _prompt_full_options(allow_group=True):
    """Interactively collect the full-suite options (all optional)."""
    dry = input("Dry run — print the planned steps without calling Marketo? (y/N): "
                ).strip().lower() in ("y", "yes")
    sfx = input("Run suffix (Enter for an auto timestamp): ").strip() or None
    if not allow_group:
        return dry, sfx, None
    print("\nAvailable groups (Enter to run everything and assert full coverage):")
    for g in AVAILABLE_GROUPS:
        print(f"    - {g}")
    grp = input("Group: ").strip() or None
    if grp and grp not in AVAILABLE_GROUPS:
        print(f"Unknown group: {grp!r}. Running the full suite instead.")
        grp = None
    return dry, sfx, grp


def _parse_cli(argv):
    """Parse the optional CLI subcommand. Returns a dict or None (interactive).

    Subcommands (all preserve their historical behavior):
      live
      full     [--dry-run] [--suffix X] [--group bulk-export|bulk-import]
      readonly [--dry-run] [--suffix X]   (discovery read pass; zero mutations)
      write    [--dry-run] [--suffix X] [--group ...]  (create/update/delete)
    """
    if not argv:
        return None
    cmd = argv[0].lower()
    if cmd not in ("live", "full", "readonly", "write"):
        return None
    opts = {"cmd": cmd, "dry_run": False, "suffix": None, "group": None}
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--dry-run":
            opts["dry_run"] = True
        elif arg == "--suffix":
            i += 1
            opts["suffix"] = argv[i]
        elif arg == "--group":
            i += 1
            opts["group"] = argv[i]
        elif arg.startswith("--group="):
            opts["group"] = arg.split("=", 1)[1]
        elif arg.startswith("--suffix="):
            opts["suffix"] = arg.split("=", 1)[1]
        else:
            print(f"Unknown argument: {arg!r}")
            sys.exit(2)
        i += 1
    if opts["group"] and opts["group"] not in AVAILABLE_GROUPS:
        print(f"Unknown group: {opts['group']!r}. Available: {', '.join(AVAILABLE_GROUPS)}")
        sys.exit(2)
    return opts


def _dispatch_cli(opts):
    cmd = opts["cmd"]
    if cmd == "live":
        run_live_mode()
    elif cmd == "full":
        run_full_mode(dry_run=opts["dry_run"], suffix=opts["suffix"],
                      group=opts["group"], mode="full")
    elif cmd == "readonly":
        run_full_mode(dry_run=opts["dry_run"], suffix=opts["suffix"],
                      group=None, mode="readonly")
    elif cmd == "write":
        run_full_mode(dry_run=opts["dry_run"], suffix=opts["suffix"],
                      group=opts["group"], mode="write")


# Maps the interactive menu choices onto the same machinery as the CLI:
#   1 -> readonly   2 -> write   3 -> full
#   4 -> full --group bulk-export   5 -> full --group bulk-import
#   6 -> live
def _run_menu():
    print("=" * 60)
    print("Blended Marketo MCP - Test Suite")
    print("=" * 60)
    print("\nSelect what to run:")
    print("    1. Read-only tests (safe, no modifications)")
    print("    2. Write-only tests (create, clone, update, delete — "
          "temporary test assets, auto-cleaned)")
    print("    3. Full tests (read-only + write operations)")
    print("    4. Bulk-export tests (tiny jobs)")
    print("    5. Bulk-import tests (tiny jobs)")
    print("    6. Live mode (quick single smoke call against a running server)")

    choice = input("\nSelect test mode (1-6): ").strip()

    if choice == "2":
        dry, sfx, _ = _prompt_full_options(allow_group=False)
        run_full_mode(dry_run=dry, suffix=sfx, mode="write")
    elif choice == "3":
        dry, sfx, _ = _prompt_full_options(allow_group=False)
        run_full_mode(dry_run=dry, suffix=sfx, mode="full")
    elif choice == "4":
        run_full_mode(group=BULK_EXPORT, mode="full")
    elif choice == "5":
        run_full_mode(group=BULK_IMPORT, mode="full")
    elif choice == "6":
        run_live_mode()
    else:
        run_full_mode(mode="readonly")


if __name__ == "__main__":
    _cli = _parse_cli(sys.argv[1:])
    if _cli is not None:
        _dispatch_cli(_cli)
    else:
        _run_menu()
