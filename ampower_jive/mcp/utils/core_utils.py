from datetime import datetime, date
from frappe.sessions import Session
import requests
import logging
import frappe
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

def _convert_dates_to_strings(data):
    if isinstance(data, list):
        return [_convert_dates_to_strings(item) for item in data]
    elif isinstance(data, dict):
        return {k: _convert_dates_to_strings(v) for k, v in data.items()}
    elif isinstance(data, (datetime, date)):
        return data.isoformat()
    return data

def _open_fresh_session():
    """
    Open a fresh DB session that sees latest committed rows.
    """
    # If a previous connection exists, close it first
    try:
        if getattr(frappe, "db", None):
            frappe.db.close()
    except Exception:
        pass

    # Init/connect for the current site
    if not getattr(frappe.local, "site", None):
        site_name = os.environ.get("FRAPPE_SITE")
        frappe.init(site=site_name)

    return frappe.connect()

def _teardown_session():
    try:
        if getattr(frappe, "db", None):
            # Ensure nothing is left pending and release connection back to pool
            frappe.db.commit()
            frappe.db.close()
    except Exception:
        pass


def bind_frappe_session_from_sid(sid: str) -> None:
    """Bind frappe.local session and user from a valid SID."""
    try:
        if not sid or not isinstance(sid, str):
            raise PermissionError("Invalid or missing SID")

        Sessions = frappe.qb.DocType("Sessions")
        # Fetch the associated user for an active session
        row = (
            frappe.qb.from_(Sessions)
            .select(Sessions.user)
            .where((Sessions.sid == sid) & (Sessions.status == "Active"))
            .limit(1)
        ).run(as_dict=True)

        if not row or not row[0].get("user"):
            raise PermissionError("Invalid or inactive session")

        user = row[0]["user"]

        #Manually bind minimal session locals for permission checks
        sess_data = frappe._dict()
        sess_data.sid = sid
        sess_data.user = user
        frappe.local.session = sess_data
        frappe.local.session_obj = None
        frappe.set_user(user)
        frappe.log_error(message=f"Current Session User: {frappe.session.user}, SID: {frappe.session.sid}, session local data: {frappe.local.session}, session data: {frappe.session.data}",  title="Session Bind Info")
    except Exception as e:
        frappe.log_error(f"Session bind error", str(e))
        raise


def cleanup_frappe_local():
    """
    Clear per-request locals to avoid cross-request contamination in worker reuse.
    """
    try:
        # Reset user to 'Guest' and drop local session safely
        frappe.set_user("Guest")
    except Exception:
        pass
    finally:
        if hasattr(frappe, "local"):
            # Drop session reference
            try:
                frappe.local.session = None
            except Exception:
                pass