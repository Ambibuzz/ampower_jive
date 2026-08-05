"""Shared helpers used by the split Jive API modules."""

from __future__ import annotations

import json
import re

import frappe

from ampower_jive.utils.followup_suggestions import (
    FollowupSuggestionService,
    append_followup_block,
    strip_followup_block,
)
from ampower_jive.utils.context_summary import summarize_context_payload


def _summarize_context_payload(context_payload):
    """Return a compact, log-safe summary of the current page context payload."""
    return summarize_context_payload(context_payload)


def _log_context_debug(stage: str, payload: dict):
    """Write a structured context debug line to the server log."""
    try:
        frappe.logger().info(f"[JiveContextDebug] {stage} {json.dumps(payload, default=str, ensure_ascii=False)}")
    except Exception:
        pass


def _append_followup_suggestions(mode: str, user_message: str, response_text: str, history: list = None) -> str:
    """Append a structured follow-up block when the LLM returns valid suggestions."""
    visible_response = strip_followup_block(response_text or "")

    try:
        service = FollowupSuggestionService(mode)
        suggestions = service.generate(user_message, visible_response, history=history or [])
        if suggestions:
            return append_followup_block(visible_response, suggestions)
    except Exception:
        frappe.log_error("Follow-up suggestion generation failed", frappe.get_traceback())

    return visible_response


def _strip_followup_blocks_from_history(history: list = None) -> list:
    """Remove hidden follow-up blocks before history is sent back to the LLM."""
    cleaned = []
    for msg in history or []:
        if not isinstance(msg, dict):
            continue
        item = dict(msg)
        item["content"] = strip_followup_block(item.get("content") or "")
        cleaned.append(item)
    return cleaned


def _ensure_local_monthly_quota() -> dict | None:
    """
    Ensure the local monthly quota has not been exceeded.

    The result is cached per request so multiple call sites can reuse the same
    check without requerying the token log table.
    """
    if getattr(frappe.local, "_jive_local_quota_checked", False):
        return None

    try:
        from ampower_jive.utils.token_log_service import TokenLogService

        service = TokenLogService(site_name=frappe.local.site)
        snapshot = service.get_usage_snapshot()
        frappe.local.jive_token_usage = snapshot
        frappe.local._jive_local_quota_checked = True

        monthly = snapshot.get("monthly", {})
        if not monthly.get("unlimited") and int(monthly.get("current", 0)) > int(monthly.get("limit", 0)):
            return service.build_quota_exceeded_response()
    except Exception as exc:
        frappe.log_error(
            message=f"Failed to evaluate local monthly quota: {exc}",
            title="Jive Local Quota Error",
        )

    return None


def _build_helpdesk_fallback_suggestions(user_message: str, response_text: str) -> list:
    """Build deterministic helpdesk follow-up questions when the model does not provide any."""
    text = f"{user_message or ''} {response_text or ''}".lower()

    if "erpnext" in text or "frappe" in text:
        return [
            "Can you show the exact ERPNext navigation path?",
            "Which ERPNext fields are mandatory here?",
            "What is the next step after this in ERPNext?",
        ]
    return []


def _append_helpdesk_recommendations(message: str, response_text: str, history: list = None) -> str:
    """Always attach follow-up recommendations for helpdesk responses."""
    response_with_model_suggestions = _append_followup_suggestions("helpdesk", message, response_text, history)
    if response_with_model_suggestions != response_text:
        return response_with_model_suggestions

    fallback_suggestions = _build_helpdesk_fallback_suggestions(message, response_text)
    return append_followup_block(response_text, fallback_suggestions)


