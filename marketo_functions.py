import base64
import mimetypes
import requests
import json
import os
import time
import dotenv
from datetime import datetime, timedelta, timezone

dotenv.load_dotenv()

base_url = os.environ.get('MARKETO_BASE_URL')

# Per-request base URL override. The blended MCP server serves many Marketo
# instances at once (credentials arrive as request headers), so it wraps each
# function call in base_url_override(...). Plain library/legacy use keeps
# reading MARKETO_BASE_URL from the environment.
import contextlib
import contextvars

_base_url_override = contextvars.ContextVar('marketo_base_url_override', default=None)


def _base():
    return _base_url_override.get() or base_url


@contextlib.contextmanager
def base_url_override(url):
    """Temporarily route all marketo_functions calls in this context to url."""
    token_ = _base_url_override.set(url.rstrip('/'))
    try:
        yield
    finally:
        _base_url_override.reset(token_)
client_id = os.environ.get('MARKETO_CLIENT_ID')
client_secret = os.environ.get('MARKETO_CLIENT_SECRET')

_token_cache = {"access_token": None, "expires_at": 0}


# Get an access token (cached, refreshes 60s before expiry)
def getToken():
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    response = requests.get(
        _base() + '/identity/oauth/token',
        params={
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret
        },
        timeout=30
    )
    data = response.json()
    _token_cache["access_token"] = data['access_token']
    _token_cache["expires_at"] = time.time() + data.get('expires_in', 3600) - 60
    return _token_cache["access_token"]


# ============================================================================
# Activity Functions
# ============================================================================

def getActivityTypes(token):
    """Get available activity types from Marketo."""
    url = _base() + '/rest/v1/activities/types.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getPagingToken(token, sinceDate):
    """Get a paging token for activity queries."""
    url = _base() + '/rest/v1/activities/pagingtoken.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'sinceDatetime': sinceDate}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    data = response.json()
    return data['nextPageToken']


def getLeadActivities(token, leadId, activityTypeIds=None, daysBack=7):
    """
    Fetch activities for a lead.

    Args:
        token: Access token
        leadId: Marketo lead ID
        activityTypeIds: List of activity type IDs to filter by
        daysBack: Number of days back to look

    Returns:
        Activity data from Marketo
    """
    sinceDate = (datetime.now(timezone.utc) - timedelta(days=daysBack)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {'Authorization': 'Bearer ' + token}

    nextPageToken = getPagingToken(token, sinceDate)

    if activityTypeIds is None:
        activityTypeIds = [1, 2, 6, 13, 37]

    url = _base() + '/rest/v1/activities.json'
    params = {
        'nextPageToken': nextPageToken,
        'leadIds': str(leadId),
        'activityTypeIds': ','.join(map(str, activityTypeIds))
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLeadChanges(token, leadId, fields=None, daysBack=7):
    """Get data value changes for a lead."""
    sinceDate = (datetime.now(timezone.utc) - timedelta(days=daysBack)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {'Authorization': 'Bearer ' + token}

    nextPageToken = getPagingToken(token, sinceDate)

    params = {
        'nextPageToken': nextPageToken,
        'leadIds': str(leadId)
    }

    if not fields:
        fields = ['email', 'firstName', 'lastName', 'company']
    params['fields'] = ','.join(fields)

    url = _base() + '/rest/v1/activities/leadchanges.json'
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Lead Functions
# ============================================================================

def lookupLead(token, filterType, filterValues, fields=None):
    """
    Look up lead(s) in Marketo.

    Args:
        token: Access token
        filterType: Type of filter (e.g., 'id', 'email')
        filterValues: Value(s) to filter by
        fields: Optional comma-separated string of fields to return

    Returns:
        JSON response with lead data
    """
    url = _base() + '/rest/v1/leads.json'
    headers = {'Authorization': 'Bearer ' + token}

    if fields is None:
        fields = 'id,email,firstName,lastName,createdAt,updatedAt'

    if isinstance(filterValues, list):
        filterValues = ','.join(map(str, filterValues))

    params = {
        'filterType': filterType,
        'filterValues': filterValues,
        'fields': fields
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLeadsByFilter(token, filterType, filterValues, fields=None, batchSize=None,
                     nextPageToken=None):
    """Get leads by filter (email or id), honoring an explicit field list.

    Unlike the native MCP's get_leads_by_filter (which ignores its field
    argument and returns a fixed default set), this passes the requested
    fields straight to the REST `fields` parameter, so only those fields are
    returned. Omit fields to get Marketo's default set.
    """
    url = _base() + '/rest/v1/leads.json'
    headers = {'Authorization': 'Bearer ' + token}

    if isinstance(filterValues, list):
        filterValues = ','.join(map(str, filterValues))

    params = {'filterType': filterType, 'filterValues': filterValues}
    if fields:
        params['fields'] = ','.join(fields) if isinstance(fields, list) else fields
    if batchSize:
        params['batchSize'] = batchSize
    if nextPageToken:
        params['nextPageToken'] = nextPageToken

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def describeLeads(token):
    """Get lead field metadata and schema information."""
    url = _base() + '/rest/v1/leads/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def mergeLeads(token, winningLeadId, losingLeadIds, mergeInCRM=False):
    """
    Merge duplicate lead records into a winning lead.

    Args:
        token: Access token
        winningLeadId: ID of the lead that survives the merge
        losingLeadIds: List of lead IDs to merge into the winning lead
        mergeInCRM: Whether to also merge the leads in the linked CRM

    Returns:
        JSON response from Marketo
    """
    url = _base() + f'/rest/v1/leads/{winningLeadId}/merge.json'
    # Content-Type must be set or Marketo rejects the merge (error 612)
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
    }

    params = {
        'leadIds': ','.join(map(str, losingLeadIds)),
        'mergeInCRM': 'true' if mergeInCRM else 'false'
    }

    response = requests.post(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Email Functions
# ============================================================================

def getEmailById(token, emailId):
    """Get an email asset by its ID."""
    url = _base() + f'/rest/asset/v1/email/{emailId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getEmailByName(token, name, folderId=None):
    """Get an email asset by its name."""
    url = _base() + '/rest/asset/v1/email/byName.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {'name': name}
    if folderId:
        params['folder'] = json.dumps({"id": folderId, "type": "Folder"})

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def browseEmails(token, maxReturn=20, offset=0, status=None, folderId=None,
                 earliestUpdatedAt=None, latestUpdatedAt=None):
    """Browse email assets with optional filtering."""
    url = _base() + '/rest/asset/v1/emails.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {
        'maxReturn': min(maxReturn, 200),
        'offset': offset
    }

    if status:
        params['status'] = status
    if folderId:
        params['folder'] = json.dumps({"id": folderId, "type": "Folder"})
    if earliestUpdatedAt:
        params['earliestUpdatedAt'] = earliestUpdatedAt
    if latestUpdatedAt:
        params['latestUpdatedAt'] = latestUpdatedAt

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailContent(token, emailId, status=None):
    """Get the content sections of an email asset."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/content.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {}
    if status:
        params['status'] = status

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailCcFields(token):
    """Get the set of fields enabled for Email CC."""
    url = _base() + '/rest/asset/v1/email/ccFields.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def previewEmail(token, emailId, status=None, contentType="HTML", leadId=None):
    """Get a live preview of an email."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/fullContent.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {'type': contentType}
    if status:
        params['status'] = status
    if leadId:
        params['leadId'] = leadId

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Channel Functions
# ============================================================================

def getChannels(token, maxReturn=200, offset=0):
    """Get available program channels."""
    url = _base() + '/rest/asset/v1/channels.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {
        'maxReturn': min(maxReturn, 200),
        'offset': offset
    }
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Folder Functions
# ============================================================================

def getFolderByName(token, name):
    """Get a folder by its name."""
    url = _base() + '/rest/asset/v1/folder/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'name': name}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def browseFolders(token, maxReturn=20, offset=0, folderType="Folder"):
    """Browse folders in Marketo."""
    url = _base() + '/rest/asset/v1/folders.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {
        'maxReturn': min(maxReturn, 200),
        'offset': offset,
        'type': folderType
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Smart Campaign Functions
# ============================================================================

def getSmartCampaignById(token, campaignId):
    """Get a smart campaign by its ID."""
    url = _base() + f'/rest/asset/v1/smartCampaign/{campaignId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getSmartCampaignByName(token, name):
    """Get a smart campaign by its name."""
    url = _base() + '/rest/asset/v1/smartCampaign/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'name': name}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def browseSmartCampaigns(token, maxReturn=20, offset=0, isActive=None, folderId=None,
                         earliestUpdatedAt=None, latestUpdatedAt=None):
    """Browse smart campaigns with optional filtering."""
    url = _base() + '/rest/asset/v1/smartCampaigns.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {
        'maxReturn': min(maxReturn, 200),
        'offset': offset
    }

    if isActive is not None:
        params['isActive'] = str(isActive).lower()
    if folderId:
        params['folder'] = json.dumps({"id": folderId, "type": "Folder"})
    if earliestUpdatedAt:
        params['earliestUpdatedAt'] = earliestUpdatedAt
    if latestUpdatedAt:
        params['latestUpdatedAt'] = latestUpdatedAt

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createSmartCampaign(token, name, folderId, description=None):
    """Create a new smart campaign."""
    url = _base() + '/rest/asset/v1/smartCampaigns.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'name': name,
        'folder': json.dumps({"type": "folder", "id": folderId})
    }

    if description:
        data['description'] = description

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateSmartCampaign(token, campaignId, name=None, description=None, folderId=None):
    """Update an existing smart campaign."""
    url = _base() + f'/rest/asset/v1/smartCampaign/{campaignId}.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {}
    if name:
        data['name'] = name
    if description:
        data['description'] = description
    if folderId:
        data['folder'] = json.dumps({"type": "folder", "id": folderId})

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def cloneSmartCampaign(token, campaignId, name, folderId, description=None, folderType="folder"):
    """Clone an existing smart campaign."""
    url = _base() + f'/rest/asset/v1/smartCampaign/{campaignId}/clone.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'name': name,
        'folder': json.dumps({"type": folderType, "id": folderId})
    }

    if description:
        data['description'] = description

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def scheduleBatchCampaign(token, campaignId, runAt=None, tokens=None, cloneToProgram=None):
    """Schedule a batch smart campaign."""
    url = _base() + f'/rest/v1/campaigns/{campaignId}/schedule.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
    }

    body = {"input": {}}
    if runAt:
        body["input"]["runAt"] = runAt
    if tokens:
        body["input"]["tokens"] = tokens
    if cloneToProgram:
        body["input"]["cloneToProgram"] = cloneToProgram

    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def requestCampaign(token, campaignId, leadIds, tokens=None):
    """Request a smart campaign for specific leads."""
    url = _base() + f'/rest/v1/campaigns/{campaignId}/trigger.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/json'
    }

    body = {
        "input": {
            "leads": [{"id": leadId} for leadId in leadIds[:100]]
        }
    }

    if tokens:
        body["input"]["tokens"] = tokens[:100]

    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def activateSmartCampaign(token, campaignId):
    """Activate a smart campaign."""
    url = _base() + f'/rest/asset/v1/smartCampaign/{campaignId}/activate.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deactivateSmartCampaign(token, campaignId):
    """Deactivate a smart campaign."""
    url = _base() + f'/rest/asset/v1/smartCampaign/{campaignId}/deactivate.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteSmartCampaign(token, campaignId):
    """Delete a smart campaign."""
    url = _base() + f'/rest/asset/v1/smartCampaign/{campaignId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Program Functions
