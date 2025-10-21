You are an expert in Python and FastAPI, focused on building secure, maintainable, and standards-compliant MCP tools and resources for integrating with the Marketo API.

Marketo API Integration
- Use environment variables for all sensitive information, including the Marketo Client ID and Client Secret. Never hardcode credentials.
- Authenticate with the Marketo API using OAuth2 client credentials. Always retrieve a fresh access token before making API requests.
- Pass the access token as an Authorization: Bearer header. Do not use access tokens as URL query parameters.
- Use the requests library with appropriate headers and timeout handling. Document the purpose of each request and parameter clearly.

MCP Conventions
- Use `@mcp.resource` for all read-only queries to Marketo (e.g., leads, campaigns).
- Use `@mcp.tool` only for mutation actions, if needed.
- Name MCP resources using a `marketo://` URI scheme that clearly describes the resource (e.g., `marketo://leads/by-email`).
- Ensure each MCP route includes a clear and concise docstring describing its function.

Error Handling
- Implement basic error handling for HTTP errors and API failures. Log meaningful error messages and include the relevant response status codes.
- Avoid crashing on external API issues. Where possible, return a structured error response and note potential recovery steps in comments.

Code Style and Structure
- Write clean, modular code with clear separation of concerns.
- Include inline comments explaining each major step or logic block, especially around token handling and API calls.
- Use descriptive variable names that reflect their purpose (e.g., `access_token`, `lead_id`).
- Keep functions focused and concise; split logic into helpers where needed.

Security and Reliability
- Use `os.getenv()` or similar to access environment variables securely.
- Validate all input parameters for MCP tools and resources.
- Plan for token expiry and rate limits if scaling up usage.

Documentation and Maintainability
- Comment code so future developers and the AI assistant can easily follow it.
- Include links to the relevant Marketo API documentation when implementing new endpoints or features.
- Document assumptions and edge cases as needed in comments.

FastAPI + MCP Integration
- Use FastAPI's dependency injection features for shared services (e.g., access token retrieval).
- Use Pydantic models to define and validate request and response schemas for MCP interfaces.
- Keep FastAPI and MCP concerns cleanly separated for clarity and testability.
