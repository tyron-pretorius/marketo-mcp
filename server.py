import os
import sys
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging for debugging and monitoring
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Marketo credentials from environment variables
MARKETO_CLIENT_ID = os.environ.get("MARKETO_CLIENT_ID")
MARKETO_CLIENT_SECRET = os.environ.get("MARKETO_CLIENT_SECRET")
MARKETO_BASE_URL = os.environ.get("MARKETO_BASE_URL")

# Initialize FastMCP server
try:
    from fastmcp import FastMCP
    mcp = FastMCP(name="MarketoMCPServer")
    FASTMCP_AVAILABLE = True
except ImportError:
    logger.warning("FastMCP not available. Install with: pip install fastmcp")
    FASTMCP_AVAILABLE = False

def validate_marketo_credentials() -> bool:
    """
    Validate that all required Marketo credentials are present in environment variables.
    
    Returns:
        bool: True if all credentials are present, False otherwise
    """
    missing_credentials = []
    
    if not MARKETO_CLIENT_ID:
        missing_credentials.append("MARKETO_CLIENT_ID")
    if not MARKETO_CLIENT_SECRET:
        missing_credentials.append("MARKETO_CLIENT_SECRET")
    if not MARKETO_BASE_URL:
        missing_credentials.append("MARKETO_BASE_URL")
    
    if missing_credentials:
        logger.error(f"Missing required Marketo credentials: {', '.join(missing_credentials)}")
        logger.error("Please set these environment variables before running the server.")
        return False
    
    return True

def get_marketo_token() -> Optional[str]:
    """
    Obtain a Marketo OAuth access token using Client ID/Secret.
    
    This function implements 2-legged OAuth 2.0 authentication with Marketo.
    It calls the identity endpoint to exchange client credentials for an access token.
    
    Returns:
        Optional[str]: The access token if successful, None if authentication fails
        
    Raises:
        requests.RequestException: If the HTTP request fails
        ValueError: If the response doesn't contain a valid access token
    """
    # Validate credentials before attempting authentication
    if not validate_marketo_credentials():
        return None
    
    # Construct the identity URL for OAuth token exchange
    identity_url = f"{MARKETO_BASE_URL}/identity/oauth/token"
    
    # OAuth 2.0 client credentials flow parameters
    params = {
        "grant_type": "client_credentials",
        "client_id": MARKETO_CLIENT_ID,
        "client_secret": MARKETO_CLIENT_SECRET
    }
    
    try:
        logger.info("Attempting to authenticate with Marketo API...")
        
        # Make the OAuth token request
        # Using timeout to prevent hanging requests
        response = requests.get(identity_url, params=params, timeout=30)
        
        # Check for HTTP errors and raise exception if needed
        response.raise_for_status()
        
        # Parse the JSON response
        data = response.json()
        
        # Extract the access token from the response
        access_token = data.get("access_token")
        
        if not access_token:
            logger.error("No access_token found in Marketo response")
            logger.error(f"Response data: {data}")
            raise ValueError("Invalid response: missing access_token")
        
        # Log successful authentication (without exposing the token)
        logger.info("Successfully obtained Marketo access token")
        
        # Log token expiry information if available
        expires_in = data.get("expires_in")
        if expires_in:
            logger.info(f"Token expires in {expires_in} seconds")
        
        return access_token
        
    except requests.RequestException as e:
        logger.error(f"HTTP request failed during Marketo authentication: {e}")
        raise
    except ValueError as e:
        logger.error(f"Invalid response from Marketo: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during Marketo authentication: {e}")
        raise

def test_marketo_authentication() -> bool:
    """
    Test function to verify Marketo authentication is working.
    
    Returns:
        bool: True if authentication succeeds, False otherwise
    """
    try:
        token = get_marketo_token()
        if token:
            logger.info("✅ Marketo authentication test PASSED")
            return True
        else:
            logger.error("❌ Marketo authentication test FAILED: No token received")
            return False
    except Exception as e:
        logger.error(f"❌ Marketo authentication test FAILED: {e}")
        return False