def _log_mode_turn(chat_log, message: str, mode: str, response_text: str, status: str = None, error_message: str = None, error_traceback: str = None, extra: dict = None, request_payload: dict = None) -> dict:
    """Log a mode response and build the standard API payload."""
    from ampower_jive.utils.chat_support import _assistant_log_payload, add_message_to_log

    assistant_status = status or ("error" if _is_error_response(response_text) else "success")
    assistant_error = error_message if error_message is not None else (response_text if assistant_status == "error" else None)
    payload = request_payload or {"message": message, "mode": mode, "conversation_id": getattr(chat_log, "name", None)}
    assistant_kwargs = _assistant_log_payload(status=assistant_status, error_message=assistant_error, error_traceback=error_traceback)
    assistant_kwargs["request_payload"] = payload

    add_message_to_log(chat_log, "user", message, mode, request_payload=payload)
    add_message_to_log(
        chat_log,
        "assistant",
        response_text,
        mode,
        **assistant_kwargs,
    )

    response_payload = {
        "error": False,
        "response": response_text,
        "conversation_id": chat_log.name,
        "mode": mode,
        "title": chat_log.title,
        "token_usage": getattr(frappe.local, "jive_token_usage", None),
    }
    if extra:
        response_payload.update(extra)
    return response_payload


def _log_mode_error(chat_log, message: str, mode: str, error: Exception | str, title: str, traceback_str: str = None, request_payload: dict = None):
    """Write a mode failure to both the chat log and the server log."""
    from ampower_jive.utils.chat_support import _assistant_log_payload, add_message_to_log

    trace = traceback_str or frappe.get_traceback()
    frappe.log_error(message=trace, title=title)
    try:
        if chat_log:
            payload = request_payload or {"message": message, "mode": mode, "conversation_id": getattr(chat_log, "name", None)}
            assistant_kwargs = _assistant_log_payload(status="error", error_message=str(error), error_traceback=trace)
            assistant_kwargs["request_payload"] = payload
            add_message_to_log(chat_log, "user", message, mode, request_payload=payload)
            add_message_to_log(
                chat_log,
                "assistant",
                f"An error occurred: {str(error)}",
                mode,
                **assistant_kwargs,
            )
    except Exception:
        pass
    return {"error": True, "message": str(error)}


_VIEW_CHART_LINK_RE = re.compile(r"\[View (?:the )?[Cc]hart\]\([^)]+\)")
_VIEW_CHART_TEXT_RE = re.compile(r"View the chart:?\s*\[?[^\]]*\]?\([^)]*\)?")
_CREATED_SECTION_RE = re.compile(r"\*\*Created (?:Resources|Visualizations):\*\*.*?(?=\n\n|\Z)", re.DOTALL)
_INSIGHTS_BANNER_RE = re.compile(r"---\s*\*\*📈 View in Insights:\*\*.*?(?=\n\n|\Z)", re.DOTALL)
_INSIGHTS_SECTION_RE = re.compile(r"💡\s*\*\*Quick Insights:?\*\*")
_RECOMMENDATION_SECTION_RE = re.compile(r"\*\*Recommendation:?\*\*")
_FOLLOWUP_SECTION_RE = re.compile(r"\*\*Would you like to:?\*\*")
_LINK_RE = re.compile(r"📈\s*\[[^\]]+\]\([^)]+\)")
_INSIGHTS_BOUNDARY_RE = re.compile(r"\n\n(?:📈|\*\*Recommendation|\*\*Would you like|---)")
_RECOMMENDATION_BOUNDARY_RE = re.compile(r"\n\n(?:📈|💡|\*\*Would you like|---)")
_FOLLOWUP_BOUNDARY_RE = re.compile(r"\n\n📈")


def _remove_duplicate_sections(response: str, section_pattern, boundary_pattern) -> str:
    matches = list(section_pattern.finditer(response))
    if len(matches) <= 1:
        return response

    for match in reversed(matches[1:]):
        start = match.start()
        remaining = response[match.end():]
        next_section = boundary_pattern.search(remaining)
        end = match.end() + next_section.start() if next_section else len(response)
        response = response[:start] + response[end:]

    return response


def _normalize_feedback_value(raw_feedback: str = None) -> str:
    if raw_feedback in ("Like", "Positive"):
        return "Like"
    if raw_feedback in ("Dislike", "Negative"):
        return "Dislike"
    return None


