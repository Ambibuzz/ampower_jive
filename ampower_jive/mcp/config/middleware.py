import json, frappe
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from ampower_jive.mcp.utils.core_utils import bind_frappe_session_from_sid, cleanup_frappe_local

class FrappeSIDAuthMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers() or {}
        sid = None

        auth_header = headers.get("authorization") or headers.get("Authorization")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 1:
                sid = parts[0]
            elif len(parts) == 2 and parts[0].lower() == "bearer":
                sid = parts[1]
        frappe.log_error("Middleware Log", f"Headers: {auth_header}, SID: {sid}")
        if not sid:
            frappe.log_error("Middleware Error", "Missing Authorization header with SID")
            raise ToolError({"error": "Unauthorized", "code": 401, "detail": "Missing Authorization header with SID"})

        try:
            bind_frappe_session_from_sid(sid)
        except Exception:
            frappe.log_error("Middleware Error", "Invalid or expired SID")
            raise ToolError({"error": "Unauthorized", "code": 401, "detail": "Invalid or expired SID"})

        try:
            return await call_next(context)
        finally:
            cleanup_frappe_local()
