# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import os
import json
import frappe
import requests
from typing import Dict
from datetime import datetime, date
from fastmcp.server.dependencies import get_context

frappe.utils.logger.set_log_level("INFO")
logger = frappe.logger("frappe-mcp", allow_site=True, file_count=2)


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
            site_name = os.environ.get("FRAPPE_SITE")
            frappe.init(site=site_name)
            frappe.connect()
        if not hasattr(frappe, "local") or not frappe.local.db:
            frappe.connect()
        logger.info("Frappe initialized successfully")
    except Exception as e:
        logger.error(f"Frappe init error: {e}")


def convert_dates_to_strings(data):
    if isinstance(data, list):
        return [convert_dates_to_strings(item) for item in data]
    elif isinstance(data, dict):
        return {k: convert_dates_to_strings(v) for k, v in data.items()}
    elif isinstance(data, (datetime, date)):
        return data.isoformat()
    return data


def open_fresh_session():
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
    frappe.connect()
    update_current_session()


def update_current_session():
    # Get SID and user from FastMCP context and store in variables
    try:
        ctx = get_context()
        frappe_sid = frappe.local.mcp_sid
        frappe_user = frappe.local.mcp_user

        # Bind the session if SID and user are available
        if frappe_sid and frappe_user:
            set_session_user(frappe_sid, frappe_user)
    except Exception as e:
        frappe.log_error(
            message=str(e), title="Failed to get or bind session from FastMCP context"
        )


def teardown_session():
    try:
        if getattr(frappe, "db", None):
            # Ensure nothing is left pending and release connection back to pool
            frappe.db.close()
            frappe.destroy()
    except Exception as e:
        logger.error(f"Error during teardown_session {e}")


def validate_session(sid: str) -> Dict[str, any]:
    """
    Check if a session ID is valid and active.

    Args:
        sid: Session ID to validate

    Returns:
        dict: Session information with keys:
            - valid (bool): Whether session is valid
            - user (str): User associated with session (if valid)
            - message (str): Error message (if invalid)

    Raises:
        ValueError: If sid is invalid format
    """
    try:
        # Validate input
        if not sid or not isinstance(sid, str):
            return {"valid": False, "user": None, "message": "Invalid or missing SID"}

        Sessions = frappe.qb.DocType("Sessions")

        # Fetch the associated user for an active session
        row = (
            frappe.qb.from_(Sessions)
            .select(Sessions.user, Sessions.status)
            .where((Sessions.sid == sid) & (Sessions.status == "Active"))
            .limit(1)
        ).run(as_dict=True)

        if not row or not row[0].get("user"):
            return {
                "valid": False,
                "user": None,
                "message": "Invalid or inactive session",
            }

        user = row[0]["user"]

        # Additional validation: Check if user is enabled
        if not frappe.db.get_value("User", user, "enabled"):
            return {"valid": False, "user": user, "message": f"User {user} is disabled"}

        return {"valid": True, "user": user, "message": "Session is valid"}

    except Exception as e:
        frappe.log_error(message=str(e), title="Session Validation Error")
        return {
            "valid": False,
            "user": None,
            "message": f"Error validating session: {str(e)}",
        }


def set_session_user(sid: str, user: str) -> None:
    """
    Set the validated session as the current session user.

    This function assumes the session has already been validated.
    Use validate_session() first to check validity.

    Args:
        sid: Validated session ID
        user: User to set as current session user

    Raises:
        PermissionError: If session binding fails
    """
    try:
        # Manually bind minimal session locals for permission checks
        sess_data = frappe._dict()
        sess_data.sid = sid
        sess_data.user = user

        # Set session in frappe.local
        frappe.local.session = sess_data
        frappe.local.session_obj = None

        # Set the user context
        frappe.set_user(user)

        # Log session binding for debugging
        frappe.log_error(
            message=f"Current Session User: {frappe.session.user}, "
            f"SID: {frappe.session.sid}, "
            f"Session Local Data: {frappe.local.session}, "
            f"Session Data: {frappe.session.data}",
            title="Session Bind Info",
        )

    except Exception as e:
        frappe.log_error(message=str(e), title="Session Bind Error")
        raise PermissionError(f"Failed to set session user: {str(e)}")


def bind_frappe_session_from_sid(sid: str) -> None:
    """
    Validate and bind frappe.local session and user from a SID.

    This is a convenience function that combines validate_session()
    and set_session_user().

    Args:
        sid: Session ID to validate and bind

    Raises:
        PermissionError: If session is invalid or binding fails
    """
    # Step 1: Validate the session
    validation_result = validate_session(sid)

    if not validation_result["valid"]:
        raise PermissionError(validation_result["message"])

    return validation_result
