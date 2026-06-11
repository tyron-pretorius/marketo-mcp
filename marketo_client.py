"""
Marketo REST API functions for the blended MCP server's custom tools.

Unlike marketo_functions.py (which reads credentials from the environment at
import time), every function here takes base_url and token as parameters so
credentials can vary per request. Covers only the operations the native
Marketo MCP server lacks.
"""

import json
from datetime import datetime, timedelta, timezone

import requests


def _bearer(token):
    return {'Authorization': 'Bearer ' + token}


def _is_token_error(payload):
    """Marketo returns HTTP 200 with errors[] codes 601/602 for bad/expired tokens."""
    if not isinstance(payload, dict):
        return False
    return any(e.get('code') in ('601', '602') for e in payload.get('errors') or [])


def call_with_token_retry(creds, tokens, fn):
    """Run fn(token); on a 601/602 token error, invalidate the cache and retry once.

    creds: MarketoCreds, tokens: TokenManager, fn: callable(token) -> dict
    """
    result = fn(tokens.get_token(creds))
    if _is_token_error(result):
        tokens.invalidate(creds)
        result = fn(tokens.get_token(creds))
    return result


# ============================================================================
# Lead Functions
# ============================================================================

def syncLeads(base_url, token, leads, action="createOrUpdate", lookupField="email",
              asyncProcessing=False, partitionName=None):
    """Create and/or update leads."""
    url = base_url + '/rest/v1/leads.json'
    headers = {**_bearer(token), 'Content-Type': 'application/json'}

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


def mergeLeads(base_url, token, winningLeadId, losingLeadIds, mergeInCRM=False):
    """Merge losing leads into a winning lead."""
    url = base_url + f'/rest/v1/leads/{winningLeadId}/merge.json'
    # Marketo rejects this endpoint with 612 "Invalid Content Type" unless a
    # JSON content type is sent, even though the request has no body.
    headers = {**_bearer(token), 'Content-Type': 'application/json'}
    params = {
        'leadIds': ','.join(map(str, losingLeadIds)),
        'mergeInCRM': str(mergeInCRM).lower(),
    }
    response = requests.post(url, headers=headers, params=params, timeout=30)
    return response.json()


def getLeadChanges(base_url, token, leadId, fields=None, daysBack=7):
    """Get data value changes for a lead."""
    sinceDate = (datetime.now(timezone.utc) - timedelta(days=daysBack)).strftime("%Y-%m-%dT%H:%M:%SZ")
    nextPageToken = getPagingToken(base_url, token, sinceDate)

    params = {
        'nextPageToken': nextPageToken,
        'leadIds': str(leadId),
        'fields': ','.join(fields or ['email', 'firstName', 'lastName', 'company']),
    }
    url = base_url + '/rest/v1/activities/leadchanges.json'
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


def getPagingToken(base_url, token, sinceDate):
    """Get a paging token for activity queries."""
    url = base_url + '/rest/v1/activities/pagingtoken.json'
    params = {'sinceDatetime': sinceDate}
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()['nextPageToken']


def lookupLead(base_url, token, filterType, filterValues, fields=None):
    """Look up lead(s) by filter."""
    url = base_url + '/rest/v1/leads.json'
    if isinstance(filterValues, list):
        filterValues = ','.join(map(str, filterValues))
    params = {
        'filterType': filterType,
        'filterValues': filterValues,
        'fields': fields or 'id,email,firstName,lastName,createdAt,updatedAt',
    }
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


def getLeadActivities(base_url, token, leadId, activityTypeIds=None, daysBack=7):
    """Fetch activities for a lead."""
    sinceDate = (datetime.now(timezone.utc) - timedelta(days=daysBack)).strftime("%Y-%m-%dT%H:%M:%SZ")
    nextPageToken = getPagingToken(base_url, token, sinceDate)

    url = base_url + '/rest/v1/activities.json'
    params = {
        'nextPageToken': nextPageToken,
        'leadIds': str(leadId),
        'activityTypeIds': ','.join(map(str, activityTypeIds or [1, 2, 6, 13, 37])),
    }
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


# ============================================================================
# Email Functions
# ============================================================================

def sendSampleEmail(base_url, token, emailId, emailAddress, textOnly=False, leadId=None):
    """Send a sample of an email to an address."""
    url = base_url + f'/rest/asset/v1/email/{emailId}/sendSample.json'
    headers = {**_bearer(token), 'Content-Type': 'application/x-www-form-urlencoded'}

    data = {'emailAddress': emailAddress}
    if textOnly:
        data['textOnly'] = 'true'
    if leadId:
        data['leadId'] = leadId

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def previewEmail(base_url, token, emailId, status=None, contentType="HTML", leadId=None):
    """Get the full rendered content of an email."""
    url = base_url + f'/rest/asset/v1/email/{emailId}/fullContent.json'
    params = {'type': contentType}
    if status:
        params['status'] = status
    if leadId:
        params['leadId'] = leadId
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


def getEmailCcFields(base_url, token):
    """Get the set of fields enabled for Email CC."""
    url = base_url + '/rest/asset/v1/email/ccFields.json'
    response = requests.get(url, headers=_bearer(token), timeout=30)
    return response.json()


# ============================================================================
# Landing Page Functions
# ============================================================================

def browseLandingPages(base_url, token, maxReturn=20, offset=0, folderId=None, status=None):
    """Browse landing pages with optional filtering."""
    url = base_url + '/rest/asset/v1/landingPages.json'
    params = {'maxReturn': min(maxReturn, 200), 'offset': offset}
    if folderId:
        params['folder'] = json.dumps({"id": folderId, "type": "Folder"})
    if status:
        params['status'] = status
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