# ============================================================================

def getProgramById(token, programId):
    """Get a program by its ID."""
    url = _base() + f'/rest/asset/v1/program/{programId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getProgramByName(token, name, includeTags=False, includeCosts=False):
    """Get a program by its name."""
    url = _base() + '/rest/asset/v1/program/byName.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {'name': name}
    if includeTags:
        params['includeTags'] = 'true'
    if includeCosts:
        params['includeCosts'] = 'true'

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def browsePrograms(token, maxReturn=20, offset=0, status=None,
                   earliestUpdatedAt=None, latestUpdatedAt=None):
    """Browse programs with optional filtering."""
    url = _base() + '/rest/asset/v1/programs.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {
        'maxReturn': min(maxReturn, 200),
        'offset': offset
    }

    if status:
        params['status'] = status
    if earliestUpdatedAt:
        params['earliestUpdatedAt'] = earliestUpdatedAt
    if latestUpdatedAt:
        params['latestUpdatedAt'] = latestUpdatedAt

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createProgram(token, name, folderId, programType, channel, description=None,
                  costs=None, tags=None, startDate=None, endDate=None):
    """Create a new program."""
    url = _base() + '/rest/asset/v1/programs.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": "Folder"}),
        'type': programType,
        'channel': channel
    }

    if description:
        data['description'] = description
    if costs:
        data['costs'] = json.dumps(costs)
    if tags:
        data['tags'] = json.dumps(tags)
    if startDate:
        data['startDate'] = startDate
    if endDate:
        data['endDate'] = endDate

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateProgram(token, programId, name=None, description=None, costs=None,
                  costsDestructiveUpdate=False, tags=None, startDate=None, endDate=None):
    """Update an existing program."""
    url = _base() + f'/rest/asset/v1/program/{programId}.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {}
    if name:
        data['name'] = name
    if description:
        data['description'] = description
    if costs is not None:
        data['costs'] = json.dumps(costs)
    if costsDestructiveUpdate:
        data['costsDestructiveUpdate'] = 'true'
    if tags:
        data['tags'] = json.dumps(tags)
    if startDate:
        data['startDate'] = startDate
    if endDate:
        data['endDate'] = endDate

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def cloneProgram(token, programId, name, folderId, description=None):
    """Clone an existing program."""
    url = _base() + f'/rest/asset/v1/program/{programId}/clone.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": "Folder"})
    }

    if description:
        data['description'] = description

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def approveEmailProgram(token, programId):
    """Approve an Email Program."""
    url = _base() + f'/rest/asset/v1/program/{programId}/approve.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def unapproveEmailProgram(token, programId):
    """Unapprove an Email Program."""
    url = _base() + f'/rest/asset/v1/program/{programId}/unapprove.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteProgram(token, programId):
    """Delete a program and all its child contents."""
    url = _base() + f'/rest/asset/v1/program/{programId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Program Member Functions
# ============================================================================

def describeProgramMembers(token):
    """Get program member field metadata and schema information."""
    url = _base() + '/rest/v1/programs/members/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def queryProgramMembers(token, programId, filterType, filterValues, fields=None,
                        startAt=None, endAt=None):
    """Query program members with filtering."""
    url = _base() + f'/rest/v1/programs/{programId}/members.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {
        'filterType': filterType,
        'filterValues': filterValues
    }

    if fields:
        params['fields'] = fields
    if startAt:
        params['startAt'] = startAt
    if endAt:
        params['endAt'] = endAt

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Token Management Functions
# ============================================================================

def getTokensByFolder(token, folderId, folderType="Folder"):
    """Get tokens by folder ID."""
    url = _base() + f'/rest/asset/v1/folder/{folderId}/tokens.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'folderType': folderType}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createToken(token, folderId, name, tokenType, value, folderType="Folder"):
    """Create a new token."""
    url = _base() + f'/rest/asset/v1/folder/{folderId}/tokens.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'name': name,
        'type': tokenType,
        'value': value,
        'folderType': folderType
    }

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateToken(token, folderId, name, tokenType, value, folderType="Folder"):
    """Update an existing token (uses the same endpoint as create)."""
    url = _base() + f'/rest/asset/v1/folder/{folderId}/tokens.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'name': name,
        'type': tokenType,
        'value': value,
        'folderType': folderType
    }

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteToken(token, folderId, name, tokenType, folderType="Folder"):
    """Delete a token from a folder or program."""
    url = _base() + f'/rest/asset/v1/folder/{folderId}/tokens/delete.json'
    headers = {
        'Authorization': 'Bearer ' + token,
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'name': name,
        'type': tokenType,
        'folderType': folderType
    }

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


# ============================================================================
# Leads (extended)
# ============================================================================

def syncLeads(token, leads, action="createOrUpdate", lookupField="email",
              asyncProcessing=False, partitionName=None):
    """Create and/or update leads. action is one of createOnly, updateOnly,
    createOrUpdate, or createDuplicate (intentionally create a duplicate
    record, e.g. to test merging). Max 300 leads per call."""
    if len(leads) > 300:
        return {"error": f"Marketo allows at most 300 leads per sync call (got {len(leads)})."}
    url = _base() + '/rest/v1/leads.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    body = {
        'action': action,
        'lookupField': lookupField,
        'input': leads,
    }
    if asyncProcessing:
        body['asyncProcessing'] = True
    if partitionName:
        body['partitionName'] = partitionName

    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getLeadById(token, leadId, fields=None):
    """Get a single lead by its Marketo lead ID."""
    url = _base() + f'/rest/v1/lead/{leadId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {}
    if fields:
        params['fields'] = fields
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def deleteLeads(token, leadIds):
    """Delete leads by ID. Max 300 lead IDs per call."""
    if len(leadIds) > 300:
        return {"error": f"Marketo allows at most 300 leads per delete call (got {len(leadIds)})."}
    url = _base() + '/rest/v1/leads/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": [{"id": leadId} for leadId in leadIds]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeLead2(token):
    """Describe the lead object using the newer describe2 endpoint (includes searchableFields)."""
    url = _base() + '/rest/v1/leads/describe2.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getLeadPartitions(token):
    """List all lead partitions in the instance."""
    url = _base() + '/rest/v1/leads/partitions.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def updateLeadPartitions(token, assignments):
    """Move leads between partitions. assignments is a list of {id, partitionName} dicts."""
    url = _base() + '/rest/v1/leads/partitions.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": assignments}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getLeadsByProgram(token, programId, fields=None, batchSize=None, nextPageToken=None):
    """Get leads that are members of a program, including their program membership status."""
    url = _base() + f'/rest/v1/leads/programs/{programId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'fields': fields, 'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def changeLeadProgramStatus(token, programId, leadIds, status):
    """Change the program status of leads in a program (adds them as members if not already)."""
    url = _base() + f'/rest/v1/leads/programs/{programId}/status.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"status": status, "input": [{"id": leadId} for leadId in leadIds]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def pushLeads(token, leads, lookupField=None, partitionName=None, programName=None,
              programStatus=None, reason=None, source=None):
    """Upsert leads and fire the "Lead is Pushed to Marketo" trigger. Max 300 leads per call."""
    if len(leads) > 300:
        return {"error": f"Marketo allows at most 300 leads per push call (got {len(leads)})."}
    url = _base() + '/rest/v1/leads/push.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {
        "input": leads,
        "lookupField": lookupField,
        "partitionName": partitionName,
        "programName": programName,
        "programStatus": programStatus,
        "reason": reason,
        "source": source,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def submitForm(token, formId, leadFormFields, visitorData=None, cookie=None, programId=None):
    """Submit a Marketo form programmatically for exactly one lead record."""
    url = _base() + '/rest/v1/leads/submitForm.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    record = {
        "leadFormFields": leadFormFields,
        "visitorData": visitorData,
        "cookie": cookie,
    }
    record = {k: v for k, v in record.items() if v is not None}
    body = {"formId": formId, "input": [record]}
    if programId is not None:
        body["programId"] = programId
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def associateLead(token, leadId, cookie):
    """Associate a Munchkin web cookie (the _mch-... value) with a known lead."""
    url = _base() + f'/rest/v1/leads/{leadId}/associate.json'
    # Empty-body Lead DB POST still needs a JSON content type (error 612 otherwise)
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    params = {'cookie': cookie}
    response = requests.post(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLeadListMembership(token, leadId, batchSize=None, nextPageToken=None):
    """List the static lists a lead is a member of."""
    url = _base() + f'/rest/v1/leads/{leadId}/listMembership.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLeadProgramMembership(token, leadId, filterType=None, filterValues=None,
                             earliestUpdatedAt=None, latestUpdatedAt=None,
                             batchSize=None, nextPageToken=None):
    """List the programs a lead is a member of, with optional filters."""
    url = _base() + f'/rest/v1/leads/{leadId}/programMembership.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {
        'filterType': filterType,
        'filterValues': filterValues,
        'earliestUpdatedAt': earliestUpdatedAt,
        'latestUpdatedAt': latestUpdatedAt,
        'batchSize': batchSize,
        'nextPageToken': nextPageToken,
    }
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLeadSmartCampaignMembership(token, leadId, earliestUpdatedAt=None,
                                   latestUpdatedAt=None, batchSize=None,
                                   nextPageToken=None):
    """List the smart campaigns a lead is a member of, with optional updatedAt filters."""
    url = _base() + f'/rest/v1/leads/{leadId}/smartCampaignMembership.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {
        'earliestUpdatedAt': earliestUpdatedAt,
        'latestUpdatedAt': latestUpdatedAt,
        'batchSize': batchSize,
        'nextPageToken': nextPageToken,
    }
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLeadActivitiesByEmail(token, email, activityTypeIds=None, daysBack=7):
    """Look up a lead by email, then get its recent activities (lookupLead + getLeadActivities)."""
    leadData = lookupLead(token, "email", email)
    leads = leadData.get("result", [])
    if not leads:
        return {"error": f"No lead found with email: {email}"}
    leadId = leads[0].get("id")
    return getLeadActivities(token, leadId, activityTypeIds, daysBack)


# ============================================================================
# Lead Schema
# ============================================================================

def getLeadFields(token, batchSize=None, nextPageToken=None):
    """List the lead object's field schema (all standard and custom fields)."""
    url = _base() + '/rest/v1/leads/schema/fields.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createLeadFields(token, fields):
    """Create custom lead fields. fields is a list of dicts with displayName, name, dataType."""
    url = _base() + '/rest/v1/leads/schema/fields.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": fields}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getLeadFieldByName(token, fieldApiName):
    """Get the schema of a single lead field by its API name."""
    url = _base() + f'/rest/v1/leads/schema/fields/{fieldApiName}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def updateLeadField(token, fieldApiName, updates):
    """Update a lead field's metadata (e.g. displayName, description, isHidden)."""
    url = _base() + f'/rest/v1/leads/schema/fields/{fieldApiName}.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": [updates]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# Static Lists (extended)
# ============================================================================

