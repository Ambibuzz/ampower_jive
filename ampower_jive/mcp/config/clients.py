# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt


import os
from fastmcp import FastMCP

MCP_HOST = os.environ.get("MCP_HOST", "your-custom-fallback-host")
MCP_PORT = os.environ.get("MCP_PORT", "your-custom-fallback-port")

mcp = FastMCP("Frappe MCP Server", port=MCP_PORT, host=MCP_HOST, stateless_http=True)
