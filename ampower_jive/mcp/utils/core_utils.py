from ampower_jive.mcp.config.setup import logger
from datetime import datetime, date
import requests
import frappe
import json


MCP_HOST = frappe.conf.get("mcp_server_host", "localhost")
MCP_PORT = frappe.conf.get("mcp_server_port", 8001)
MCP_BASE_URL = f"http://{MCP_HOST}:{MCP_PORT}"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": f"Frappe-MCP-Client/{frappe.__version__}",
}


def make_local_mcp_request(method, params={}, request_id="frappe-mcp-client"):
    """Send generic JSON-RPC request to MCP server"""
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }

    logger.info(f"MCP Request Payload: {json.dumps(payload, indent=2)}")

    try:
        res = requests.post(
            f"{MCP_BASE_URL}/mcp",
            headers=HEADERS,
            data=json.dumps(payload),
            timeout=300,
            verify=False,
        )

        logger.info(f"Response Status: {res.status_code}")
        logger.info(f"Response Text: {res.text}")

        if res.status_code == 200:
            try:
                content_type = res.headers.get("content-type", "")

                if "text/event-stream" in content_type:
                    lines = res.text.strip().split("\n")
                    for line in lines:
                        if line.startswith("data: "):
                            data = line[6:].strip()
                            if data and data != "[DONE]":
                                try:
                                    return json.loads(data)
                                except json.JSONDecodeError:
                                    continue
                    return {"error": "No valid data in SSE response"}
                else:
                    return res.json()

            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                return {
                    "error": "Invalid JSON response from MCP server",
                    "raw": res.text,
                }
        else:
            return {"error": f"HTTP {res.status_code}", "details": res.text}

    except Exception as e:
        logger.error(f"MCP request error: {e}")
        return {"error": "Unable to reach MCP server", "details": str(e)}


def datetime_handler(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    logger.error(f"Object of type {type(obj)} is not JSON serializable")


def ensure_frappe_init():
    """Ensure Frappe is initialized"""
    try:
        if not hasattr(frappe, "db") or not frappe.db:
            frappe.init()
        if not hasattr(frappe, "local") or not frappe.local.db:
            frappe.connect()
        logger.info("Frappe initialized successfully")
    except Exception as e:
        logger.error(f"Frappe init error: {e}")