def removeLeadsFromList(token, listId, leadIds):
    """Remove leads from a static list by lead ID. Max 300 lead IDs per call."""
    if len(leadIds) > 300:
        return {"error": f"Marketo allows at most 300 leads per remove call (got {len(leadIds)})."}
    url = _base() + f'/rest/v1/lists/{listId}/leads.json'
    # DELETE requires a JSON content type even with no body
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    params = {'id': leadIds}
    response = requests.delete(url, headers=headers, params=params, timeout=30)
    return response.json()


def isMemberOfList(token, listId, leadIds):
    """Check whether the given lead IDs are members of a static list."""
    url = _base() + f'/rest/v1/lists/{listId}/leads/ismember.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'id': leadIds}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def deleteStaticList(token, listId):
    """Delete a static list (Asset API)."""
    url = _base() + f'/rest/asset/v1/staticList/{listId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Activities (extended)
# ============================================================================

def getDeletedLeads(token, nextPageToken=None, sinceDatetime=None, batchSize=None):
    """Get lead-deletion activities. Pass nextPageToken, or sinceDatetime to fetch one."""
    headers = {'Authorization': 'Bearer ' + token}
    if nextPageToken is None:
        if sinceDatetime is None:
            return {"error": "Provide nextPageToken or sinceDatetime to anchor the query."}
        tokenResp = requests.get(
            _base() + '/rest/v1/activities/pagingtoken.json',
            headers=headers, params={'sinceDatetime': sinceDatetime}, timeout=30).json()
        nextPageToken = (tokenResp or {}).get('nextPageToken')
        if not nextPageToken:
            return {"error": "Could not fetch a paging token.", "response": tokenResp}
    url = _base() + '/rest/v1/activities/deletedleads.json'
    params = {'nextPageToken': nextPageToken, 'batchSize': batchSize}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def addCustomActivities(token, activities):
    """Add custom activity records to leads. Max 300 activities per call."""
    if len(activities) > 300:
        return {"error": f"Marketo allows at most 300 activities per call (got {len(activities)})."}
    url = _base() + '/rest/v1/activities/external.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": activities}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# Custom Activity Types
# ============================================================================

def getCustomActivityTypes(token):
    """List all custom activity types defined in the instance."""
    url = _base() + '/rest/v1/activities/external/types.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def describeCustomActivityType(token, apiName, draft=False):
    """Describe a custom activity type by API name, including its attributes."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'draft': True} if draft else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createCustomActivityType(token, apiName, name, filterName, triggerName,
                             primaryAttribute, description=None):
    """Create a custom activity type as a draft (approve it separately)."""
    url = _base() + '/rest/v1/activities/external/type.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {
        "apiName": apiName,
        "name": name,
        "filterName": filterName,
        "triggerName": triggerName,
        "primaryAttribute": primaryAttribute,
        "description": description,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def updateCustomActivityType(token, apiName, name=None, filterName=None,
                             triggerName=None, primaryAttribute=None,
                             description=None, newApiName=None):
    """Update a custom activity type's draft (use newApiName to rename the apiName)."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {
        "apiName": newApiName,
        "name": name,
        "filterName": filterName,
        "triggerName": triggerName,
        "primaryAttribute": primaryAttribute,
        "description": description,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def approveCustomActivityType(token, apiName):
    """Approve the draft of a custom activity type, making it live."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}/approve.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardCustomActivityTypeDraft(token, apiName):
    """Discard the draft of a custom activity type."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteCustomActivityType(token, apiName):
    """Delete a custom activity type (must be unused with no recent activity records)."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def addCustomActivityTypeAttributes(token, apiName, attributes):
    """Add secondary attributes to a custom activity type's draft."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}/attributes/create.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"attributes": attributes}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def updateCustomActivityTypeAttributes(token, apiName, attributes):
    """Update secondary attributes on a custom activity type's draft."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}/attributes/update.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"attributes": attributes}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteCustomActivityTypeAttributes(token, apiName, attributes):
    """Delete secondary attributes from a custom activity type's draft."""
    url = _base() + f'/rest/v1/activities/external/type/{apiName}/attributes/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"attributes": attributes}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# Companies
# ============================================================================

def queryCompanies(token, filterType, filterValues, fields=None, batchSize=None,
                   nextPageToken=None):
    """Query company records by a searchable company field."""
    url = _base() + '/rest/v1/companies.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'filterType': filterType, 'filterValues': filterValues, 'fields': fields,
              'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncCompanies(token, records, action="createOrUpdate", dedupeBy=None):
    """Create and/or update company records (max 300). Only usable with no native CRM sync."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 companies per call (got {len(records)})."}
    url = _base() + '/rest/v1/companies.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'action': action, 'dedupeBy': dedupeBy, 'input': records}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteCompanies(token, records, deleteBy="dedupeFields"):
    """Delete company records (max 300). deleteBy is dedupeFields or idField."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 companies per call (got {len(records)})."}
    url = _base() + '/rest/v1/companies/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'deleteBy': deleteBy, 'input': records}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeCompanies(token):
    """Describe the company object: fields, dedupe fields, searchable fields."""
    url = _base() + '/rest/v1/companies/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getCompanyFields(token, batchSize=None, nextPageToken=None):
    """Get metadata for all fields on the company object."""
    url = _base() + '/rest/v1/companies/schema/fields.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getCompanyFieldByName(token, fieldApiName):
    """Get metadata for a single company field by its API name."""
    url = _base() + f'/rest/v1/companies/schema/fields/{fieldApiName}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Opportunities
# ============================================================================

def queryOpportunities(token, filterType, filterValues, fields=None, batchSize=None,
                       nextPageToken=None):
    """Query opportunity records by a searchable opportunity field."""
    url = _base() + '/rest/v1/opportunities.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'filterType': filterType, 'filterValues': filterValues, 'fields': fields,
              'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncOpportunities(token, records, action="createOrUpdate", dedupeBy=None):
    """Create and/or update opportunity records (max 300). Only usable with no native CRM sync."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 opportunities per call (got {len(records)})."}
    url = _base() + '/rest/v1/opportunities.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'action': action, 'dedupeBy': dedupeBy, 'input': records}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteOpportunities(token, records, deleteBy="dedupeFields"):
    """Delete opportunity records (max 300). deleteBy is dedupeFields or idField."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 opportunities per call (got {len(records)})."}
    url = _base() + '/rest/v1/opportunities/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'deleteBy': deleteBy, 'input': records}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeOpportunities(token):
    """Describe the opportunity object: fields, dedupe fields, searchable fields."""
    url = _base() + '/rest/v1/opportunities/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getOpportunityFields(token, batchSize=None, nextPageToken=None):
    """Get metadata for all fields on the opportunity object."""
    url = _base() + '/rest/v1/opportunities/schema/fields.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getOpportunityFieldByName(token, fieldApiName):
    """Get metadata for a single opportunity field by its API name."""
    url = _base() + f'/rest/v1/opportunities/schema/fields/{fieldApiName}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Opportunity Roles
# ============================================================================

def queryOpportunityRoles(token, filterType, filterValues, fields=None, batchSize=None,
                          nextPageToken=None):
    """Query opportunity role records linking leads to opportunities."""
    url = _base() + '/rest/v1/opportunities/roles.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'filterType': filterType, 'filterValues': filterValues, 'fields': fields,
              'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncOpportunityRoles(token, records, action="createOrUpdate", dedupeBy=None):
    """Create and/or update opportunity roles (max 300). Each record needs
    externalOpportunityId, leadId, and role."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 opportunity roles per call (got {len(records)})."}
    url = _base() + '/rest/v1/opportunities/roles.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'action': action, 'dedupeBy': dedupeBy, 'input': records}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteOpportunityRoles(token, records, deleteBy="dedupeFields"):
    """Delete opportunity role records (max 300). deleteBy is dedupeFields or idField."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 opportunity roles per call (got {len(records)})."}
    url = _base() + '/rest/v1/opportunities/roles/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'deleteBy': deleteBy, 'input': records}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeOpportunityRoles(token):
    """Describe the opportunity role object: fields, dedupe fields, searchable fields."""
    url = _base() + '/rest/v1/opportunities/roles/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Sales Persons
# ============================================================================

def querySalesPersons(token, filterType, filterValues, fields=None, batchSize=None,
                      nextPageToken=None):
    """Query sales person records by a searchable sales person field."""
    url = _base() + '/rest/v1/salespersons.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'filterType': filterType, 'filterValues': filterValues, 'fields': fields,
              'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncSalesPersons(token, records, action="createOrUpdate", dedupeBy=None):
    """Create and/or update sales person records (max 300). Only usable with no native CRM sync."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 sales persons per call (got {len(records)})."}
    url = _base() + '/rest/v1/salespersons.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'action': action, 'dedupeBy': dedupeBy, 'input': records}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteSalesPersons(token, records, deleteBy="dedupeFields"):
    """Delete sales person records (max 300). deleteBy is dedupeFields or idField."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 sales persons per call (got {len(records)})."}
    url = _base() + '/rest/v1/salespersons/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'deleteBy': deleteBy, 'input': records}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeSalesPersons(token):
    """Describe the sales person object: fields, dedupe fields, searchable fields."""
    url = _base() + '/rest/v1/salespersons/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Custom Objects
# ============================================================================

def listCustomObjects(token, names=None):
    """List custom object types available in the instance."""
    url = _base() + '/rest/v1/customobjects.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'names': names} if names else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def queryCustomObjects(token, objectApiName, filterType=None, filterValues=None,
                       fields=None, batchSize=None, nextPageToken=None,
                       compoundFilter=None):
    """Query records of a custom object type (compoundFilter switches to POST _method=GET mode)."""
    url = _base() + f'/rest/v1/customobjects/{objectApiName}.json'
    if compoundFilter is not None:
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        body = {'filterType': filterType, 'fields': fields, 'input': compoundFilter}
        body = {k: v for k, v in body.items() if v is not None}
        response = requests.post(url, headers=headers, params={'_method': 'GET'},
                                 json=body, timeout=30)
        return response.json()
    headers = {'Authorization': 'Bearer ' + token}
    params = {'filterType': filterType, 'filterValues': filterValues, 'fields': fields,
              'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncCustomObjects(token, objectApiName, records, action="createOrUpdate", dedupeBy=None):
    """Create and/or update records of a custom object type (max 300)."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 custom object records per call (got {len(records)})."}
    url = _base() + f'/rest/v1/customobjects/{objectApiName}.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'action': action, 'dedupeBy': dedupeBy, 'input': records}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteCustomObjects(token, objectApiName, records, deleteBy="dedupeFields"):
    """Delete records of a custom object type (max 300). deleteBy is dedupeFields or idField."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 custom object records per call (got {len(records)})."}
    url = _base() + f'/rest/v1/customobjects/{objectApiName}/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'deleteBy': deleteBy, 'input': records}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeCustomObject(token, objectApiName):
    """Describe a custom object type: fields, dedupe fields, searchable fields, relationships."""
    url = _base() + f'/rest/v1/customobjects/{objectApiName}/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Custom Object Types
# ============================================================================

