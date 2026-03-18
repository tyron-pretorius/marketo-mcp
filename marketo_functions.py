import requests
import json
import os
import time
import dotenv
from datetime import datetime, timedelta, timezone

dotenv.load_dotenv()

base_url = os.environ.get('MARKETO_BASE_URL')
client_id = os.environ.get('MARKETO_CLIENT_ID')
client_secret = os.environ.get('MARKETO_CLIENT_SECRET')

_token_cache = {"access_token": None, "expires_at": 0}


# Get an access token (cached, refreshes 60s before expiry)
def getToken():
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    response = requests.get(
        base_url + '/identity/oauth/token',
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
    url = base_url + '/rest/v1/activities/types.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getPagingToken(token, sinceDate):
    """Get a paging token for activity queries."""
    url = base_url + '/rest/v1/activities/pagingtoken.json'
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

    url = base_url + '/rest/v1/activities.json'
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

    url = base_url + '/rest/v1/activities/leadchanges.json'
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
    url = base_url + '/rest/v1/leads.json'
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


def describeLeads(token):
    """Get lead field metadata and schema information."""
    url = base_url + '/rest/v1/leads/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Email Functions
# ============================================================================

def getEmailById(token, emailId):
    """Get an email asset by its ID."""
    url = base_url + f'/rest/asset/v1/email/{emailId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getEmailByName(token, name, folderId=None):
    """Get an email asset by its name."""
    url = base_url + '/rest/asset/v1/email/byName.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {'name': name}
    if folderId:
        params['folder'] = json.dumps({"id": folderId, "type": "Folder"})

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def browseEmails(token, maxReturn=20, offset=0, status=None, folderId=None,
                 earliestUpdatedAt=None, latestUpdatedAt=None):
    """Browse email assets with optional filtering."""
    url = base_url + '/rest/asset/v1/emails.json'
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
    url = base_url + f'/rest/asset/v1/email/{emailId}/content.json'
    headers = {'Authorization': 'Bearer ' + token}

    params = {}
    if status:
        params['status'] = status

    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def getEmailCcFields(token):
    """Get the set of fields enabled for Email CC."""
    url = base_url + '/rest/asset/v1/email/ccFields.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def previewEmail(token, emailId, status=None, contentType="HTML", leadId=None):
    """Get a live preview of an email."""
    url = base_url + f'/rest/asset/v1/email/{emailId}/fullContent.json'
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
    url = base_url + '/rest/asset/v1/channels.json'
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
    url = base_url + '/rest/asset/v1/folder/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'name': name}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def browseFolders(token, maxReturn=20, offset=0, folderType="Folder"):
    """Browse folders in Marketo."""
    url = base_url + '/rest/asset/v1/folders.json'
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
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getSmartCampaignByName(token, name):
    """Get a smart campaign by its name."""
    url = base_url + '/rest/asset/v1/smartCampaign/byName.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'name': name}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def browseSmartCampaigns(token, maxReturn=20, offset=0, isActive=None, folderId=None,
                         earliestUpdatedAt=None, latestUpdatedAt=None):
    """Browse smart campaigns with optional filtering."""
    url = base_url + '/rest/asset/v1/smartCampaigns.json'
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
    url = base_url + '/rest/asset/v1/smartCampaigns.json'
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
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}.json'
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


def cloneSmartCampaign(token, campaignId, name, folderId, description=None):
    """Clone an existing smart campaign."""
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}/clone.json'
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


def scheduleBatchCampaign(token, campaignId, runAt=None, tokens=None, cloneToProgram=None):
    """Schedule a batch smart campaign."""
    url = base_url + f'/rest/v1/campaigns/{campaignId}/schedule.json'
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
    url = base_url + f'/rest/v1/campaigns/{campaignId}/trigger.json'
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
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}/activate.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deactivateSmartCampaign(token, campaignId):
    """Deactivate a smart campaign."""
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}/deactivate.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteSmartCampaign(token, campaignId):
    """Delete a smart campaign."""
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Program Functions
# ============================================================================

def getProgramById(token, programId):
    """Get a program by its ID."""
    url = base_url + f'/rest/asset/v1/program/{programId}.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def getProgramByName(token, name, includeTags=False, includeCosts=False):
    """Get a program by its name."""
    url = base_url + '/rest/asset/v1/program/byName.json'
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
    url = base_url + '/rest/asset/v1/programs.json'
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
    url = base_url + '/rest/asset/v1/programs.json'
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
    url = base_url + f'/rest/asset/v1/program/{programId}.json'
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
    url = base_url + f'/rest/asset/v1/program/{programId}/clone.json'
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
    url = base_url + f'/rest/asset/v1/program/{programId}/approve.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def unapproveEmailProgram(token, programId):
    """Unapprove an Email Program."""
    url = base_url + f'/rest/asset/v1/program/{programId}/unapprove.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


def deleteProgram(token, programId):
    """Delete a program and all its child contents."""
    url = base_url + f'/rest/asset/v1/program/{programId}/delete.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.post(url, headers=headers, timeout=30)
    return response.json()


# ============================================================================
# Program Member Functions
# ============================================================================

def describeProgramMembers(token):
    """Get program member field metadata and schema information."""
    url = base_url + '/rest/v1/programs/members/describe.json'
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get(url, headers=headers, timeout=30)
    return response.json()


def queryProgramMembers(token, programId, filterType, filterValues, fields=None,
                        startAt=None, endAt=None):
    """Query program members with filtering."""
    url = base_url + f'/rest/v1/programs/{programId}/members.json'
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
    url = base_url + f'/rest/asset/v1/folder/{folderId}/tokens.json'
    headers = {'Authorization': 'Bearer ' + token}
    params = {'folderType': folderType}
    response = requests.get(url, headers=headers, params=params, timeout=30)
    return response.json()


def createToken(token, folderId, name, tokenType, value, folderType="Folder"):
    """Create a new token."""
    url = base_url + f'/rest/asset/v1/folder/{folderId}/tokens.json'
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
    url = base_url + f'/rest/asset/v1/folder/{folderId}/tokens.json'
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
    url = base_url + f'/rest/asset/v1/folder/{folderId}/tokens/delete.json'
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