"""Domain modules for the blended Marketo MCP server's expanded custom tools.

Each *_tools module exposes register(mcp) which adds its custom_* tools.
All tools delegate to the single-source API library (marketo_functions.py)
through marketo_rest.bridge.
"""