def listCustomObjectTypes(token, names=None, state=None):
    """List custom object type schemas, optionally filtered by names or state."""
    url = _base() + '/rest/v1/customobjects/schema.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'names': names, 'state': state}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncCustomObjectType(token, apiName, displayName, action=None, pluralName=None,
                         description=None, showInLeadDetail=None):
    """Create or update a custom object type as a draft (approve before syncing records)."""
    url = _base() + '/rest/v1/customobjects/schema.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {
        'action': action,
        'apiName': apiName,
        'displayName': displayName,
        'pluralName': pluralName,
        'description': description,
        'showInLeadDetail': showInLeadDetail,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeCustomObjectType(token, apiName, state=None):
    """Describe a custom object type schema by API name (state: draft or approved)."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'state': state} if state else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getCustomObjectFieldTypes(token):
    """Get the list of data types available for custom object fields."""
    url = _base() + '/rest/v1/customobjects/schema/fieldDataTypes.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getCustomObjectLinkableObjects(token):
    """Get the objects (lead, company, etc.) that custom object link fields can relate to."""
    url = _base() + '/rest/v1/customobjects/schema/linkableObjects.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getCustomObjectTypeDependents(token, apiName):
    """Get assets (smart lists, campaigns, etc.) that depend on a custom object type."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/dependentAssets.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def addCustomObjectTypeFields(token, apiName, fields):
    """Add fields to a custom object type draft (each needs name, displayName, dataType)."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/addField.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": fields}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def updateCustomObjectTypeField(token, apiName, fieldApiName, updates):
    """Update a field on a custom object type draft."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/{fieldApiName}/updateField.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, json=updates, timeout=30)
    return response.json()


def deleteCustomObjectTypeFields(token, apiName, fieldNames):
    """Delete fields from a custom object type draft. fieldNames is a list of field API names."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/deleteField.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": [{"name": n} for n in fieldNames]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def approveCustomObjectType(token, apiName):
    """Approve the draft of a custom object type, making it usable for records."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/approve.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardCustomObjectTypeDraft(token, apiName):
    """Discard the draft version of a custom object type."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteCustomObjectType(token, apiName):
    """Delete a custom object type entirely (must have no dependent assets or records)."""
    url = _base() + f'/rest/v1/customobjects/schema/{apiName}/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Named Accounts
# ============================================================================

def queryNamedAccounts(token, filterType, filterValues, fields=None, batchSize=None,
                       nextPageToken=None):
    """Query named account records. Requires an ABM-enabled subscription."""
    url = _base() + '/rest/v1/namedaccounts.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'filterType': filterType, 'filterValues': filterValues, 'fields': fields,
              'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncNamedAccounts(token, records, action="createOrUpdate", dedupeBy=None):
    """Create and/or update named accounts (max 300). Requires an ABM-enabled subscription."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 named accounts per call (got {len(records)})."}
    url = _base() + '/rest/v1/namedaccounts.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'action': action, 'dedupeBy': dedupeBy, 'input': records}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteNamedAccounts(token, records, deleteBy="dedupeFields"):
    """Delete named accounts (max 300). Requires an ABM-enabled subscription."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 named accounts per call (got {len(records)})."}
    url = _base() + '/rest/v1/namedaccounts/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'deleteBy': deleteBy, 'input': records}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def describeNamedAccounts(token):
    """Describe the named account object. Requires an ABM-enabled subscription."""
    url = _base() + '/rest/v1/namedaccounts/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getNamedAccountFields(token, batchSize=None, nextPageToken=None):
    """Get metadata for all fields on the named account object."""
    url = _base() + '/rest/v1/namedaccounts/schema/fields.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getNamedAccountFieldByName(token, fieldApiName):
    """Get metadata for a single named account field by its API name."""
    url = _base() + f'/rest/v1/namedaccounts/schema/fields/{fieldApiName}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Named Account Lists
# ============================================================================

def queryNamedAccountLists(token, filterType, filterValues, batchSize=None,
                           nextPageToken=None):
    """Query named account lists. filterType is dedupeFields (list name) or idField."""
    url = _base() + '/rest/v1/namedAccountLists.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'filterType': filterType, 'filterValues': filterValues,
              'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def syncNamedAccountLists(token, records, action="createOrUpdate", dedupeBy=None):
    """Create and/or update named account lists (max 300). Requires an ABM-enabled subscription."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 named account lists per call (got {len(records)})."}
    url = _base() + '/rest/v1/namedAccountLists.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'action': action, 'dedupeBy': dedupeBy, 'input': records}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteNamedAccountLists(token, records, deleteBy="dedupeFields"):
    """Delete named account lists (max 300). deleteBy is dedupeFields or idField."""
    if len(records) > 300:
        return {"error": f"Marketo allows at most 300 named account lists per call (got {len(records)})."}
    url = _base() + '/rest/v1/namedAccountLists/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'deleteBy': deleteBy, 'input': records}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getNamedAccountListMembers(token, listId, fields=None, batchSize=None,
                               nextPageToken=None):
    """Get the named accounts that are members of a named account list."""
    url = _base() + f'/rest/v1/namedAccountList/{listId}/namedAccounts.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'fields': fields, 'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def addNamedAccountListMembers(token, listId, accountIds):
    """Add named accounts to a named account list by marketoGUID (max 300)."""
    if len(accountIds) > 300:
        return {"error": f"Marketo allows at most 300 named accounts per call (got {len(accountIds)})."}
    url = _base() + f'/rest/v1/namedAccountList/{listId}/namedAccounts.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": [{"id": i} for i in accountIds]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def removeNamedAccountListMembers(token, listId, accountIds):
    """Remove named accounts from a named account list by marketoGUID (max 300)."""
    if len(accountIds) > 300:
        return {"error": f"Marketo allows at most 300 named accounts per call (got {len(accountIds)})."}
    url = _base() + f'/rest/v1/namedAccountList/{listId}/namedAccounts/remove.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": [{"id": i} for i in accountIds]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# Program Members (extended)
# ============================================================================

def syncProgramMemberData(token, programId, members):
    """Update custom program-member field values for leads in a program. Max 300 members."""
    if len(members) > 300:
        return {"error": f"Marketo allows at most 300 members per call (got {len(members)})."}
    url = _base() + f'/rest/v1/programs/{programId}/members.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": members}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def syncProgramMemberStatus(token, programId, statusName, leadIds):
    """Set the program membership status (by status name) for lead IDs. Max 300 per call."""
    if len(leadIds) > 300:
        return {"error": f"Marketo allows at most 300 leads per call (got {len(leadIds)})."}
    url = _base() + f'/rest/v1/programs/{programId}/members/status.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"statusName": statusName,
            "input": [{"leadId": leadId} for leadId in leadIds]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteProgramMembers(token, programId, leadIds):
    """Remove leads from a program (deletes their program membership records). Max 300."""
    if len(leadIds) > 300:
        return {"error": f"Marketo allows at most 300 leads per call (got {len(leadIds)})."}
    url = _base() + f'/rest/v1/programs/{programId}/members/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": [{"leadId": leadId} for leadId in leadIds]}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def createProgramMemberFields(token, fields):
    """Create custom program-member fields (each needs displayName, name, dataType)."""
    url = _base() + '/rest/v1/programs/members/schema/fields.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": fields}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getProgramMemberFieldByName(token, fieldApiName):
    """Get the metadata for a single program-member field by its API name."""
    url = _base() + f'/rest/v1/programs/members/schema/fields/{fieldApiName}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def updateProgramMemberField(token, fieldApiName, updates):
    """Update a custom program-member field. updates is a list of update dicts."""
    url = _base() + f'/rest/v1/programs/members/schema/fields/{fieldApiName}.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"input": updates}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# Bulk Lead Import & Export Mgmt
# ============================================================================

def importLeadsCsv(token, csvContent, lookupField="email", listId=None, partitionName=None):
    """Start a bulk lead import job from CSV content. Returns a batchId. Max 10MB."""
    if len(csvContent.encode()) > 10 * 1024 * 1024:
        return {"error": "CSV content exceeds Marketo's 10MB bulk import limit."}
    url = _base() + '/bulk/v1/leads.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'format': 'csv', 'lookupField': lookupField}
    if listId:
        params['listId'] = listId
    if partitionName:
        params['partitionName'] = partitionName
    files = {'file': ('leads.csv', csvContent, 'text/csv')}
    response = requests.post(url, headers=headers, params=params, files=files, timeout=60)
    return response.json()


def getLeadImportFailures(token, batchId):
    """Get the failures file for a bulk lead import batch (CSV text)."""
    url = _base() + f'/bulk/v1/leads/batch/{batchId}/failures.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.text


def getLeadImportWarnings(token, batchId):
    """Get the warnings file for a bulk lead import batch (CSV text)."""
    url = _base() + f'/bulk/v1/leads/batch/{batchId}/warnings.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.text


def listLeadExportJobs(token, status=None, batchSize=None, nextPageToken=None):
    """List bulk lead export jobs, optionally filtered by status."""
    url = _base() + '/bulk/v1/leads/export.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status, 'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def cancelLeadExportJob(token, exportId):
    """Cancel a bulk lead export job."""
    url = _base() + f'/bulk/v1/leads/export/{exportId}/cancel.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Bulk Activity Export
# ============================================================================

def createActivityExportJob(token, startAt, endAt, activityTypeIds=None, fields=None,
                            exportFormat="CSV", columnHeaderNames=None):
    """Create a bulk activity export job filtered by createdAt range (max 31 days)."""
    url = _base() + '/bulk/v1/activities/export/create.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    activityFilter = {"createdAt": {"startAt": startAt, "endAt": endAt}}
    if activityTypeIds is not None:
        activityFilter["activityTypeIds"] = activityTypeIds
    body = {"fields": fields, "filter": activityFilter, "format": exportFormat,
            "columnHeaderNames": columnHeaderNames}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def enqueueActivityExportJob(token, exportId):
    """Enqueue a created bulk activity export job for processing."""
    url = _base() + f'/bulk/v1/activities/export/{exportId}/enqueue.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def getActivityExportJobStatus(token, exportId):
    """Get the status of a bulk activity export job."""
    url = _base() + f'/bulk/v1/activities/export/{exportId}/status.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getActivityExportFile(token, exportId):
    """Download the file for a completed bulk activity export job (returns CSV/TSV text)."""
    url = _base() + f'/bulk/v1/activities/export/{exportId}/file.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=60)
    return response.text


def cancelActivityExportJob(token, exportId):
    """Cancel a bulk activity export job."""
    url = _base() + f'/bulk/v1/activities/export/{exportId}/cancel.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def listActivityExportJobs(token, status=None, batchSize=None, nextPageToken=None):
    """List bulk activity export jobs, optionally filtered by status."""
    url = _base() + '/bulk/v1/activities/export.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status, 'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Bulk Program Member Export/Import
# ============================================================================

def createProgramMemberExportJob(token, fields, programId, exportFormat="CSV",
                                 columnHeaderNames=None):
    """Create a bulk program member export job for a program. Returns an exportId."""
    url = _base() + '/bulk/v1/program/members/export/create.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"fields": fields, "filter": {"programId": programId},
            "format": exportFormat, "columnHeaderNames": columnHeaderNames}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def enqueueProgramMemberExportJob(token, exportId):
    """Enqueue a created bulk program member export job for processing."""
    url = _base() + f'/bulk/v1/program/members/export/{exportId}/enqueue.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def getProgramMemberExportJobStatus(token, exportId):
    """Get the status of a bulk program member export job."""
    url = _base() + f'/bulk/v1/program/members/export/{exportId}/status.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getProgramMemberExportFile(token, exportId):
    """Download the file for a completed bulk program member export job (CSV/TSV text)."""
    url = _base() + f'/bulk/v1/program/members/export/{exportId}/file.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=60)
    return response.text


