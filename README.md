# Marketo MCP Server - Enhanced Activities API

A comprehensive FastMCP server for integrating with Adobe Marketo Engage's REST API, specifically focused on the Activities API with full compliance to Marketo's requirements.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Variables

Set the following environment variables with your Marketo credentials:

```bash
# Your Marketo Client ID from LaunchPoint
export MARKETO_CLIENT_ID="your_client_id_here"

# Your Marketo Client Secret from LaunchPoint  
export MARKETO_CLIENT_SECRET="your_client_secret_here"

# Your Marketo instance base URL (found in Admin > Web Services)
# Format: https://<instance>.mktorest.com
export MARKETO_BASE_URL="https://your-instance.mktorest.com"
```

### 3. Test Authentication

Run the authentication test to verify your credentials:

```bash
python server.py
```

You should see output like:
```
Testing Marketo OAuth Authentication...
INFO:__main__:Attempting to authenticate with Marketo API...
INFO:__main__:Successfully obtained Marketo access token
INFO:__main__:Token expires in 3600 seconds
INFO:__main__:✅ Marketo authentication test PASSED
Authentication successful! Ready to proceed with MCP server setup.
```

## Features

- **OAuth 2.0 Authentication**: Implements 2-legged OAuth with Marketo
- **Activity Types Discovery**: Get available activity types and their definitions
- **Enhanced Lead Activities**: Full compliance with Marketo's required `activityTypeIds` parameter
- **Lead Data Changes**: Specialized endpoint for tracking field value changes
- **Environment Variable Security**: All credentials stored securely in environment variables
- **Error Handling**: Comprehensive error handling and logging
- **Token Management**: Handles access token retrieval and validation
- **FastMCP Integration**: Complete MCP server with 3 powerful tools

## Testing

### 1. Test Authentication and Activities
```bash
python server.py
```

This will test both authentication and lead activities retrieval.

### 2. Start the MCP Server
```bash
python server.py --server
```

This starts the FastMCP server with the Marketo integration.

## MCP Tools

The server provides the following MCP tools:

### 1. `get_activity_types()`
Get available activity types from Marketo with their definitions and attributes.

### 2. `get_lead_activities(lead_id, activity_type_ids, days_back)`
Get recent activities for a lead with full Marketo API compliance:
- **lead_id**: The Marketo lead ID (default: 12345)
- **activity_type_ids**: Optional list of activity type IDs to filter by (up to 10)
- **days_back**: Number of days back to fetch activities (default: 7)

### 3. `get_lead_changes(lead_id, fields, days_back)`
Get data value changes for a lead (specialized for Data Value Change activities):
- **lead_id**: The Marketo lead ID (default: 12345)
- **fields**: Optional list of field names to track changes for
- **days_back**: Number of days back to fetch changes (default: 7)

## API Endpoints Implemented

- **OAuth Authentication**: 2-legged OAuth 2.0 with Marketo
- **Activity Types API**: 
  - Get available activity types and definitions
  - Retrieve activity type attributes and data types
- **Activities API**: 
  - Paging token retrieval
  - Lead activities retrieval with required `activityTypeIds` parameter
  - Support for up to 10 activity type IDs
  - Optional lead ID and list ID filtering
- **Lead Changes API**:
  - Specialized endpoint for Data Value Change activities
  - Field-specific change tracking
  - Support for multiple field monitoring

## Usage Examples

### 1. Get Activity Types
```python
# Get all available activity types
result = get_activity_types()
```

### 2. Get Lead Activities
```python
# Get activities for lead 12345 with specific activity types
result = get_lead_activities(
    lead_id=12345,
    activity_type_ids=[1, 2, 6],  # Visit Webpage, Fill Form, Send Email
    days_back=7
)
```

### 3. Get Lead Changes
```python
# Track changes to specific fields for lead 12345
result = get_lead_changes(
    lead_id=12345,
    fields=["firstName", "lastName", "email"],
    days_back=30
)
```

## Common Activity Type IDs

Based on the [Marketo Activities API documentation](https://experienceleague.adobe.com/en/docs/marketo-developer/marketo/rest/lead-database/activities):

- **1**: Visit Webpage
- **2**: Fill Out Form  
- **6**: Send Email
- **13**: Data Value Change
- **37**: Deleted Lead
