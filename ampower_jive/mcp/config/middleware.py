import json, frappe
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from ampower_jive.mcp.utils.core_utils import (
    bind_frappe_session_from_sid,
    cleanup_frappe_local
)


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
            raise ToolError(
                {
                    "error": "Unauthorized",
                    "code": 401,
                    "detail": "Missing Authorization header with SID",
                }
            )

        try:
            # Validate and bind frappe session
            validation_result = bind_frappe_session_from_sid(sid)

            # Optionally get validated user directly
            # If validate_session is accessible, use it to avoid re-querying later
            try:
                user = (
                    validation_result.get("user")
                    if validation_result and validation_result.get("valid")
                    else frappe.session.user
                )
            except Exception:
                user = getattr(frappe.session, "user", None)

            # Store session info in FastMCP context state for tools
            context.fastmcp_context.set_state("frappe_sid", sid)
            if user:
                context.fastmcp_context.set_state("frappe_user", user)

            # Continue to the tool call
            return await call_next(context)

        except Exception:
            raise ToolError(
                {
                    "error": "Unauthorized",
                    "code": 401,
                    "detail": "Invalid or expired SID",
                }
            )

        finally:
            # Clean up frappe locals after each request to prevent leakage
            cleanup_frappe_local()