def cancelProgramMemberExportJob(token, exportId):
    """Cancel a bulk program member export job."""
    url = _base() + f'/bulk/v1/program/members/export/{exportId}/cancel.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def listProgramMemberExportJobs(token, status=None, batchSize=None, nextPageToken=None):
    """List bulk program member export jobs, optionally filtered by status."""
    url = _base() + '/bulk/v1/program/members/export.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status, 'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def importProgramMembersCsv(token, programId, programMemberStatus, csvContent):
    """Start a bulk program member import from CSV content. Returns a batchId. Max 10MB."""
    if len(csvContent.encode()) > 10 * 1024 * 1024:
        return {"error": "CSV content exceeds Marketo's 10MB bulk import limit."}
    url = _base() + f'/bulk/v1/program/{programId}/members/import.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'programMemberStatus': programMemberStatus, 'format': 'csv'}
    files = {'file': ('data.csv', csvContent, 'text/csv')}
    response = requests.post(url, headers=headers, params=params, files=files, timeout=60)
    return response.json()


def getProgramMemberImportStatus(token, batchId):
    """Get the status of a bulk program member import batch."""
    url = _base() + f'/bulk/v1/program/members/import/{batchId}/status.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getProgramMemberImportFailures(token, batchId):
    """Get the failures file for a bulk program member import batch (CSV text)."""
    url = _base() + f'/bulk/v1/program/members/import/{batchId}/failures.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.text


def getProgramMemberImportWarnings(token, batchId):
    """Get the warnings file for a bulk program member import batch (CSV text)."""
    url = _base() + f'/bulk/v1/program/members/import/{batchId}/warnings.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.text


# ============================================================================
# Bulk Custom Object Export/Import
# ============================================================================

def createCustomObjectExportJob(token, objectApiName, fields, exportFilter,
                                exportFormat="CSV", columnHeaderNames=None):
    """Create a bulk export job for a custom object (filter by updatedAt/staticListId/smartListId)."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/export/create.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {"fields": fields, "filter": exportFilter, "format": exportFormat,
            "columnHeaderNames": columnHeaderNames}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def enqueueCustomObjectExportJob(token, objectApiName, exportId):
    """Enqueue a created bulk custom object export job for processing."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/export/{exportId}/enqueue.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def getCustomObjectExportJobStatus(token, objectApiName, exportId):
    """Get the status of a bulk custom object export job."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/export/{exportId}/status.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getCustomObjectExportFile(token, objectApiName, exportId):
    """Download the file for a completed bulk custom object export job (CSV/TSV text)."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/export/{exportId}/file.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=60)
    return response.text


def cancelCustomObjectExportJob(token, objectApiName, exportId):
    """Cancel a bulk custom object export job."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/export/{exportId}/cancel.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def listCustomObjectExportJobs(token, objectApiName, status=None, batchSize=None,
                               nextPageToken=None):
    """List bulk export jobs for a custom object, optionally filtered by status."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/export.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status, 'batchSize': batchSize, 'nextPageToken': nextPageToken}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def importCustomObjectsCsv(token, objectApiName, csvContent):
    """Start a bulk custom object import from CSV content. Returns a batchId. Max 10MB."""
    if len(csvContent.encode()) > 10 * 1024 * 1024:
        return {"error": "CSV content exceeds Marketo's 10MB bulk import limit."}
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/import.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'format': 'csv'}
    files = {'file': ('data.csv', csvContent, 'text/csv')}
    response = requests.post(url, headers=headers, params=params, files=files, timeout=60)
    return response.json()


def getCustomObjectImportStatus(token, objectApiName, batchId):
    """Get the status of a bulk custom object import batch."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/import/{batchId}/status.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getCustomObjectImportFailures(token, objectApiName, batchId):
    """Get the failures file for a bulk custom object import batch (CSV text)."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/import/{batchId}/failures.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.text


def getCustomObjectImportWarnings(token, objectApiName, batchId):
    """Get the warnings file for a bulk custom object import batch (CSV text)."""
    url = _base() + f'/bulk/v1/customobjects/{objectApiName}/import/{batchId}/warnings.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.text


# ============================================================================
# Usage Stats
# ============================================================================

def getDailyUsage(token):
    """Get today's API usage (call counts per user) for the instance."""
    url = _base() + '/rest/v1/stats/usage.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getWeeklyUsage(token):
    """Get API usage (call counts per user) for the past 7 days."""
    url = _base() + '/rest/v1/stats/usage/last7days.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getDailyErrors(token):
    """Get today's API error counts (by error code) for the instance."""
    url = _base() + '/rest/v1/stats/errors.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getWeeklyErrors(token):
    """Get API error counts (by error code) for the past 7 days."""
    url = _base() + '/rest/v1/stats/errors/last7days.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Emails (extended)
# ============================================================================

def sendSampleEmail(token, emailId, emailAddress, textOnly=False, leadId=None):
    """Send a sample of an email to an address (leadId impersonates a lead for rendering)."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/sendSample.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'emailAddress': emailAddress}
    if textOnly:
        data['textOnly'] = 'true'
    if leadId:
        data['leadId'] = leadId
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateEmail(token, emailId, name=None, description=None, preHeader=None,
                operational=None, published=None, textOnly=None, webView=None):
    """Update an email's metadata: name, description, preHeader, and boolean flags."""
    url = _base() + f'/rest/asset/v1/email/{emailId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'description': description,
        'preHeader': preHeader,
        'operational': operational,
        'published': published,
        'textOnly': textOnly,
        'webView': webView,
    }
    data = {k: ('true' if v else 'false') if isinstance(v, bool) else v
            for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def cloneEmail(token, emailId, name, folderId, folderType="Folder", description=None,
               operational=None):
    """Clone an email into a folder or program."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/clone.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": folderType}),
        'description': description,
        'operational': operational,
    }
    data = {k: ('true' if v else 'false') if isinstance(v, bool) else v
            for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteEmail(token, emailId):
    """Delete an email. The email must be unapproved and not in use."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def unapproveEmail(token, emailId):
    """Unapprove an email, reverting it to draft-only state."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/unapprove.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardEmailDraft(token, emailId):
    """Discard an email's draft version, leaving the approved version untouched."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def updateEmailHeaders(token, emailId, subject=None, fromName=None, fromEmail=None,
                       replyTo=None):
    """Update an email's header fields (subject, fromName, fromEmail, replyTo) on its draft."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/content.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'subject': subject,
        'fromName': fromName,
        'fromEmail': fromEmail,
        'replyTO': replyTo,  # field name casing per Marketo docs
    }
    data = {k: json.dumps({"type": "Text", "value": v})
            for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def rearrangeEmailModules(token, emailId, positions):
    """Rearrange the modules within an email's draft (modular editor only)."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/content/rearrange.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'positions': json.dumps(positions)}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def addEmailModule(token, emailId, moduleId, name, index):
    """Add a copy of an existing module to an email at the given position (modular editor)."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/content/{moduleId}/add.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'name': name, 'index': index}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteEmailModule(token, emailId, moduleId):
    """Delete a module from an email's draft (modular editor only)."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/content/{moduleId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def duplicateEmailModule(token, emailId, moduleId, name):
    """Duplicate a module within an email (modular editor only), naming the copy."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/content/{moduleId}/duplicate.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'name': name}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def renameEmailModule(token, emailId, moduleId, name):
    """Rename a module within an email (modular editor only)."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/content/{moduleId}/rename.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'name': name}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def getEmailDynamicContent(token, emailId, dynamicContentId, status=None):
    """Get the dynamic content (per-segment variations) for a section of an email."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/dynamicContent/{dynamicContentId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def updateEmailDynamicContent(token, emailId, dynamicContentId, segment, contentType, value):
    """Update a segment's variation in a dynamic content section of an email's draft."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/dynamicContent/{dynamicContentId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'segment': segment, 'type': contentType, 'value': value}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateEmailFullContent(token, emailId, htmlContent):
    """Replace the entire HTML content of an email's draft (non-modular emails only)."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/fullContent.json'
    headers = {'Authorization': 'Bearer ' + token}
    files = {'content': ('email.html', htmlContent, 'text/html')}
    response = requests.post(url, headers=headers, files=files, timeout=60)
    return response.json()


def getEmailVariables(token, emailId):
    """Get the variables defined for an email (modular editor emails with variables)."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/variables.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def updateEmailVariable(token, emailId, variableName, value, moduleId=None):
    """Update the value of an email variable on the email's draft."""
    url = _base() + f'/rest/asset/v1/email/{emailId}/variable/{variableName}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'value': value, 'moduleId': moduleId}
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


# ============================================================================
# Email Templates
# ============================================================================

def browseEmailTemplates(token, status=None, maxReturn=20, offset=None):
    """List email templates with optional status filtering."""
    url = _base() + '/rest/asset/v1/emailTemplates.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'maxReturn': min(maxReturn or 20, 200)}
    if status is not None:
        params['status'] = status
    if offset is not None:
        params['offset'] = offset
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailTemplateById(token, templateId, status=None):
    """Get an email template's metadata by ID."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailTemplateByName(token, name, status=None):
    """Get an email template's metadata by exact name."""
    url = _base() + '/rest/asset/v1/emailTemplate/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'name': name}
    if status is not None:
        params['status'] = status
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailTemplateContent(token, templateId, status=None):
    """Get an email template's HTML content."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}/content'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailTemplateUsedBy(token, templateId, maxReturn=None, offset=None):
    """List the emails that use an email template."""
    url = _base() + f'/rest/asset/v1/emailTemplates/{templateId}/usedBy.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'maxReturn': maxReturn, 'offset': offset}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createEmailTemplate(token, name, folderId, htmlContent, description=None,
                        folderType="Folder"):
    """Create a new email template in a folder from HTML content."""
    url = _base() + '/rest/asset/v1/emailTemplates.json'
    headers = {'Authorization': 'Bearer ' + token}
    data = {'name': name, 'folder': json.dumps({"id": folderId, "type": folderType})}
    if description is not None:
        data['description'] = description
    files = {'content': ('template.html', htmlContent, 'text/html')}
    response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
    return response.json()


def updateEmailTemplate(token, templateId, name=None, description=None):
    """Update an email template's name and/or description."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'name': name, 'description': description}
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateEmailTemplateContent(token, templateId, htmlContent):
    """Replace an email template's HTML content (changes apply to the draft)."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}/content.json'
    headers = {'Authorization': 'Bearer ' + token}
    files = {'content': ('template.html', htmlContent, 'text/html')}
    response = requests.post(url, headers=headers, files=files, timeout=60)
    return response.json()


def approveEmailTemplate(token, templateId):
    """Approve an email template's draft, making it the live version."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}/approveDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def unapproveEmailTemplate(token, templateId):
    """Unapprove an email template, reverting it to draft-only state."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}/unapprove.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardEmailTemplateDraft(token, templateId):
    """Discard an email template's draft, leaving the approved version untouched."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def cloneEmailTemplate(token, templateId, name, folderId, folderType="Folder",
                       description=None):
    """Clone an email template into a folder."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}/clone.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": folderType}),
        'description': description,
    }
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteEmailTemplate(token, templateId):
    """Delete an email template (must be unapproved and not in use by any email)."""
    url = _base() + f'/rest/asset/v1/emailTemplate/{templateId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Files
# ============================================================================

def browseFiles(token, folderId=None, folderType="Folder", maxReturn=None, offset=None):
    """List files in the Design Studio, optionally scoped to a folder."""
    url = _base() + '/rest/asset/v1/files.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {}
    if folderId is not None:
        params['folder'] = json.dumps({"id": folderId, "type": folderType})
    if maxReturn is not None:
        params['maxReturn'] = maxReturn
    if offset is not None:
        params['offset'] = offset
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getFileById(token, fileId):
    """Get a file's metadata (including its public URL) by ID."""
    url = _base() + f'/rest/asset/v1/file/{fileId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getFileByName(token, name):
    """Get a file's metadata (including its public URL) by exact name."""
    url = _base() + '/rest/asset/v1/file/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'name': name}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def uploadFile(token, name, folderId, fileContent, fileName=None, description=None,
               insertOnly=False, isBase64=False, folderType="Folder"):
    """Upload a file to the Design Studio (pass base64 content with isBase64=True for binary)."""
    url = _base() + '/rest/asset/v1/files.json'
    headers = {'Authorization': 'Bearer ' + token}
    content = base64.b64decode(fileContent) if isBase64 else fileContent
    data = {'name': name, 'folder': json.dumps({"id": folderId, "type": folderType})}
    if description is not None:
        data['description'] = description
    if insertOnly is not None:
        data['insertOnly'] = 'true' if insertOnly else 'false'
    # An explicit part-level mime type is required: without it Marketo stores
    # the request envelope's multipart/form-data type as the file's mimeType,
    # which then breaks replaceFileContent (709 type-mismatch) forever.
    mime = mimetypes.guess_type(fileName or name)[0] or 'application/octet-stream'
    files = {'file': (fileName or name, content, mime)}
    response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
    return response.json()


