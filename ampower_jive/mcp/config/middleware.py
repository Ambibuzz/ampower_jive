# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import frappe
from fastmcp.exceptions import ToolError
from ..utils.core_utils import teardown_session
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from ampower_jive.mcp.utils.core_utils import bind_frappe_session_from_sid, logger


class FrappeSIDAuthMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        logger.debug("FrappeSIDAuthMiddleware invoked")
        headers = get_http_headers() or {}
        sid = None

        auth_header = headers.get("authorization") or headers.get("Authorization")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 1:
                sid = parts[0]
            elif len(parts) == 2 and parts[0].lower() == "bearer":
                sid = parts[1]
        logger.info(f"Middleware Log: Headers :- {auth_header}, SID :- {sid}, usesr :- {frappe.session.user}")

        if not sid:
            teardown_session()
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
            teardown_session()
            return await call_next(context)

        except Exception:
            teardown_session()
            raise ToolError(
                {
                    "error": "Unauthorized",
                    "code": 401,
                    "detail": "Invalid or expired SID",
                }
            )

        finally:
            teardown_session()
