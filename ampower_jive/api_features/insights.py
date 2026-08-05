"""Insights-specific endpoints for Jive."""

from __future__ import annotations

import re

import frappe

from ampower_jive.api_features.common import (
    _append_followup_suggestions,
    _build_insights_api_key_missing_response,
    _build_insights_not_installed_response,
    _ensure_local_monthly_quota,
    _finalize_insights_response,
    clean_insights_response,
)
from ampower_jive.api_features.access import has_jive_access
from ampower_jive.utils.chat_support import safe_commit
from ampower_jive.utils.followup_suggestions import strip_followup_block

def _strip_trailing_followup_questions(response_text: str) -> str:
    """Remove trailing plain-text follow-up questions from the visible Insights answer."""
    if not response_text:
        return response_text

    lines = response_text.splitlines()
    end = len(lines) - 1

    while end >= 0 and not lines[end].strip():
        end -= 1

    idx = end
    question_count = 0

    while idx >= 0:
        line = lines[idx].strip()
        if not line:
            break

        if re.match(r"^(?:[-*]\s*)?.+\?\s*$", line):
            question_count += 1
            idx -= 1
            continue

        break

    if question_count < 2:
        return response_text.strip()

    return "\n".join(lines[:idx + 1]).rstrip()


@frappe.whitelist()
def check_insights_installed():
    """Check if Frappe Insights is installed."""
    try:
        installed_apps = frappe.get_installed_apps()
        return {"installed": "insights" in installed_apps}
    except Exception:
        return {"installed": False}


@frappe.whitelist()
def delete_insights_workbook(workbook_id: str):
    """Delete an Insights workbook and all associated charts and queries."""
    if not has_jive_access():
        return {"error": True, "message": "Access denied"}

    try:
        installed_apps = frappe.get_installed_apps()
        if "insights" not in installed_apps:
            return {"error": True, "message": "Insights is not installed"}

        if not workbook_id:
            return {"error": True, "message": "Workbook ID is required"}

        if not frappe.db.exists("Insights Workbook", workbook_id):
            return {"error": True, "message": f"Workbook '{workbook_id}' not found"}

        workbook_title = frappe.db.get_value("Insights Workbook", workbook_id, "title") or workbook_id
        charts = frappe.get_all("Insights Chart v3", filters={"workbook": workbook_id}, pluck="name")
        queries = frappe.get_all("Insights Query v3", filters={"workbook": workbook_id}, pluck="name")
        dashboards = frappe.get_all("Insights Dashboard v3", filters={"workbook": workbook_id}, pluck="name")

        for chart in charts:
            frappe.delete_doc("Insights Chart v3", chart, ignore_permissions=True, force=True)
        for dashboard in dashboards:
            frappe.delete_doc("Insights Dashboard v3", dashboard, ignore_permissions=True, force=True)
        for query in queries:
            frappe.delete_doc("Insights Query v3", query, ignore_permissions=True, force=True)

        frappe.delete_doc("Insights Workbook", workbook_id, ignore_permissions=True, force=True)
        safe_commit()

        return {
            "error": False,
            "message": f"✅ Workbook '{workbook_title}' deleted successfully",
            "deleted": {
                "workbook": workbook_id,
                "charts": len(charts),
                "queries": len(queries),
                "dashboards": len(dashboards),
            },
        }

    except Exception as e:
        frappe.log_error(f"Delete Workbook Error: {e}", "Insights Agent")
        return {"error": True, "message": str(e)}


def handle_insights_mode(message: str, conversation_id: str, chat_log, history: list, session_id: str = None, context_payload=None, context_aware: bool = False, request_payload=None):
    """Handle insights mode for creating visualizations."""
    try:
        installed_apps = frappe.get_installed_apps()
        insights_installed = "insights" in installed_apps
    except Exception:
        insights_installed = False

    if not insights_installed:
        response_text = _build_insights_not_installed_response()
        return _finalize_insights_response(
            chat_log,
            message,
            conversation_id,
            response_text,
            status="error",
            error_message=response_text,
            extra={"insights_installed": False},
            request_payload=request_payload,
        )

    try:
        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        if not provider.get_api_key():
            response_text = _build_insights_api_key_missing_response()
            return _finalize_insights_response(
                chat_log,
                message,
                conversation_id,
                response_text,
                status="error",
                error_message=response_text,
                request_payload=request_payload,
            )

        quota_response = _ensure_local_monthly_quota()
        if quota_response:
            return quota_response

        from ampower_jive.agent.insights_graph import get_insights_agent

        agent = get_insights_agent()
        result = agent.process(message, history, session_id=session_id, context_payload=context_payload, context_aware=context_aware)

        response_text = clean_insights_response(result.get("response", ""))
        response_text = _strip_trailing_followup_questions(response_text)
        response_text = strip_followup_block(response_text)
        response_text = _append_followup_suggestions("insights", message, response_text, history)
        return _finalize_insights_response(
            chat_log,
            message,
            conversation_id,
            response_text,
            status="error" if result.get("error", False) else "success",
            error_message=response_text if result.get("error", False) else None,
            extra={
                "error": result.get("error", False),
                "insights_installed": True,
                "created_urls": result.get("created_urls", []),
                "chart_render_data": result.get("chart_render_data", []),
                "token_usage": getattr(frappe.local, "jive_token_usage", None),
            },
            request_payload=request_payload,
        )

    except ImportError as e:
        error_msg = f"**Missing Dependencies**\n\nThe Insights agent requires additional Python packages. Error: {str(e)}\n\nPlease ensure langchain and langchain-openai are installed:\n```\npip install langchain langchain-openai\n```"
        return _finalize_insights_response(
            chat_log,
            message,
            conversation_id,
            error_msg,
            status="error",
            error_message=str(e),
            extra={"error": False},
            request_payload=request_payload,
        )

    except TimeoutError:
        error_msg = "**Request Timeout**\n\nThe request took too long. Please try again with a simpler query."
        return _finalize_insights_response(
            chat_log,
            message,
            conversation_id,
            error_msg,
            status="timeout",
            error_message="Request timed out",
            extra={"error": False},
            request_payload=request_payload,
        )

    except Exception as e:
        traceback_str = frappe.get_traceback()
        frappe.log_error("Insights Mode Error", traceback_str)
        error_msg = f"**Error**\n\n{str(e)}\n\nPlease check the Error Log for details."
        return _finalize_insights_response(
            chat_log,
            message,
            conversation_id,
            error_msg,
            status="error",
            error_message=str(e),
            extra={"error": True},
            request_payload=request_payload,
        )