def replaceFileContent(token, fileId, fileContent, fileName=None, isBase64=False):
    """Replace the content of an existing Design Studio file (the file keeps its URL)."""
    url = _base() + f'/rest/asset/v1/file/{fileId}/content.json'
    headers = {'Authorization': 'Bearer ' + token}
    content = base64.b64decode(fileContent) if isBase64 else fileContent
    mime = mimetypes.guess_type(fileName or '')[0] or 'application/octet-stream'
    files = {'file': (fileName or 'file', content, mime)}
    response = requests.post(url, headers=headers, files=files, timeout=60)
    return response.json()


# ============================================================================
# Landing Pages (extended)
# ============================================================================

def createLandingPage(token, name, folderId, templateId, folderType="Folder",
                      description=None, title=None, urlPageName=None,
                      mobileEnabled=None, prefillForm=None, customHeadHtml=None,
                      facebookOgTags=None, keywords=None, robots=None,
                      workspace=None):
    """Create a new landing page from a landing page template in the given folder."""
    url = _base() + '/rest/asset/v1/landingPages.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": folderType}),
        'template': templateId,
        'description': description,
        'title': title,
        'urlPageName': urlPageName,
        'mobileEnabled': None if mobileEnabled is None else ('true' if mobileEnabled else 'false'),
        'prefillForm': None if prefillForm is None else ('true' if prefillForm else 'false'),
        'customHeadHTML': customHeadHtml,
        'facebookOgTags': facebookOgTags,
        'keywords': keywords,
        'robots': robots,
        'workspace': workspace,
    }
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def cloneLandingPage(token, landingPageId, name, folderId, folderType="Folder",
                     description=None, templateId=None):
    """Clone a landing page into a folder, optionally switching templates."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/clone.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": folderType}),
        'description': description,
        'template': templateId,
    }
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteLandingPage(token, landingPageId):
    """Delete a landing page (it must be unapproved first)."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def addLandingPageContentSection(token, landingPageId, contentId, contentType,
                                 value=None, layout=None):
    """Add a content section to a landing page draft (layout is a dict of positioning attributes)."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/content.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'contentId': contentId, 'type': contentType, 'value': value}
    if layout:
        data.update(layout)
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteLandingPageContentSection(token, landingPageId, contentId):
    """Delete a content section from a landing page draft."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/content/{contentId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def getLandingPageDynamicContent(token, landingPageId, dynamicContentId):
    """Get the dynamic content (per-segment variations) of a landing page content section."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/dynamicContent/{dynamicContentId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def updateLandingPageDynamicContent(token, landingPageId, dynamicContentId,
                                    segment=None, contentType=None, value=None,
                                    layout=None):
    """Update a segment variation of a dynamic content section on a landing page draft."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/dynamicContent/{dynamicContentId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'segment': segment, 'type': contentType, 'value': value}
    if layout:
        data.update(layout)
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def getLandingPageVariables(token, landingPageId, status=None):
    """Get the variables of a landing page built on a guided template."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/variables.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def updateLandingPageVariable(token, landingPageId, variableId, value):
    """Update the value of a guided landing page variable on the page's draft."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/variable/{variableId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'value': value}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


# ============================================================================
# Landing Page Templates
# ============================================================================

def browseLandingPageTemplates(token, status=None, folderId=None,
                               folderType="Folder", maxReturn=20, offset=0):
    """Browse landing page templates with optional folder/status filtering."""
    url = _base() + '/rest/asset/v1/landingPageTemplates.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'maxReturn': maxReturn, 'offset': offset}
    if status:
        params['status'] = status
    if folderId is not None:
        params['folder'] = json.dumps({"id": folderId, "type": folderType})
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLandingPageTemplateById(token, templateId, status=None):
    """Get a landing page template by its ID."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLandingPageTemplateByName(token, name):
    """Get a landing page template by its name."""
    url = _base() + '/rest/asset/v1/landingPageTemplate/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'name': name}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLandingPageTemplateContent(token, templateId, status=None):
    """Get the HTML content of a landing page template."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}/content.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createLandingPageTemplate(token, name, folderId, folderType="Folder",
                              description=None, enableMunchkin=None,
                              templateType="freeForm"):
    """Create a new landing page template (templateType is freeForm or guided)."""
    url = _base() + '/rest/asset/v1/landingPageTemplates.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": folderType}),
        'description': description,
        'enableMunchkin': None if enableMunchkin is None else ('true' if enableMunchkin else 'false'),
        'templateType': templateType,
    }
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateLandingPageTemplate(token, templateId, name=None, description=None,
                              enableMunchkin=None):
    """Update landing page template metadata (name, description, Munchkin tracking)."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'description': description,
        'enableMunchkin': None if enableMunchkin is None else ('true' if enableMunchkin else 'false'),
    }
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateLandingPageTemplateContent(token, templateId, htmlContent):
    """Replace the HTML content of a landing page template's draft."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}/content.json'
    headers = {'Authorization': 'Bearer ' + token}
    files = {'content': ('template.html', htmlContent, 'text/html')}
    response = requests.post(url, headers=headers, files=files, timeout=60)
    return response.json()


def approveLandingPageTemplate(token, templateId):
    """Approve a landing page template draft, publishing the changes."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}/approveDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def unapproveLandingPageTemplate(token, templateId):
    """Unapprove a landing page template, reverting it to draft-only."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}/unapprove.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardLandingPageTemplateDraft(token, templateId):
    """Discard the draft version of a landing page template."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def cloneLandingPageTemplate(token, templateId, name, folderId,
                             folderType="Folder", description=None):
    """Clone a landing page template into the given folder."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}/clone.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'name': name,
        'folder': json.dumps({"id": folderId, "type": folderType}),
        'description': description,
    }
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteLandingPageTemplate(token, templateId):
    """Delete a landing page template. Fails if any landing pages still use it."""
    url = _base() + f'/rest/asset/v1/landingPageTemplate/{templateId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Redirect Rules & Domains
# ============================================================================

def browseRedirectRules(token, redirectToPath=None, redirectToLandingPageId=None,
                        earliestUpdatedAt=None, latestUpdatedAt=None,
                        maxReturn=20, offset=0):
    """Browse landing page redirect rules with optional target/update-date filtering."""
    url = _base() + '/rest/asset/v1/redirectRules.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'maxReturn': maxReturn, 'offset': offset}
    if redirectToPath:
        params['redirectToPath'] = redirectToPath
    if redirectToLandingPageId is not None:
        params['redirectTolandingPageId'] = redirectToLandingPageId
    if earliestUpdatedAt:
        params['earliestUpdatedAt'] = earliestUpdatedAt
    if latestUpdatedAt:
        params['latestUpdatedAt'] = latestUpdatedAt
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getRedirectRuleById(token, ruleId):
    """Get a landing page redirect rule by its ID."""
    url = _base() + f'/rest/asset/v1/redirectRule/{ruleId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def createRedirectRule(token, hostname, fromType, fromValue, toType, toValue):
    """Create a landing page redirect rule (types are landingPageId or path)."""
    url = _base() + '/rest/asset/v1/redirectRules.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'hostname': hostname,
        'redirectFrom': json.dumps({"type": fromType, "value": fromValue}),
        'redirectTo': json.dumps({"type": toType, "value": toValue}),
    }
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateRedirectRule(token, ruleId, hostname=None, fromType=None,
                       fromValue=None, toType=None, toValue=None):
    """Update a redirect rule (supply both type and value to change source or target)."""
    url = _base() + f'/rest/asset/v1/redirectRule/{ruleId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'hostname': hostname}
    if fromType is not None and fromValue is not None:
        data['redirectFrom'] = json.dumps({"type": fromType, "value": fromValue})
    if toType is not None and toValue is not None:
        data['redirectTo'] = json.dumps({"type": toType, "value": toValue})
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def deleteRedirectRule(token, ruleId):
    """Delete a landing page redirect rule."""
    url = _base() + f'/rest/asset/v1/redirectRule/{ruleId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def getLandingPageDomains(token, maxReturn=20, offset=0):
    """Get the landing page domains (CNAMEs) configured for the instance."""
    url = _base() + '/rest/asset/v1/landingPageDomains.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'maxReturn': maxReturn, 'offset': offset}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Segmentation
# ============================================================================

def browseSegmentations(token, status=None):
    """Browse the segmentations defined in the instance."""
    url = _base() + '/rest/asset/v1/segmentation.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else None
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getSegments(token, segmentationId, status=None, maxReturn=20, offset=0):
    """Get the segments of a segmentation (use segment names for dynamic content)."""
    url = _base() + f'/rest/asset/v1/segmentation/{segmentationId}/segments.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'maxReturn': maxReturn, 'offset': offset}
    if status:
        params['status'] = status
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


# ============================================================================
# Forms (extended)
# ============================================================================

