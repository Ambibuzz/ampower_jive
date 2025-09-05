from ampower_jive.mcp.config.setup import logger
from googleapiclient.discovery import build
from google.oauth2 import service_account
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
import frappe
import json
import os

config = frappe.get_single("Jive Config")
api_key = config.api_key or os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=api_key)

google_drive_config_json = config.drive_service_account

if not google_drive_config_json:
    logger.error("Google Drive config is missing in Jive Config")

if isinstance(google_drive_config_json, str):
    service_account_info = json.loads(google_drive_config_json)
else:
    service_account_info = google_drive_config_json

scopes = ["https://www.googleapis.com/auth/drive"]
credentials = service_account.Credentials.from_service_account_info(
    service_account_info, scopes=scopes
)

gdrive_client = build("drive", "v3", credentials=credentials)

MCP_HOST = os.environ.get("MCP_HOST", "your-custom-fallback-host")
MCP_PORT = os.environ.get("MCP_PORT", "your-custom-fallback-port")

mcp = FastMCP("Frappe MCP Server", port=MCP_PORT, host=MCP_HOST, stateless_http=True)