def get_activity_types(headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Get available activity types from Marketo.
    
    Args:
        headers: HTTP headers with Bearer token
        
    Returns:
        Dict[str, Any]: Activity types data or error information
    """
    try:
        types_url = f"{MARKETO_BASE_URL}/rest/v1/activities/types.json"
        
        logger.info("Requesting activity types from Marketo")
        response = requests.get(types_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        result_count = len(data.get("result", []))
        logger.info(f"Successfully retrieved {result_count} activity types")
        
        return data
        
    except requests.RequestException as e:
        logger.error(f"Failed to get activity types: {e}")
        return {"error": f"Failed to get activity types: {str(e)}"}

def get_paging_token(since_datetime: str, headers: Dict[str, str]) -> Optional[str]:
    """
    Get a paging token from Marketo for the specified start datetime.
    
    Args:
        since_datetime: ISO8601 formatted datetime string
        headers: HTTP headers with Bearer token
        
    Returns:
        Optional[str]: The next page token if successful, None otherwise
    """
    try:
        paging_url = f"{MARKETO_BASE_URL}/rest/v1/activities/pagingtoken.json"
        paging_params = {"sinceDatetime": since_datetime}
        
        logger.info(f"Requesting paging token for activities since {since_datetime}")
        response = requests.get(paging_url, headers=headers, params=paging_params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        next_page_token = data.get("nextPageToken")
        
        if not next_page_token:
            logger.error("No paging token returned from Marketo")
            return None
            
        logger.info("Successfully obtained paging token")
        return next_page_token
        
    except requests.RequestException as e:
        logger.error(f"Failed to get paging token: {e}")
        return None

def fetch_lead_activities(lead_id: int, activity_type_ids: Optional[List[int]] = None, days_back: int = 7) -> Dict[str, Any]:
    """
    Fetch recent activities for the given lead ID from Marketo.
    
    Args:
        lead_id: The Marketo lead ID to fetch activities for
        days_back: Number of days back to fetch activities (default: 7)
        
    Returns:
        Dict[str, Any]: Marketo activities data or error information
    """
    try:
        # Get fresh OAuth token
        token = get_marketo_token()
        if not token:
            return {"error": "Failed to obtain access token"}
        
        # Prepare headers with Bearer token for Marketo API calls
        headers = {"Authorization": f"Bearer {token}"}
        
        # Define timeframe: specified days back from now
        since_time = datetime.now(timezone.utc) - timedelta(days=days_back)
        since_str = since_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        logger.info(f"Fetching activities for lead {lead_id} since {since_str}")
        
        # 1. Get paging token for the start datetime
        next_page_token = get_paging_token(since_str, headers)
        if not next_page_token:
            return {"error": "Failed to obtain paging token"}
        
        # 2. Get activities using the paging token and leadId filter
        activities_url = f"{MARKETO_BASE_URL}/rest/v1/activities.json"
        activities_params = {
            "nextPageToken": next_page_token,
            "leadIds": str(lead_id)
        }
        
        # Add activity type IDs if provided (required by Marketo API)
        if activity_type_ids:
            activities_params["activityTypeIds"] = ",".join(map(str, activity_type_ids))
        else:
            # Use common activity types if none specified
            common_types = [1, 2, 6, 13, 37]  # Visit Webpage, Fill Form, Send Email, Data Change, Deleted Lead
            activities_params["activityTypeIds"] = ",".join(map(str, common_types))
        
        logger.info(f"Requesting activities for lead {lead_id}")
        response = requests.get(activities_url, headers=headers, params=activities_params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Log success and return data
        result_count = len(data.get("result", []))
        logger.info(f"Successfully retrieved {result_count} activities for lead {lead_id}")
        
        return data
        
    except requests.RequestException as e:
        logger.error(f"HTTP request failed while fetching activities: {e}")
        return {"error": f"HTTP request failed: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error while fetching activities: {e}")
        return {"error": f"Unexpected error: {str(e)}"}

def test_lead_activities(lead_id: int = 12345) -> bool:
    """
    Test function to verify lead activities retrieval is working.
    
    Args:
        lead_id: Test lead ID (default: 12345)
        
    Returns:
        bool: True if activities retrieval succeeds, False otherwise
    """
    try:
        print(f"Testing lead activities retrieval for lead ID: {lead_id}")
        result = fetch_lead_activities(lead_id, activity_type_ids=[1, 2, 6], days_back=7)
        
        if "error" in result:
            print(f"❌ Lead activities test FAILED: {result['error']}")
            return False
        
        activities = result.get("result", [])
        print(f"✅ Lead activities test PASSED: Retrieved {len(activities)} activities")
        
        # Show a sample activity if available
        if activities:
            sample_activity = activities[0]
            print(f"   Sample activity: {sample_activity.get('activityTypeId', 'Unknown type')} at {sample_activity.get('activityDate', 'Unknown date')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Lead activities test FAILED: {e}")
        return False

def test_activity_types() -> bool:
    """
    Test function to verify activity types retrieval is working.
    
    Returns:
        bool: True if activity types retrieval succeeds, False otherwise
    """
    try:
        print("Testing activity types retrieval...")
        token = get_marketo_token()
        if not token:
            print("❌ Activity types test FAILED: No token received")
            return False
        
        headers = {"Authorization": f"Bearer {token}"}
        result = get_activity_types(headers)
        
        if "error" in result:
            print(f"❌ Activity types test FAILED: {result['error']}")
            return False
        
        activity_types = result.get("result", [])
        print(f"✅ Activity types test PASSED: Retrieved {len(activity_types)} activity types")
        
        # Show a sample activity type if available
        if activity_types:
            sample_type = activity_types[0]
            print(f"   Sample type: {sample_type.get('name', 'Unknown')} (ID: {sample_type.get('id', 'Unknown')})")
        
        return True
        
    except Exception as e:
        print(f"❌ Activity types test FAILED: {e}")
        return False

# MCP Tools for Marketo Activities API
if FASTMCP_AVAILABLE:
    @mcp.tool
    def get_activity_types() -> Dict[str, Any]:
        """
        Get available activity types from Marketo.
        
        Returns:
            Dict[str, Any]: Marketo activity types data including definitions and attributes
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            return get_activity_types(headers)
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get activity types: {str(e)}"}

    @mcp.tool
    def get_lead_by_email(email: str) -> Dict[str, Any]:
        """
        Get a lead by email address from Marketo.
        
        Args:
            email: The email address to search for
            
        Returns:
            Dict[str, Any]: Lead data including ID, email, and other fields
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get lead by email
            lead_url = f"{MARKETO_BASE_URL}/rest/v1/leads.json"
            params = {
                "filterType": "email",
                "filterValues": email,
                "fields": "id,email,firstName,lastName,createdAt,updatedAt"
            }
            
            logger.info(f"Requesting lead with email: {email}")
            response = requests.get(lead_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} leads for email: {email}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get lead by email: {str(e)}"}

    @mcp.tool
    def get_lead_activities_by_email(email: str, activity_type_ids: Optional[List[int]] = None, days_back: int = 7) -> Dict[str, Any]:
        """
        Get recent activities for a lead by email address from Marketo.
        
        Args:
            email: The email address to fetch activities for
            activity_type_ids: Optional list of activity type IDs to filter by (up to 10)
            days_back: Number of days back to fetch activities (default: 7)
            
        Returns:
            Dict[str, Any]: Marketo activities data including result list and metadata
        """
        try:
            # First, get the lead by email
            lead_result = get_lead_by_email(email)
            if "error" in lead_result:
                return lead_result
            
            leads = lead_result.get("result", [])
            if not leads:
                return {"error": f"No lead found with email: {email}"}
            
            # Get the first lead (should be unique by email)
            lead_id = leads[0].get("id")
            if not lead_id:
                return {"error": "No lead ID found in response"}
            
            logger.info(f"Found lead ID {lead_id} for email {email}")
            
            # Now fetch activities for this lead
            return fetch_lead_activities(lead_id, activity_type_ids, days_back)
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to fetch activities by email: {str(e)}"}

    @mcp.tool
    def get_lead_activities(lead_id: int = 12345, activity_type_ids: Optional[List[int]] = None, days_back: int = 7) -> Dict[str, Any]:
        """
        Get recent activities for a lead from Marketo.
        
        Args:
            lead_id: The Marketo lead ID to fetch activities for (default: 12345)
            activity_type_ids: Optional list of activity type IDs to filter by (up to 10)
            days_back: Number of days back to fetch activities (default: 7)
            
        Returns:
            Dict[str, Any]: Marketo activities data including result list and metadata
        """
        try:
            return fetch_lead_activities(lead_id, activity_type_ids, days_back)
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to fetch activities: {str(e)}"}

    @mcp.tool
    def get_lead_changes(lead_id: int = 12345, fields: Optional[List[str]] = None, days_back: int = 7) -> Dict[str, Any]:
        """
        Get data value changes for a lead from Marketo (specialized for Data Value Change activities).
        
        Args:
            lead_id: The Marketo lead ID to fetch changes for (default: 12345)
            fields: Optional list of field names to track changes for
            days_back: Number of days back to fetch changes (default: 7)
            
        Returns:
            Dict[str, Any]: Marketo lead changes data including field changes
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Define timeframe
            since_time = datetime.now(timezone.utc) - timedelta(days=days_back)
            since_str = since_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Get paging token
            next_page_token = get_paging_token(since_str, headers)
            if not next_page_token:
                return {"error": "Failed to obtain paging token"}
            
            # Get lead changes
            changes_url = f"{MARKETO_BASE_URL}/rest/v1/activities/leadchanges.json"
            changes_params = {
                "nextPageToken": next_page_token,
                "leadIds": str(lead_id)
            }
            
            if fields:
                changes_params["fields"] = ",".join(fields)
            
            response = requests.get(changes_url, headers=headers, params=changes_params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} lead changes for lead {lead_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to fetch lead changes: {str(e)}"}

    @mcp.tool
    def get_email_by_id(email_id: int) -> Dict[str, Any]:
        """
        Get an email asset by its ID from Marketo.
        
        Args:
            email_id: The Marketo email asset ID
            
        Returns:
            Dict[str, Any]: Email asset data including metadata, subject, from info, and status
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get email by ID
            email_url = f"{MARKETO_BASE_URL}/rest/asset/v1/email/{email_id}.json"
            
            logger.info(f"Requesting email with ID: {email_id}")
            response = requests.get(email_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully retrieved email: {data.get('result', [{}])[0].get('name', 'Unknown')}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get email by ID: {str(e)}"}

    @mcp.tool
    def get_email_by_name(name: str, folder_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get an email asset by its name from Marketo.
        
        Args:
            name: The name of the email asset
            folder_id: Optional folder ID to search within a specific folder
            
        Returns:
            Dict[str, Any]: Email asset data including metadata, subject, from info, and status
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {"name": name}
            if folder_id:
                params["folder"] = f'{{"id":{folder_id},"type":"Folder"}}'
            
            # Get email by name
            email_url = f"{MARKETO_BASE_URL}/rest/asset/v1/email/byName.json"
            
            logger.info(f"Requesting email with name: {name}")
            response = requests.get(email_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully retrieved email: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get email by name: {str(e)}"}

    @mcp.tool
    def browse_emails(max_return: int = 20, offset: int = 0, status: Optional[str] = None, 
                     folder_id: Optional[int] = None, earliest_updated_at: Optional[str] = None,
                     latest_updated_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Browse email assets in Marketo with optional filtering.
        
        Args:
            max_return: Maximum number of results to return (default: 20, max: 200)
            offset: Number of results to skip for pagination (default: 0)
            status: Filter by status - "approved" or "draft" (optional)
            folder_id: Filter by folder ID (optional)
            earliest_updated_at: Filter by earliest update date in ISO8601 format (optional)
            latest_updated_at: Filter by latest update date in ISO8601 format (optional)
            
        Returns:
            Dict[str, Any]: List of email assets matching the criteria
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {
                "maxReturn": min(max_return, 200),  # Ensure max is 200
                "offset": offset
            }
            
            if status:
                params["status"] = status
            if folder_id:
                params["folder"] = f'{{"id":{folder_id},"type":"Folder"}}'
            if earliest_updated_at:
                params["earliestUpdatedAt"] = earliest_updated_at
            if latest_updated_at:
                params["latestUpdatedAt"] = latest_updated_at
            
            # Browse emails
            emails_url = f"{MARKETO_BASE_URL}/rest/asset/v1/emails.json"
            
            logger.info(f"Browsing emails with max_return={max_return}, offset={offset}")
            response = requests.get(emails_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} emails")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to browse emails: {str(e)}"}

    @mcp.tool
    def get_email_content(email_id: int, status: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the content sections of an email asset from Marketo.
        
        Args:
            email_id: The Marketo email asset ID
            status: Filter by status - "approved" or "draft" (optional, defaults to approved if available)
            
        Returns:
            Dict[str, Any]: Email content sections including HTML and text versions
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {}
            if status:
                params["status"] = status
            
            # Get email content
            content_url = f"{MARKETO_BASE_URL}/rest/asset/v1/email/{email_id}/content.json"
            
            logger.info(f"Requesting content for email ID: {email_id}")
            response = requests.get(content_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} content sections for email {email_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get email content: {str(e)}"}

    @mcp.tool
    def get_email_cc_fields() -> Dict[str, Any]:
        """
        Get the set of fields enabled for Email CC in the Marketo instance.
        
        Returns:
            Dict[str, Any]: Available CC fields data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get email CC fields
            cc_fields_url = f"{MARKETO_BASE_URL}/rest/asset/v1/email/ccFields.json"
            
            logger.info("Requesting email CC fields")
            response = requests.get(cc_fields_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} CC fields")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get email CC fields: {str(e)}"}

    @mcp.tool
    def preview_email(email_id: int, status: Optional[str] = None, content_type: str = "HTML", 
                     lead_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get a live preview of an email as it would be sent to a recipient.
        Note: This endpoint only works with Version 1.0 Emails.
        
        Args:
            email_id: The Marketo email asset ID
            status: Filter by status - "approved" or "draft" (optional, defaults to approved if available)
            content_type: Content type - "HTML" or "Text" (default: "HTML")
            lead_id: Optional lead ID to preview the email as though received by that lead
            
        Returns:
            Dict[str, Any]: Email preview content
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {"type": content_type}
            if status:
                params["status"] = status
            if lead_id:
                params["leadId"] = lead_id
            
            # Get email preview
            preview_url = f"{MARKETO_BASE_URL}/rest/asset/v1/email/{email_id}/fullContent.json"
            
            logger.info(f"Requesting preview for email ID: {email_id}")
            response = requests.get(preview_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully retrieved preview for email {email_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to preview email: {str(e)}"}

    # Folder Tools
    @mcp.tool
    def browse_folders(max_return: int = 20, offset: int = 0, folder_type: str = "Folder") -> Dict[str, Any]:
        """
        Browse folders in Marketo to find valid folder IDs for use with other operations.
        
        Args:
            max_return: Maximum number of results to return (default: 20, max: 200)
            offset: Number of results to skip for pagination (default: 0)
            folder_type: Type of folder to browse - "Folder" or "Program" (default: "Folder")
            
        Returns:
            Dict[str, Any]: List of folders with their IDs, names, and metadata
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {
                "maxReturn": min(max_return, 200),  # Ensure max is 200
                "offset": offset,
                "type": folder_type
            }
            
            # Browse folders
            folders_url = f"{MARKETO_BASE_URL}/rest/asset/v1/folders.json"
            
            logger.info(f"Browsing {folder_type} folders with max_return={max_return}, offset={offset}")
            response = requests.get(folders_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} {folder_type} folders")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to browse folders: {str(e)}"}

    # Smart Campaign Tools
    @mcp.tool
    def get_smart_campaign_by_id(campaign_id: int) -> Dict[str, Any]:
        """
        Get a smart campaign by its ID from Marketo.
        
        Args:
            campaign_id: The Marketo smart campaign ID
            
        Returns:
            Dict[str, Any]: Smart campaign data including metadata, status, type, and configuration
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get smart campaign by ID
            campaign_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaign/{campaign_id}.json"
            
            logger.info(f"Requesting smart campaign with ID: {campaign_id}")
            response = requests.get(campaign_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully retrieved smart campaign: {data.get('result', [{}])[0].get('name', 'Unknown')}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get smart campaign by ID: {str(e)}"}

    @mcp.tool
    def get_smart_campaign_by_name(name: str) -> Dict[str, Any]:
        """
        Get a smart campaign by its name from Marketo.
        
        Args:
            name: The name of the smart campaign
            
        Returns:
            Dict[str, Any]: Smart campaign data including metadata, status, type, and configuration
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get smart campaign by name
            campaign_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaign/byName.json"
            params = {"name": name}
            
            logger.info(f"Requesting smart campaign with name: {name}")
            response = requests.get(campaign_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully retrieved smart campaign: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get smart campaign by name: {str(e)}"}

    @mcp.tool
    def browse_smart_campaigns(max_return: int = 20, offset: int = 0, is_active: Optional[bool] = None,
                              folder_id: Optional[int] = None, earliest_updated_at: Optional[str] = None,
                              latest_updated_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Browse smart campaigns in Marketo with optional filtering.
        
        Args:
            max_return: Maximum number of results to return (default: 20, max: 200)
            offset: Number of results to skip for pagination (default: 0)
            is_active: Filter by active status for trigger campaigns (optional)
            folder_id: Filter by folder ID (optional) - must be a valid folder ID that exists in Marketo
            earliest_updated_at: Filter by earliest update date in ISO8601 format without milliseconds (optional)
            latest_updated_at: Filter by latest update date in ISO8601 format without milliseconds (optional)
            
        Returns:
            Dict[str, Any]: List of smart campaigns matching the criteria
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {
                "maxReturn": min(max_return, 200),  # Ensure max is 200
                "offset": offset
            }
            
            if is_active is not None:
                params["isActive"] = str(is_active).lower()
            
            # Handle folder parameter with proper JSON formatting
            if folder_id:
                # Validate folder_id is a positive integer
                if not isinstance(folder_id, int) or folder_id <= 0:
                    return {"error": f"Invalid folder_id: {folder_id}. Must be a positive integer."}
                
                # Format folder parameter as proper JSON object
                import json
                folder_obj = {"id": folder_id, "type": "Folder"}
                params["folder"] = json.dumps(folder_obj)
                logger.info(f"Using folder filter: {params['folder']}")
            
            if earliest_updated_at:
                params["earliestUpdatedAt"] = earliest_updated_at
            if latest_updated_at:
                params["latestUpdatedAt"] = latest_updated_at
            
            # Browse smart campaigns
            campaigns_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaigns.json"
            
            logger.info(f"Browsing smart campaigns with max_return={max_return}, offset={offset}")
            if folder_id:
                logger.info(f"Filtering by folder_id: {folder_id}")
            
            response = requests.get(campaigns_url, headers=headers, params=params, timeout=30)
            
            # Handle specific validation errors
            if response.status_code == 400:
                try:
                    error_data = response.json()
                    if "errors" in error_data:
                        error_messages = [error.get("message", "Unknown error") for error in error_data["errors"]]
                        if any("not valid under any of the given schemas" in msg for msg in error_messages):
                            return {"error": f"Invalid folder_id: {folder_id}. This folder ID does not exist or is not accessible. Please verify the folder ID exists in your Marketo instance."}
                        return {"error": f"Validation error: {'; '.join(error_messages)}"}
                except:
                    pass
            
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} smart campaigns")
            
            return data
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.error(f"Bad request error: {e}")
                return {"error": f"Bad request: {str(e)}. Please check your parameters, especially folder_id if provided."}
            else:
                logger.error(f"HTTP error: {e}")
                return {"error": f"HTTP error: {str(e)}"}
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to browse smart campaigns: {str(e)}"}

    @mcp.tool
    def create_smart_campaign(name: str, folder_id: int, description: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new smart campaign in Marketo.
        
        Args:
            name: The name of the smart campaign to create
            folder_id: The folder ID where the smart campaign will be created
            description: Optional description for the smart campaign (max 2000 characters)
            
        Returns:
            Dict[str, Any]: Created smart campaign data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Build form data
            form_data = {
                "name": name,
                "folder": f'{{"type": "folder","id": {folder_id}}}'
            }
            
            if description:
                form_data["description"] = description
            
            # Create smart campaign
            create_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaigns.json"
            
            logger.info(f"Creating smart campaign: {name}")
            response = requests.post(create_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully created smart campaign: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to create smart campaign: {str(e)}"}

    @mcp.tool
    def update_smart_campaign(campaign_id: int, name: Optional[str] = None, 
                             description: Optional[str] = None, folder_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Update an existing smart campaign in Marketo.
        
        Args:
            campaign_id: The ID of the smart campaign to update
            name: New name for the smart campaign (optional)
            description: New description for the smart campaign (optional, max 2000 characters)
            folder_id: New folder ID for the smart campaign (optional)
            
        Returns:
            Dict[str, Any]: Updated smart campaign data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Build form data
            form_data = {}
            if name:
                form_data["name"] = name
            if description:
                form_data["description"] = description
            if folder_id:
                form_data["folder"] = f'{{"type": "folder","id": {folder_id}}}'
            
            # Update smart campaign
            update_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaign/{campaign_id}.json"
            
            logger.info(f"Updating smart campaign ID: {campaign_id}")
            response = requests.post(update_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully updated smart campaign ID: {campaign_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to update smart campaign: {str(e)}"}

    @mcp.tool
    def clone_smart_campaign(campaign_id: int, name: str, folder_id: int, 
                            description: Optional[str] = None) -> Dict[str, Any]:
        """
        Clone an existing smart campaign in Marketo.
        
        Args:
            campaign_id: The ID of the smart campaign to clone
            name: The name for the new cloned smart campaign
            folder_id: The folder ID where the cloned smart campaign will be created
            description: Optional description for the cloned smart campaign (max 2000 characters)
            
        Returns:
            Dict[str, Any]: Cloned smart campaign data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Build form data
            form_data = {
                "name": name,
                "folder": f'{{"type": "folder","id": {folder_id}}}'
            }
            
            if description:
                form_data["description"] = description
            
            # Clone smart campaign
            clone_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaign/{campaign_id}/clone.json"
            
            logger.info(f"Cloning smart campaign ID: {campaign_id} to: {name}")
            response = requests.post(clone_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully cloned smart campaign to: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to clone smart campaign: {str(e)}"}

    @mcp.tool
    def schedule_batch_campaign(campaign_id: int, run_at: Optional[str] = None, 
                               tokens: Optional[List[Dict[str, str]]] = None,
                               clone_to_program: Optional[str] = None) -> Dict[str, Any]:
        """
        Schedule a batch smart campaign to run at a specific time.
        
        Args:
            campaign_id: The ID of the batch smart campaign to schedule
            run_at: ISO8601 datetime when to run the campaign (optional, defaults to 5 minutes from now)
            tokens: Optional list of My Tokens to override program tokens (max 100 tokens)
            clone_to_program: Optional program name to clone the campaign to (limited to 20 calls per day)
            
        Returns:
            Dict[str, Any]: Scheduling confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            # Build request body
            request_body = {"input": {}}
            
            if run_at:
                request_body["input"]["runAt"] = run_at
            if tokens:
                request_body["input"]["tokens"] = tokens
            if clone_to_program:
                request_body["input"]["cloneToProgram"] = clone_to_program
            
            # Schedule batch campaign
            schedule_url = f"{MARKETO_BASE_URL}/rest/v1/campaigns/{campaign_id}/schedule.json"
            
            logger.info(f"Scheduling batch campaign ID: {campaign_id}")
            response = requests.post(schedule_url, headers=headers, json=request_body, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully scheduled batch campaign ID: {campaign_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to schedule batch campaign: {str(e)}"}

    @mcp.tool
    def trigger_campaign(campaign_id: int, lead_ids: List[int], 
                        tokens: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """
        Trigger a smart campaign for specific leads.
        The campaign must have a "Campaign is Requested" trigger with "Web Service API" as the source.
        
        Args:
            campaign_id: The ID of the trigger smart campaign
            lead_ids: List of lead IDs to trigger the campaign for (max 100 leads)
            tokens: Optional list of My Tokens to override program tokens (max 100 tokens)
            
        Returns:
            Dict[str, Any]: Trigger confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            
            # Build request body
            request_body = {
                "input": {
                    "leads": [{"id": lead_id} for lead_id in lead_ids[:100]]  # Limit to 100 leads
                }
            }
            
            if tokens:
                request_body["input"]["tokens"] = tokens[:100]  # Limit to 100 tokens
            
            # Trigger campaign
            trigger_url = f"{MARKETO_BASE_URL}/rest/v1/campaigns/{campaign_id}/trigger.json"
            
            logger.info(f"Triggering campaign ID: {campaign_id} for {len(lead_ids)} leads")
            response = requests.post(trigger_url, headers=headers, json=request_body, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully triggered campaign ID: {campaign_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to trigger campaign: {str(e)}"}

    @mcp.tool
    def activate_smart_campaign(campaign_id: int) -> Dict[str, Any]:
        """
        Activate a smart campaign in Marketo.
        The campaign must be deactivated and have at least one trigger and one flow step.
        
        Args:
            campaign_id: The ID of the smart campaign to activate
            
        Returns:
            Dict[str, Any]: Activation confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Activate smart campaign
            activate_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaign/{campaign_id}/activate.json"
            
            logger.info(f"Activating smart campaign ID: {campaign_id}")
            response = requests.post(activate_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully activated smart campaign ID: {campaign_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to activate smart campaign: {str(e)}"}

    @mcp.tool
    def deactivate_smart_campaign(campaign_id: int) -> Dict[str, Any]:
        """
        Deactivate a smart campaign in Marketo.
        The campaign must be activated.
        
        Args:
            campaign_id: The ID of the smart campaign to deactivate
            
        Returns:
            Dict[str, Any]: Deactivation confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Deactivate smart campaign
            deactivate_url = f"{MARKETO_BASE_URL}/rest/asset/v1/smartCampaign/{campaign_id}/deactivate.json"
            
            logger.info(f"Deactivating smart campaign ID: {campaign_id}")
            response = requests.post(deactivate_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully deactivated smart campaign ID: {campaign_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to deactivate smart campaign: {str(e)}"}

    # Program Tools
    @mcp.tool
    def get_program_by_id(program_id: int) -> Dict[str, Any]:
        """
        Get a program by its ID from Marketo.
        
        Args:
            program_id: The Marketo program ID
            
        Returns:
            Dict[str, Any]: Program data including metadata, type, channel, status, and tags
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get program by ID
            program_url = f"{MARKETO_BASE_URL}/rest/asset/v1/program/{program_id}.json"
            
            logger.info(f"Requesting program with ID: {program_id}")
            response = requests.get(program_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully retrieved program: {data.get('result', [{}])[0].get('name', 'Unknown')}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get program by ID: {str(e)}"}

    @mcp.tool
    def get_program_by_name(name: str, include_tags: bool = False, include_costs: bool = False) -> Dict[str, Any]:
        """
        Get a program by its name from Marketo.
        
        Args:
            name: The name of the program
            include_tags: Whether to include program tags in the response (optional)
            include_costs: Whether to include program costs in the response (optional)
            
        Returns:
            Dict[str, Any]: Program data including metadata, type, channel, status, and optional tags/costs
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {"name": name}
            if include_tags:
                params["includeTags"] = "true"
            if include_costs:
                params["includeCosts"] = "true"
            
            # Get program by name
            program_url = f"{MARKETO_BASE_URL}/rest/asset/v1/program/byName.json"
            
            logger.info(f"Requesting program with name: {name}")
            response = requests.get(program_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully retrieved program: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get program by name: {str(e)}"}

    @mcp.tool
    def browse_programs(max_return: int = 20, offset: int = 0, status: Optional[str] = None,
                       earliest_updated_at: Optional[str] = None, latest_updated_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Browse programs in Marketo with optional filtering.
        
        Args:
            max_return: Maximum number of results to return (default: 20, max: 200)
            offset: Number of results to skip for pagination (default: 0)
            status: Filter by status - "on", "off" for Engagement programs, "unlocked" for Email programs (optional)
            earliest_updated_at: Filter by earliest update date in ISO8601 format (optional)
            latest_updated_at: Filter by latest update date in ISO8601 format (optional)
            
        Returns:
            Dict[str, Any]: List of programs matching the criteria
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {
                "maxReturn": min(max_return, 200),  # Ensure max is 200
                "offset": offset
            }
            
            if status:
                params["status"] = status
            if earliest_updated_at:
                params["earliestUpdatedAt"] = earliest_updated_at
            if latest_updated_at:
                params["latestUpdatedAt"] = latest_updated_at
            
            # Browse programs
            programs_url = f"{MARKETO_BASE_URL}/rest/asset/v1/programs.json"
            
            logger.info(f"Browsing programs with max_return={max_return}, offset={offset}")
            response = requests.get(programs_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} programs")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to browse programs: {str(e)}"}

    @mcp.tool
    def create_program(name: str, folder_id: int, program_type: str, channel: str, 
                      description: Optional[str] = None, costs: Optional[List[Dict[str, Any]]] = None,
                      tags: Optional[List[Dict[str, str]]] = None, start_date: Optional[str] = None,
                      end_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new program in Marketo.
        
        Args:
            name: The name of the program to create
            folder_id: The folder ID where the program will be created
            program_type: The type of program (Default, Event, Event with Webinar, Engagement, Email)
            channel: The channel for the program
            description: Optional description for the program
            costs: Optional list of cost objects with startDate, cost, and optional note
            tags: Optional list of tag objects with tagType and tagValue
            start_date: Optional start date for Email programs (UTC datetime)
            end_date: Optional end date for Email programs (UTC datetime)
            
        Returns:
            Dict[str, Any]: Created program data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Build form data
            form_data = {
                "name": name,
                "folder": f'{{"id":{folder_id},"type":"Folder"}}',
                "type": program_type,
                "channel": channel
            }
            
            if description:
                form_data["description"] = description
            if costs:
                form_data["costs"] = str(costs).replace("'", '"')  # Convert to JSON string
            if tags:
                form_data["tags"] = str(tags).replace("'", '"')  # Convert to JSON string
            if start_date:
                form_data["startDate"] = start_date
            if end_date:
                form_data["endDate"] = end_date
            
            # Create program
            create_url = f"{MARKETO_BASE_URL}/rest/asset/v1/programs.json"
            
            logger.info(f"Creating program: {name} (Type: {program_type}, Channel: {channel})")
            response = requests.post(create_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully created program: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to create program: {str(e)}"}

    @mcp.tool
    def update_program(program_id: int, name: Optional[str] = None, description: Optional[str] = None,
                      costs: Optional[List[Dict[str, Any]]] = None, costs_destructive_update: bool = False,
                      tags: Optional[List[Dict[str, str]]] = None, start_date: Optional[str] = None,
                      end_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Update an existing program in Marketo.
        
        Args:
            program_id: The ID of the program to update
            name: New name for the program (optional)
            description: New description for the program (optional)
            costs: New costs for the program (optional)
            costs_destructive_update: Whether to replace all existing costs (default: False)
            tags: New tags for the program (optional)
            start_date: New start date for Email programs (optional, UTC datetime)
            end_date: New end date for Email programs (optional, UTC datetime)
            
        Returns:
            Dict[str, Any]: Updated program data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Build form data
            form_data = {}
            if name:
                form_data["name"] = name
            if description:
                form_data["description"] = description
            if costs is not None:
                form_data["costs"] = str(costs).replace("'", '"')  # Convert to JSON string
            if costs_destructive_update:
                form_data["costsDestructiveUpdate"] = "true"
            if tags:
                form_data["tags"] = str(tags).replace("'", '"')  # Convert to JSON string
            if start_date:
                form_data["startDate"] = start_date
            if end_date:
                form_data["endDate"] = end_date
            
            # Update program
            update_url = f"{MARKETO_BASE_URL}/rest/asset/v1/program/{program_id}.json"
            
            logger.info(f"Updating program ID: {program_id}")
            response = requests.post(update_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully updated program ID: {program_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to update program: {str(e)}"}

    @mcp.tool
    def clone_program(program_id: int, name: str, folder_id: int, 
                     description: Optional[str] = None) -> Dict[str, Any]:
        """
        Clone an existing program in Marketo.
        Note: Programs containing Push Notifications, In-App Messages, Reports, and Social Assets may not be cloned.
        
        Args:
            program_id: The ID of the program to clone
            name: The name for the new cloned program (must be globally unique, max 255 characters)
            folder_id: The folder ID where the cloned program will be created
            description: Optional description for the cloned program
            
        Returns:
            Dict[str, Any]: Cloned program data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Build form data
            form_data = {
                "name": name,
                "folder": f'{{"id":{folder_id},"type":"Folder"}}'
            }
            
            if description:
                form_data["description"] = description
            
            # Clone program
            clone_url = f"{MARKETO_BASE_URL}/rest/asset/v1/program/{program_id}/clone.json"
            
            logger.info(f"Cloning program ID: {program_id} to: {name}")
            response = requests.post(clone_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully cloned program to: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to clone program: {str(e)}"}

    @mcp.tool
    def delete_program(program_id: int) -> Dict[str, Any]:
        """
        Delete a program from Marketo.
        
        Args:
            program_id: The ID of the program to delete
            
        Returns:
            Dict[str, Any]: Deletion confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Delete program
            delete_url = f"{MARKETO_BASE_URL}/rest/asset/v1/program/{program_id}/delete.json"
            
            logger.info(f"Deleting program ID: {program_id}")
            response = requests.post(delete_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully deleted program ID: {program_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to delete program: {str(e)}"}

    @mcp.tool
    def approve_email_program(program_id: int) -> Dict[str, Any]:
        """
        Approve an Email Program in Marketo.
        The program must have a valid and approved email and smart list configured via the UI.
        Both startDate and endDate must be set to approve the program.
        
        Args:
            program_id: The ID of the Email program to approve
            
        Returns:
            Dict[str, Any]: Approval confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Approve email program
            approve_url = f"{MARKETO_BASE_URL}/rest/asset/v1/program/{program_id}/approve.json"
            
            logger.info(f"Approving email program ID: {program_id}")
            response = requests.post(approve_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully approved email program ID: {program_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to approve email program: {str(e)}"}

    @mcp.tool
    def unapprove_email_program(program_id: int) -> Dict[str, Any]:
        """
        Unapprove an Email Program in Marketo.
        
        Args:
            program_id: The ID of the Email program to unapprove
            
        Returns:
            Dict[str, Any]: Unapproval confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Unapprove email program
            unapprove_url = f"{MARKETO_BASE_URL}/rest/asset/v1/program/{program_id}/unapprove.json"
            
            logger.info(f"Unapproving email program ID: {program_id}")
            response = requests.post(unapprove_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully unapproved email program ID: {program_id}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to unapprove email program: {str(e)}"}

    # Program Members Tools
    @mcp.tool
    def describe_program_members() -> Dict[str, Any]:
        """
        Get program member field metadata and schema information from Marketo.
        
        Returns:
            Dict[str, Any]: Program member schema data including fields, searchable fields, and dedupe fields
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get program member schema
            describe_url = f"{MARKETO_BASE_URL}/rest/v1/programs/members/describe.json"
            
            logger.info("Requesting program member schema")
            response = requests.get(describe_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved program member schema with {result_count} field definitions")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to describe program members: {str(e)}"}

    @mcp.tool
    def query_program_members(program_id: int, filter_type: str, filter_values: str, 
                             fields: Optional[str] = None, start_at: Optional[str] = None,
                             end_at: Optional[str] = None) -> Dict[str, Any]:
        """
        Query program members from Marketo with filtering options.
        
        Args:
            program_id: The Marketo program ID to search members for
            filter_type: Field to use as search filter (e.g., "leadId", "statusName", "reachedSuccess")
            filter_values: Comma-separated values to search for (max 300 values)
            fields: Optional comma-separated list of fields to return
            start_at: Optional start datetime for date range filtering (ISO8601 format)
            end_at: Optional end datetime for date range filtering (ISO8601 format)
            
        Returns:
            Dict[str, Any]: Program members data matching the filter criteria
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {
                "filterType": filter_type,
                "filterValues": filter_values
            }
            
            if fields:
                params["fields"] = fields
            if start_at:
                params["startAt"] = start_at
            if end_at:
                params["endAt"] = end_at
            
            # Query program members
            query_url = f"{MARKETO_BASE_URL}/rest/v1/programs/{program_id}/members.json"
            
            logger.info(f"Querying program members for program {program_id} with filter {filter_type}")
            response = requests.get(query_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} program members")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to query program members: {str(e)}"}

    # Token Management Tools
    @mcp.tool
    def get_tokens_by_folder(folder_id: int, folder_type: str = "Folder") -> Dict[str, Any]:
        """
        Get tokens by folder ID from Marketo.
        
        Args:
            folder_id: The Marketo folder or program ID
            folder_type: The type of folder - "Folder" or "Program" (default: "Folder")
            
        Returns:
            Dict[str, Any]: Tokens data including folder information and token list
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Build query parameters
            params = {"folderType": folder_type}
            
            # Get tokens by folder
            tokens_url = f"{MARKETO_BASE_URL}/rest/asset/v1/folder/{folder_id}/tokens.json"
            
            logger.info(f"Requesting tokens for {folder_type} ID: {folder_id}")
            response = requests.get(tokens_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved {result_count} token folders")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to get tokens by folder: {str(e)}"}

    @mcp.tool
    def create_token(folder_id: int, name: str, token_type: str, value: str, 
                    folder_type: str = "Folder") -> Dict[str, Any]:
        """
        Create a new token in Marketo.
        
        Args:
            folder_id: The Marketo folder or program ID where the token will be created
            name: The name of the token (max 50 characters)
            token_type: The data type of the token - "date", "number", "rich text", "score", "sfdc campaign", or "text"
            value: The value of the token
            folder_type: The type of folder - "Folder" or "Program" (default: "Folder")
            
        Returns:
            Dict[str, Any]: Created token data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Validate token type
            valid_types = ["date", "number", "rich text", "score", "sfdc campaign", "text"]
            if token_type not in valid_types:
                return {"error": f"Invalid token type. Must be one of: {', '.join(valid_types)}"}
            
            # Build form data
            form_data = {
                "name": name,
                "type": token_type,
                "value": value,
                "folderType": folder_type
            }
            
            # Create token
            create_url = f"{MARKETO_BASE_URL}/rest/asset/v1/folder/{folder_id}/tokens.json"
            
            logger.info(f"Creating token '{name}' of type '{token_type}' in {folder_type} {folder_id}")
            response = requests.post(create_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully created token: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to create token: {str(e)}"}

    @mcp.tool
    def update_token(folder_id: int, name: str, token_type: str, value: str, 
                    folder_type: str = "Folder") -> Dict[str, Any]:
        """
        Update an existing token in Marketo (uses the same endpoint as create).
        
        Args:
            folder_id: The Marketo folder or program ID where the token exists
            name: The name of the token to update (max 50 characters)
            token_type: The data type of the token - "date", "number", "rich text", "score", "sfdc campaign", or "text"
            value: The new value of the token
            folder_type: The type of folder - "Folder" or "Program" (default: "Folder")
            
        Returns:
            Dict[str, Any]: Updated token data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Validate token type
            valid_types = ["date", "number", "rich text", "score", "sfdc campaign", "text"]
            if token_type not in valid_types:
                return {"error": f"Invalid token type. Must be one of: {', '.join(valid_types)}"}
            
            # Build form data
            form_data = {
                "name": name,
                "type": token_type,
                "value": value,
                "folderType": folder_type
            }
            
            # Update token (same endpoint as create)
            update_url = f"{MARKETO_BASE_URL}/rest/asset/v1/folder/{folder_id}/tokens.json"
            
            logger.info(f"Updating token '{name}' of type '{token_type}' in {folder_type} {folder_id}")
            response = requests.post(update_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully updated token: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to update token: {str(e)}"}

    @mcp.tool
    def delete_token(folder_id: int, name: str, token_type: str, 
                    folder_type: str = "Folder") -> Dict[str, Any]:
        """
        Delete a token from Marketo.
        
        Args:
            folder_id: The Marketo folder or program ID where the token exists
            name: The name of the token to delete
            token_type: The data type of the token - "date", "number", "rich text", "score", "sfdc campaign", or "text"
            folder_type: The type of folder - "Folder" or "Program" (default: "Folder")
            
        Returns:
            Dict[str, Any]: Deletion confirmation data
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            # Validate token type
            valid_types = ["date", "number", "rich text", "score", "sfdc campaign", "text"]
            if token_type not in valid_types:
                return {"error": f"Invalid token type. Must be one of: {', '.join(valid_types)}"}
            
            # Build form data
            form_data = {
                "name": name,
                "type": token_type,
                "folderType": folder_type
            }
            
            # Delete token
            delete_url = f"{MARKETO_BASE_URL}/rest/asset/v1/folder/{folder_id}/tokens/delete.json"
            
            logger.info(f"Deleting token '{name}' of type '{token_type}' from {folder_type} {folder_id}")
            response = requests.post(delete_url, headers=headers, data=form_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"Successfully deleted token: {name}")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to delete token: {str(e)}"}

    # Lead Schema Tools
    @mcp.tool
    def describe_leads() -> Dict[str, Any]:
        """
        Get lead field metadata and schema information from Marketo.
        This is the primary source of truth for available lead fields and their properties.
        
        Returns:
            Dict[str, Any]: Lead schema data including field definitions, data types, 
            REST API names, field lengths, read-only status, and friendly labels
        """
        try:
            token = get_marketo_token()
            if not token:
                return {"error": "Failed to obtain access token"}
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # Get lead schema
            describe_url = f"{MARKETO_BASE_URL}/rest/v1/leads/describe.json"
            
            logger.info("Requesting lead schema")
            response = requests.get(describe_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            result_count = len(data.get("result", []))
            logger.info(f"Successfully retrieved lead schema with {result_count} field definitions")
            
            return data
            
        except Exception as e:
            logger.error(f"Error in MCP tool: {e}")
            return {"error": f"Failed to describe leads: {str(e)}"}


if __name__ == "__main__":
    import sys
    
    # Check if we should run the MCP server or just test authentication
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        if not FASTMCP_AVAILABLE:
            print("❌ FastMCP not available. Install with: pip install fastmcp")
            sys.exit(1)
        
        print("🚀 Starting Marketo MCP Server...")
        print("✅ Authentication test passed - starting server")
        mcp.run()
    else:
        # Test the authentication when running this file directly
        print("Testing Marketo OAuth Authentication...")
        success = test_marketo_authentication()
        if success:
            print("✅ Authentication successful!")
            
            # Test activity types if authentication worked
            print("\nTesting Activity Types Retrieval...")
            types_success = test_activity_types()
            
            # Test lead activities if authentication worked
            print("\nTesting Lead Activities Retrieval...")
            activities_success = test_lead_activities()
            
            if FASTMCP_AVAILABLE:
                print("\n🚀 Ready to start MCP server. Run: python server.py --server")
                print("\n📋 Available MCP Tools:")
                print("   • get_activity_types() - Get available activity types")
                print("   • get_lead_by_email(email) - Get lead by email address")
                print("   • get_lead_activities(lead_id, activity_type_ids, days_back) - Get lead activities")
                print("   • get_lead_activities_by_email(email, activity_type_ids, days_back) - Get lead activities by email")
                print("   • get_lead_changes(lead_id, fields, days_back) - Get lead data changes")
                print("   • get_email_by_id(email_id) - Get email asset by ID")
                print("   • get_email_by_name(name, folder_id) - Get email asset by name")
                print("   • browse_emails(max_return, offset, status, folder_id, etc.) - Browse email assets")
                print("   • get_email_content(email_id, status) - Get email content sections")
                print("   • get_email_cc_fields() - Get available CC fields")
                print("   • preview_email(email_id, status, content_type, lead_id) - Preview email content")
                print("   • browse_folders(max_return, offset, folder_type) - Browse folders to find valid folder IDs")
                print("   • get_smart_campaign_by_id(campaign_id) - Get smart campaign by ID")
                print("   • get_smart_campaign_by_name(name) - Get smart campaign by name")
                print("   • browse_smart_campaigns(max_return, offset, is_active, etc.) - Browse smart campaigns")
                print("   • create_smart_campaign(name, folder_id, description) - Create new smart campaign")
                print("   • update_smart_campaign(campaign_id, name, description, folder_id) - Update smart campaign")
                print("   • clone_smart_campaign(campaign_id, name, folder_id, description) - Clone smart campaign")
                print("   • delete_smart_campaign(campaign_id) - Delete smart campaign")
                print("   • schedule_batch_campaign(campaign_id, run_at, tokens, clone_to_program) - Schedule batch campaign")
                print("   • trigger_campaign(campaign_id, lead_ids, tokens) - Trigger campaign for leads")
                print("   • activate_smart_campaign(campaign_id) - Activate smart campaign")
                print("   • deactivate_smart_campaign(campaign_id) - Deactivate smart campaign")
                print("   • get_program_by_id(program_id) - Get program by ID")
                print("   • get_program_by_name(name, include_tags, include_costs) - Get program by name")
                print("   • browse_programs(max_return, offset, status, etc.) - Browse programs")
                print("   • create_program(name, folder_id, program_type, channel, etc.) - Create new program")
                print("   • update_program(program_id, name, description, costs, etc.) - Update program")
                print("   • clone_program(program_id, name, folder_id, description) - Clone program")
                print("   • delete_program(program_id) - Delete program")
                print("   • approve_email_program(program_id) - Approve email program")
                print("   • unapprove_email_program(program_id) - Unapprove email program")
                print("   • describe_program_members() - Get program member schema and field metadata")
                print("   • query_program_members(program_id, filter_type, filter_values, fields, start_at, end_at) - Query program members")
                print("   • get_tokens_by_folder(folder_id, folder_type) - Get tokens by folder or program ID")
                print("   • create_token(folder_id, name, token_type, value, folder_type) - Create a new token")
                print("   • update_token(folder_id, name, token_type, value, folder_type) - Update an existing token")
                print("   • delete_token(folder_id, name, token_type, folder_type) - Delete a token")
                print("   • describe_leads() - Get lead field metadata and schema information")
            else:
                print("\n⚠️  FastMCP not available. Install with: pip install fastmcp")
        else:
            print("❌ Authentication failed. Please check your environment variables and credentials.")