def deleteForm(token, formId):
    """Delete a form. The form must not be in use by any landing pages."""
    url = _base() + f'/rest/asset/v1/form/{formId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardFormDraft(token, formId):
    """Discard the draft version of a form."""
    url = _base() + f'/rest/asset/v1/form/{formId}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteFormField(token, formId, fieldId):
    """Delete a field from a form draft (fieldId is the field's API name)."""
    url = _base() + f'/rest/asset/v1/form/{formId}/field/{fieldId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteFormFieldsetField(token, formId, fieldSetId, fieldId):
    """Delete a field from a fieldset on a form draft."""
    url = _base() + f'/rest/asset/v1/form/{formId}/fieldSet/{fieldSetId}/field/{fieldId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def updateFormSubmitButton(token, formId, label=None, waitingLabel=None,
                           buttonPosition=None, buttonStyle=None):
    """Update the submit button of a form draft (label, waiting label, position, style)."""
    url = _base() + f'/rest/asset/v1/form/{formId}/submitButton.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'label': label, 'waitingLabel': waitingLabel,
            'buttonPosition': buttonPosition, 'buttonStyle': buttonStyle}
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateFormThankYouPages(token, formId, rules):
    """Replace the thank-you page rules of a form draft (rules is a list of rule dicts)."""
    url = _base() + f'/rest/asset/v1/form/{formId}/thankYouPage.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'thankyou': json.dumps(rules)}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


# ============================================================================
# Remaining Asset Deletes
# ============================================================================

def deleteSmartList(token, smartListId):
    """Delete a smart list."""
    url = _base() + f'/rest/asset/v1/smartList/{smartListId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteSnippet(token, snippetId):
    """Delete a snippet. The snippet must not be in use by other assets."""
    url = _base() + f'/rest/asset/v1/snippet/{snippetId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardSnippetDraft(token, snippetId):
    """Discard the draft version of a snippet."""
    url = _base() + f'/rest/asset/v1/snippet/{snippetId}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def unapproveSnippet(token, snippetId):
    """Unapprove a snippet, reverting it to draft-only."""
    url = _base() + f'/rest/asset/v1/snippet/{snippetId}/unapprove.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteFolder(token, folderId, folderType="Folder"):
    """Delete an empty folder or program shell (folderType is Folder or Program)."""
    url = _base() + f'/rest/asset/v1/folder/{folderId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'type': folderType}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


# ============================================================================
# Asset v2 — Emails (Emails 2.0; paths have no .json suffix)
# ============================================================================