def getLandingPageById(base_url, token, landingPageId):
    """Get a landing page by its ID."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}.json'
    response = requests.get(url, headers=_bearer(token), timeout=30)
    return response.json()


def getLandingPageByName(base_url, token, name):
    """Get a landing page by its name."""
    url = base_url + '/rest/asset/v1/landingPage/byName.json'
    response = requests.get(url, headers=_bearer(token), params={'name': name}, timeout=30)
    return response.json()


def getLandingPageContent(base_url, token, landingPageId, status=None):
    """Get the content sections of a landing page."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}/content.json'
    params = {}
    if status:
        params['status'] = status
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


def getLandingPageFullContent(base_url, token, landingPageId, status=None):
    """Get the full rendered HTML of a landing page."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}/fullContent.json'
    params = {}
    if status:
        params['status'] = status
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


def updateLandingPage(base_url, token, landingPageId, name=None, description=None, title=None):
    """Update landing page metadata."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}.json'
    headers = {**_bearer(token), 'Content-Type': 'application/x-www-form-urlencoded'}

    data = {}
    if name:
        data['name'] = name
    if description:
        data['description'] = description
    if title:
        data['title'] = title

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def updateLandingPageContentSection(base_url, token, landingPageId, contentId,
                                    contentType, value):
    """Update a content section of a landing page draft."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}/content/{contentId}.json'
    headers = {**_bearer(token), 'Content-Type': 'application/x-www-form-urlencoded'}

    data = {'type': contentType, 'value': value}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()


def approveLandingPage(base_url, token, landingPageId):
    """Approve a landing page draft."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}/approveDraft.json'
    response = requests.post(url, headers=_bearer(token), timeout=30)
    return response.json()


def unapproveLandingPage(base_url, token, landingPageId):
    """Unapprove a landing page."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}/unapproveDraft.json'
    response = requests.post(url, headers=_bearer(token), timeout=30)
    return response.json()


def discardLandingPageDraft(base_url, token, landingPageId):
    """Discard a landing page draft."""
    url = base_url + f'/rest/asset/v1/landingPage/{landingPageId}/discardDraft.json'
    response = requests.post(url, headers=_bearer(token), timeout=30)
    return response.json()


# ============================================================================
# Bulk Lead Import Functions
# ============================================================================

def importLeadsCsv(base_url, token, csvContent, lookupField="email", listId=None,
                   partitionName=None):
    """Start a bulk lead import job from CSV content. Returns a batchId."""
    url = base_url + '/bulk/v1/leads.json'
    params = {'format': 'csv', 'lookupField': lookupField}
    if listId:
        params['listId'] = listId
    if partitionName:
        params['partitionName'] = partitionName

    files = {'file': ('leads.csv', csvContent, 'text/csv')}
    response = requests.post(url, headers=_bearer(token), params=params, files=files, timeout=60)
    return response.json()


def getLeadImportFailures(base_url, token, batchId):
    """Get the failures file for a bulk lead import batch (CSV text)."""
    url = base_url + f'/bulk/v1/leads/batch/{batchId}/failures.json'
    response = requests.get(url, headers=_bearer(token), timeout=30)
    return response.text


def getLeadImportWarnings(base_url, token, batchId):
    """Get the warnings file for a bulk lead import batch (CSV text)."""
    url = base_url + f'/bulk/v1/leads/batch/{batchId}/warnings.json'
    response = requests.get(url, headers=_bearer(token), timeout=30)
    return response.text


# ============================================================================
# Program Member Functions
# ============================================================================

def queryProgramMembers(base_url, token, programId, filterType, filterValues, fields=None,
                        startAt=None, endAt=None):
    """Query program members with filtering."""
    url = base_url + f'/rest/v1/programs/{programId}/members.json'
    params = {'filterType': filterType, 'filterValues': filterValues}
    if fields:
        params['fields'] = fields
    if startAt:
        params['startAt'] = startAt
    if endAt:
        params['endAt'] = endAt
    response = requests.get(url, headers=_bearer(token), params=params, timeout=30)
    return response.json()


# ============================================================================
# Destructive / deactivation operations the native MCP omits
# ============================================================================

def deactivateSmartCampaign(base_url, token, campaignId):
    """Deactivate a smart campaign."""
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}/deactivate.json'
    response = requests.post(url, headers=_bearer(token), timeout=30)
    return response.json()


def deleteSmartCampaign(base_url, token, campaignId):
    """Delete a smart campaign."""
    url = base_url + f'/rest/asset/v1/smartCampaign/{campaignId}/delete.json'
    response = requests.post(url, headers=_bearer(token), timeout=30)
    return response.json()


def deleteProgram(base_url, token, programId):
    """Delete a program and all its child contents."""
    url = base_url + f'/rest/asset/v1/program/{programId}/delete.json'
    response = requests.post(url, headers=_bearer(token), timeout=30)
    return response.json()


def unapproveEmailProgram(base_url, token, programId):
    """Unapprove an Email Program."""
    url = base_url + f'/rest/asset/v1/program/{programId}/unapprove.json'
    response = requests.post(url, headers=_bearer(token), timeout=30)
    return response.json()


def deleteToken(base_url, token, folderId, name, tokenType, folderType="Folder"):
    """Delete a token from a folder or program."""
    url = base_url + f'/rest/asset/v1/folder/{folderId}/tokens/delete.json'
    headers = {**_bearer(token), 'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'name': name, 'type': tokenType, 'folderType': folderType}
    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.json()