def _save_local_feedback(chat_log, feedback: str, comment: str = None, response_snippet: str = None) -> bool:
    local_saved = False
    if not getattr(chat_log, "logs", None):
        return False

    matched_log = None
    if response_snippet:
        for log in reversed(chat_log.logs):
            candidate_response = getattr(log, "response", None) or getattr(log, "content", None)
            if candidate_response and candidate_response.startswith(response_snippet):
                matched_log = log
                break

    if not matched_log:
        for log in reversed(chat_log.logs):
            if (getattr(log, "role", None) or "").lower() in ("assistant", "turn") and (
                getattr(log, "response", None) or getattr(log, "content", None)
            ):
                matched_log = log
                break

    if matched_log:
        matched_log.db_set("feedback", feedback, update_modified=False)
        if comment:
            matched_log.db_set("comment", comment, update_modified=False)
        local_saved = True

    return local_saved


def _sync_feedback_to_core(provider, session_id: str, feedback: str, comment: str = None, response_snippet: str = None) -> bool:
    try:
        client = provider._get_core_client()
        if not client:
            return False
        result = client.update_log_feedback_by_session(
            session_id=session_id,
            feedback=feedback,
            feedback_comment=comment,
            response_snippet=response_snippet,
        )
        return bool(result.get("success", False))
    except Exception as core_err:
        frappe.log_error(
            message=f"Failed to forward feedback to Core: {core_err}",
            title="Jive Core Feedback Sync Error",
        )
        return False


def _build_insights_not_installed_response() -> str:
    return """**Frappe Insights is not installed on this site.**

To use the Insights agent for creating charts and dashboards, please:

1. **Install Insights app:**
   ```
   bench get-app insights
   ```

2. **Install on your site:**
   ```
   bench --site your-site install-app insights
   ```

3. **Configure a data source** in Insights settings

Once installed, I can help you:
- Create charts (bar, line, pie, area, etc.)
- Build queries to analyze your data
- Create dashboards with multiple visualizations"""


def _build_insights_api_key_missing_response() -> str:
    return "**OpenAI API key is not configured.**\n\nPlease go to Jive Config and add your OpenAI API key, or enable Jive Core to use the Insights agent."


def _finalize_insights_response(chat_log, message: str, conversation_id: str, response_text: str, status: str = "success", error_message: str = None, extra: dict = None, request_payload: dict = None):
    from ampower_jive.utils.chat_support import _assistant_log_payload, add_message_to_log

    payload = request_payload or {"message": message, "mode": "insights", "conversation_id": conversation_id}
    assistant_kwargs = _assistant_log_payload(status=status, error_message=error_message or (response_text if status == "error" else None))
    assistant_kwargs["request_payload"] = payload
    add_message_to_log(chat_log, "user", message, "insights", request_payload=payload)
    add_message_to_log(
        chat_log,
        "assistant",
        response_text,
        "insights",
        **assistant_kwargs,
    )
    payload = {
        "error": False,
        "response": response_text,
        "conversation_id": conversation_id,
        "mode": "insights",
        "title": chat_log.title,
    }
    if extra:
        payload.update(extra)
    return payload


def clean_insights_response(response: str) -> str:
    """Clean up Insights response to remove duplicates and formatting issues."""
    if not response:
        return response

    response = _VIEW_CHART_LINK_RE.sub("", response)
    response = _VIEW_CHART_TEXT_RE.sub("", response)
    response = _CREATED_SECTION_RE.sub("", response)
    response = _INSIGHTS_BANNER_RE.sub("", response)
    response = re.sub(r"💡\s*\*?\*?Insights:?\*?\*?\s*\n(?=💡)", "", response)
    response = re.sub(r"💡\s*Insights:\s*\n", "", response)
    response = _remove_duplicate_sections(response, _INSIGHTS_SECTION_RE, _INSIGHTS_BOUNDARY_RE)
    response = _remove_duplicate_sections(response, _RECOMMENDATION_SECTION_RE, _RECOMMENDATION_BOUNDARY_RE)
    response = _remove_duplicate_sections(response, _FOLLOWUP_SECTION_RE, _FOLLOWUP_BOUNDARY_RE)
    links = list(_LINK_RE.finditer(response))
    if len(links) > 1:
        for match in reversed(links[1:]):
            response = response[:match.start()] + response[match.end():]

    response = re.sub(r"\n---\n---", "\n---", response)
    response = re.sub(r"\n{3,}", "\n\n", response)
    return response.strip()


def _is_error_response(response_text: str) -> bool:
    from ampower_jive.utils.chat_support import _is_error_response as _chat_support_error

    return _chat_support_error(response_text)