def getEmail2ById(token, emailId):
    """Get an Emails 2.0 email by ID (Asset v2; requires Emails 2.0 enabled)."""
    url = _base() + f'/rest/asset/v2/email/{emailId}'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def createEmail2(token, name, appData, emailHeaders, description=None,
                 templateId=None, themeId=None, data=None, settings=None,
                 status=None, editorContext=None):
    """Create an Emails 2.0 email (Asset v2). emailHeaders carries subject/fromName/fromEmail/replyTo."""
    url = _base() + '/rest/asset/v2/email'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {
        'name': name,
        'appData': appData,
        'headers': emailHeaders,
        'description': description,
        'templateId': templateId,
        'themeId': themeId,
        'data': data,
        'settings': settings,
        'status': status,
        'editorContext': editorContext,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def updateEmail2(token, emailId, name=None, description=None, data=None,
                 emailHeaders=None, settings=None, templateId=None,
                 themeId=None, status=None):
    """Update an Emails 2.0 email (Asset v2): name, description, data, headers, settings, etc."""
    url = _base() + f'/rest/asset/v2/email/{emailId}/update'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {
        'name': name,
        'description': description,
        'data': data,
        'headers': emailHeaders,
        'settings': settings,
        'templateId': templateId,
        'themeId': themeId,
        'status': status,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteEmail2(token, emailId):
    """Delete an Emails 2.0 email (Asset v2)."""
    url = _base() + f'/rest/asset/v2/email/{emailId}/delete'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    response = requests.post(url, headers=headers, json={}, timeout=30)
    return response.json()


def cloneEmail2(token, emailId, name, folderId, extra=None):
    """Clone an Emails 2.0 email (Asset v2) into a folder under a new name."""
    url = _base() + '/rest/asset/v2/email/clone'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    newAsset = {'name': name, 'folderId': folderId}
    if extra:
        newAsset.update(extra)
    body = {'assetId': emailId, 'newAsset': newAsset}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def transitionEmail2State(token, emailId, action):
    """Transition an Emails 2.0 email's approval state (approve, unapprove, or discard)."""
    url = _base() + '/rest/asset/v2/email/state/transition'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {'contentId': emailId, 'action': action}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getEmail2UsedBy(token, emailId, pageIndex=None, pageSize=None, assetType=None):
    """List assets that use an Emails 2.0 email (Asset v2 usedby)."""
    url = _base() + '/rest/asset/v2/email/usedby'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {'assetId': emailId, 'pageIndex': pageIndex, 'pageSize': pageSize,
            'type': assetType}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# Asset v2 — Email Templates (Emails 2.0)
# ============================================================================

def browseEmailTemplates2(token, workspaceId, folderId=None, status=None,
                          name=None, pageIndex=None, pageSize=None,
                          sortKey=None, sortOrder=None, includeArchived=None):
    """Browse Emails 2.0 email templates (Asset v2) in a workspace."""
    url = _base() + '/rest/asset/v2/emailtemplate/filter'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    params = {
        'workspaceId': workspaceId,
        'folderId': folderId,
        'status': status,
        'name': name,
        'pageIndex': pageIndex,
        'pageSize': pageSize,
        'sortKey': sortKey,
        'sortOrder': sortOrder,
        'includeArchived': includeArchived,
    }
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailTemplate2ById(token, templateId):
    """Get an Emails 2.0 email template by ID (Asset v2)."""
    url = _base() + f'/rest/asset/v2/emailtemplate/{templateId}'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def createEmailTemplate2(token, name, appData, description=None, data=None,
                         themeId=None, status=None, editorContext=None):
    """Create an Emails 2.0 email template (Asset v2). appData carries folder placement etc."""
    url = _base() + '/rest/asset/v2/emailtemplate'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {
        'name': name,
        'appData': appData,
        'description': description,
        'data': data,
        'themeId': themeId,
        'status': status,
        'editorContext': editorContext,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def updateEmailTemplate2(token, templateId, name=None, description=None,
                         data=None, themeId=None, status=None):
    """Update an Emails 2.0 email template (Asset v2): name, description, data, themeId, status."""
    url = _base() + f'/rest/asset/v2/emailtemplate/{templateId}/update'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {
        'name': name,
        'description': description,
        'data': data,
        'themeId': themeId,
        'status': status,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteEmailTemplate2(token, templateId):
    """Delete an Emails 2.0 email template (Asset v2)."""
    url = _base() + f'/rest/asset/v2/emailtemplate/{templateId}/delete'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    response = requests.post(url, headers=headers, json={}, timeout=30)
    return response.json()


def cloneEmailTemplate2(token, templateId, name, folderId, extra=None):
    """Clone an Emails 2.0 email template (Asset v2) into a folder under a new name."""
    url = _base() + '/rest/asset/v2/emailtemplate/clone'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    newAsset = {'name': name, 'folderId': folderId}
    if extra:
        newAsset.update(extra)
    body = {'assetId': templateId, 'newAsset': newAsset}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def transitionEmailTemplate2State(token, templateId, action):
    """Transition an Emails 2.0 email template's approval state (approve, unapprove, or discard)."""
    url = _base() + '/rest/asset/v2/emailtemplate/state/transition'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {'contentId': templateId, 'action': action}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getEmailTemplate2UsedBy(token, templateId, pageIndex=None, pageSize=None,
                            assetType=None):
    """List assets that use an Emails 2.0 email template (Asset v2 usedby)."""
    url = _base() + '/rest/asset/v2/emailtemplate/usedby'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {'assetId': templateId, 'pageIndex': pageIndex, 'pageSize': pageSize,
            'type': assetType}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# Asset v2 — Fragments (Emails 2.0)
# ============================================================================

def browseFragments(token, workspaceId, folderId=None, status=None, name=None,
                    fragmentType=None, pageIndex=None, pageSize=None,
                    sortKey=None, sortOrder=None, includeArchived=None):
    """Browse Emails 2.0 fragments (Asset v2) in a workspace."""
    url = _base() + '/rest/asset/v2/fragment/filter'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    params = {
        'workspaceId': workspaceId,
        'folderId': folderId,
        'status': status,
        'name': name,
        'fragmentType': fragmentType,
        'pageIndex': pageIndex,
        'pageSize': pageSize,
        'sortKey': sortKey,
        'sortOrder': sortOrder,
        'includeArchived': includeArchived,
    }
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getFragmentById(token, fragmentId):
    """Get an Emails 2.0 fragment by ID (Asset v2)."""
    url = _base() + f'/rest/asset/v2/fragment/{fragmentId}'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def createFragment(token, name, appData, settings, description=None, data=None,
                   themeId=None, status=None):
    """Create an Emails 2.0 fragment (Asset v2). appData carries folder placement; settings is required."""
    url = _base() + '/rest/asset/v2/fragment'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {
        'name': name,
        'appData': appData,
        'settings': settings,
        'description': description,
        'data': data,
        'themeId': themeId,
        'status': status,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def updateFragment(token, fragmentId, name=None, description=None, data=None,
                   settings=None, status=None):
    """Update an Emails 2.0 fragment (Asset v2): name, description, data, settings, status."""
    url = _base() + f'/rest/asset/v2/fragment/{fragmentId}/update'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {
        'name': name,
        'description': description,
        'data': data,
        'settings': settings,
        'status': status,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteFragment(token, fragmentId):
    """Delete an Emails 2.0 fragment (Asset v2)."""
    url = _base() + f'/rest/asset/v2/fragment/{fragmentId}/delete'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    response = requests.post(url, headers=headers, json={}, timeout=30)
    return response.json()


def cloneFragment(token, fragmentId, name, folderId, extra=None):
    """Clone an Emails 2.0 fragment (Asset v2) into a folder under a new name."""
    url = _base() + '/rest/asset/v2/fragment/clone'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    newAsset = {'name': name, 'folderId': folderId}
    if extra:
        newAsset.update(extra)
    body = {'assetId': fragmentId, 'newAsset': newAsset}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def transitionFragmentState(token, fragmentId, action):
    """Transition an Emails 2.0 fragment's approval state (approve, unapprove, or discard)."""
    url = _base() + '/rest/asset/v2/fragment/state/transition'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {'contentId': fragmentId, 'action': action}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getFragmentUsedBy(token, fragmentId, pageIndex=None, pageSize=None,
                      assetType=None):
    """List assets that use an Emails 2.0 fragment (Asset v2 usedby)."""
    url = _base() + '/rest/asset/v2/fragment/usedby'
    # Asset v2 (Emails 2.0) requires an x-app-type header; the API only checks
    # presence (any value passes the gate), then enforces the role's permissions.
    headers = {'Authorization': 'Bearer ' + token, 'x-app-type': 'ME'}
    body = {'assetId': fragmentId, 'pageIndex': pageIndex, 'pageSize': pageSize,
            'type': assetType}
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


# ============================================================================
# User Management (/userservice/management/v1; may return raw arrays)
# ============================================================================

def listUsers(token, pageSize=None, pageOffset=None):
    """List all users on the instance (User Management API)."""
    url = _base() + '/userservice/management/v1/users/allusers.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'pageSize': pageSize, 'pageOffset': pageOffset}
    params = {k: v for k, v in params.items() if v is not None}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getUserById(token, userId):
    """Get a user by ID (the user's email-format ID) (User Management API)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/user.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def listUserRoles(token):
    """List all user roles defined on the instance (User Management API)."""
    url = _base() + '/userservice/management/v1/users/roles.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def listWorkspaces(token):
    """List all workspaces on the instance (User Management API)."""
    url = _base() + '/userservice/management/v1/users/workspaces.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getUserRoles(token, userId):
    """Get the role/workspace assignments for a user (User Management API)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/roles.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def addUserRoles(token, userId, roleWorkspaces):
    """Add role/workspace assignments to a user (list of {accessRoleId, workspaceId} dicts)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/roles/create.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'input': roleWorkspaces}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def removeUserRoles(token, userId, roleWorkspaces):
    """Remove role/workspace assignments from a user (list of {accessRoleId, workspaceId} dicts)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/roles/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {'input': roleWorkspaces}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def inviteUser(token, emailAddress, firstName, lastName, userRoleWorkspaces,
               apiOnly=None, expiresAt=None, reason=None, userid=None):
    """Invite a new user to the instance (User Management API)."""
    url = _base() + '/userservice/management/v1/users/invite.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {
        'emailAddress': emailAddress,
        'firstName': firstName,
        'lastName': lastName,
        'userRoleWorkspaces': userRoleWorkspaces,
        'apiOnly': apiOnly,
        'expiresAt': expiresAt,
        'reason': reason,
        'userid': userid,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def getUserInvite(token, userId):
    """Get the pending invite status for a user (User Management API)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/invite.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def deleteUserInvite(token, userId):
    """Delete (revoke) a pending user invite (User Management API)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/invite/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def updateUser(token, userId, firstName=None, lastName=None, emailAddress=None,
               apiOnly=None, expiresAt=None):
    """Update a user's attributes (firstName, lastName, emailAddress, apiOnly, expiresAt)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/update.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    body = {
        'firstName': firstName,
        'lastName': lastName,
        'emailAddress': emailAddress,
        'apiOnly': apiOnly,
        'expiresAt': expiresAt,
    }
    body = {k: v for k, v in body.items() if v is not None}
    response = requests.post(url, headers=headers, json=body, timeout=30)
    return response.json()


def deleteUser(token, userId):
    """Delete a user from the instance (User Management API)."""
    url = _base() + f'/userservice/management/v1/users/{userId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Aliases (short names without "Custom" for the custom_* tool name mapping)
# ============================================================================

def addActivities(token, activities):
    """Alias for addCustomActivities."""
    return addCustomActivities(token, activities)


def describeActivityType(token, apiName, draft=False):
    """Alias for describeCustomActivityType."""
    return describeCustomActivityType(token, apiName, draft)


def createActivityType(token, apiName, name, filterName, triggerName,
                       primaryAttribute, description=None):
    """Alias for createCustomActivityType."""
    return createCustomActivityType(token, apiName, name, filterName,
                                    triggerName, primaryAttribute, description)


def updateActivityType(token, apiName, name=None, filterName=None,
                       triggerName=None, primaryAttribute=None,
                       description=None, newApiName=None):
    """Alias for updateCustomActivityType."""
    return updateCustomActivityType(token, apiName, name, filterName,
                                    triggerName, primaryAttribute, description,
                                    newApiName)


def approveActivityType(token, apiName):
    """Alias for approveCustomActivityType."""
    return approveCustomActivityType(token, apiName)


def discardActivityTypeDraft(token, apiName):
    """Alias for discardCustomActivityTypeDraft."""
    return discardCustomActivityTypeDraft(token, apiName)


def deleteActivityType(token, apiName):
    """Alias for deleteCustomActivityType."""
    return deleteCustomActivityType(token, apiName)


def addActivityTypeAttributes(token, apiName, attributes):
    """Alias for addCustomActivityTypeAttributes."""
    return addCustomActivityTypeAttributes(token, apiName, attributes)


def updateActivityTypeAttributes(token, apiName, attributes):
    """Alias for updateCustomActivityTypeAttributes."""
    return updateCustomActivityTypeAttributes(token, apiName, attributes)


def deleteActivityTypeAttributes(token, apiName, attributes):
    """Alias for deleteCustomActivityTypeAttributes."""
    return deleteCustomActivityTypeAttributes(token, apiName, attributes)


def listObjects(token, names=None):
    """Alias for listCustomObjects."""
    return listCustomObjects(token, names)


def queryObjects(token, objectApiName, filterType=None, filterValues=None,
                 fields=None, batchSize=None, nextPageToken=None,
                 compoundFilter=None):
    """Alias for queryCustomObjects."""
    return queryCustomObjects(token, objectApiName, filterType, filterValues,
                              fields, batchSize, nextPageToken, compoundFilter)


def syncObjects(token, objectApiName, records, action="createOrUpdate",
                dedupeBy=None):
    """Alias for syncCustomObjects."""
    return syncCustomObjects(token, objectApiName, records, action, dedupeBy)


def deleteObjects(token, objectApiName, records, deleteBy="dedupeFields"):
    """Alias for deleteCustomObjects."""
    return deleteCustomObjects(token, objectApiName, records, deleteBy)


def describeObject(token, objectApiName):
    """Alias for describeCustomObject."""
    return describeCustomObject(token, objectApiName)


def listObjectTypes(token, names=None, state=None):
    """Alias for listCustomObjectTypes."""
    return listCustomObjectTypes(token, names, state)


def syncObjectType(token, apiName, displayName, action=None, pluralName=None,
                   description=None, showInLeadDetail=None):
    """Alias for syncCustomObjectType."""
    return syncCustomObjectType(token, apiName, displayName, action, pluralName,
                                description, showInLeadDetail)


def describeObjectType(token, apiName, state=None):
    """Alias for describeCustomObjectType."""
    return describeCustomObjectType(token, apiName, state)


def getObjectFieldTypes(token):
    """Alias for getCustomObjectFieldTypes."""
    return getCustomObjectFieldTypes(token)


def getObjectLinkableObjects(token):
    """Alias for getCustomObjectLinkableObjects."""
    return getCustomObjectLinkableObjects(token)


def getObjectTypeDependents(token, apiName):
    """Alias for getCustomObjectTypeDependents."""
    return getCustomObjectTypeDependents(token, apiName)


def addObjectTypeFields(token, apiName, fields):
    """Alias for addCustomObjectTypeFields."""
    return addCustomObjectTypeFields(token, apiName, fields)


def updateObjectTypeField(token, apiName, fieldApiName, updates):
    """Alias for updateCustomObjectTypeField."""
    return updateCustomObjectTypeField(token, apiName, fieldApiName, updates)


def deleteObjectTypeFields(token, apiName, fieldNames):
    """Alias for deleteCustomObjectTypeFields."""
    return deleteCustomObjectTypeFields(token, apiName, fieldNames)


def approveObjectType(token, apiName):
    """Alias for approveCustomObjectType."""
    return approveCustomObjectType(token, apiName)


def discardObjectTypeDraft(token, apiName):
    """Alias for discardCustomObjectTypeDraft."""
    return discardCustomObjectTypeDraft(token, apiName)


def deleteObjectType(token, apiName):
    """Alias for deleteCustomObjectType."""
    return deleteCustomObjectType(token, apiName)


def createObjectExportJob(token, objectApiName, fields, exportFilter,
                          exportFormat="CSV", columnHeaderNames=None):
    """Alias for createCustomObjectExportJob."""
    return createCustomObjectExportJob(token, objectApiName, fields,
                                       exportFilter, exportFormat,
                                       columnHeaderNames)


def enqueueObjectExportJob(token, objectApiName, exportId):
    """Alias for enqueueCustomObjectExportJob."""
    return enqueueCustomObjectExportJob(token, objectApiName, exportId)


def getObjectExportJobStatus(token, objectApiName, exportId):
    """Alias for getCustomObjectExportJobStatus."""
    return getCustomObjectExportJobStatus(token, objectApiName, exportId)


def getObjectExportFile(token, objectApiName, exportId):
    """Alias for getCustomObjectExportFile."""
    return getCustomObjectExportFile(token, objectApiName, exportId)


def cancelObjectExportJob(token, objectApiName, exportId):
    """Alias for cancelCustomObjectExportJob."""
    return cancelCustomObjectExportJob(token, objectApiName, exportId)


def listObjectExportJobs(token, objectApiName, status=None, batchSize=None,
                         nextPageToken=None):
    """Alias for listCustomObjectExportJobs."""
    return listCustomObjectExportJobs(token, objectApiName, status, batchSize,
                                      nextPageToken)


def importObjectsCsv(token, objectApiName, csvContent):
    """Alias for importCustomObjectsCsv."""
    return importCustomObjectsCsv(token, objectApiName, csvContent)


def getObjectImportStatus(token, objectApiName, batchId):
    """Alias for getCustomObjectImportStatus."""
    return getCustomObjectImportStatus(token, objectApiName, batchId)


def getObjectImportFailures(token, objectApiName, batchId):
    """Alias for getCustomObjectImportFailures."""
    return getCustomObjectImportFailures(token, objectApiName, batchId)


def getObjectImportWarnings(token, objectApiName, batchId):
    """Alias for getCustomObjectImportWarnings."""
    return getCustomObjectImportWarnings(token, objectApiName, batchId)


# Example usage
if __name__ == '__main__':
    token = getToken()
    print("Token obtained successfully")

    # Test activity types
    types = getActivityTypes(token)
    print(f"Activity types: {len(types.get('result', []))} found")

    # Test lead lookup
    result = lookupLead(token, "email", "test@example.com")
    print(json.dumps(result, indent=2))

# ============================================================================
# Landing Pages (core)
# ============================================================================

def browseLandingPages(token, maxReturn=20, offset=0, folderId=None, status=None):
    """Browse landing pages with optional filtering."""
    url = _base() + '/rest/asset/v1/landingPages.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'maxReturn': min(maxReturn, 200), 'offset': offset}
    if folderId:
        params['folder'] = json.dumps({"id": folderId, "type": "Folder"})
    if status:
        params['status'] = status
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLandingPageById(token, landingPageId):
    """Get a landing page by its ID."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getLandingPageByName(token, name):
    """Get a landing page by its name."""
    url = _base() + '/rest/asset/v1/landingPage/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, params={'name': name}, timeout=30)
    return response.json()


def getLandingPageContent(token, landingPageId, status=None):
    """Get the content sections of a landing page."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/content.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else {}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLandingPageFullContent(token, landingPageId, status=None):
    """Get the full rendered HTML of a landing page."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/fullContent.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'status': status} if status else {}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def updateLandingPage(token, landingPageId, name=None, description=None, title=None):
    """Update landing page metadata."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {}
    if name:
        data['name'] = name
    if description:
        data['description'] = description
    if title:
        data['title'] = title
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateLandingPageContentSection(token, landingPageId, contentId, contentType, value):
    """Update a content section of a landing page draft."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/content/{contentId}.json'
    headers = {'Authorization': 'Bearer ' + token,
               'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'type': contentType, 'value': value}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def approveLandingPage(token, landingPageId):
    """Approve a landing page draft."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/approveDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def unapproveLandingPage(token, landingPageId):
    """Unapprove a landing page, taking it offline."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/unapprove.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def discardLandingPageDraft(token, landingPageId):
    """Discard a landing page draft."""
    url = _base() + f'/rest/asset/v1/landingPage/{landingPageId}/discardDraft.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()
