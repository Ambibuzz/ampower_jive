"""Shared helpers for Jive chat orchestration and logging."""

from __future__ import annotations

from collections import deque
import json
from typing import Any, Dict, List, Optional

import frappe


def safe_commit() -> None:
    """Commit while tolerating realtime log cleanup issues."""
    try:
        if not hasattr(frappe.local, "_realtime_log"):
            frappe.local._realtime_log = []
        frappe.db.commit()
    except AttributeError:
        pass


def _serialize_request_payload(request_payload: Any) -> Optional[str]:
    """Serialize a request payload for storage in a long text field."""
    if request_payload is None:
        return None
    if isinstance(request_payload, str):
        return request_payload

    try:
        return json.dumps(request_payload, default=str, ensure_ascii=False)
    except Exception:
        return str(request_payload)


def create_new_conversation(mode: str = "query", session_id: str = None):
    """Create a new chat log document with the expected defaults."""
    chat_log = frappe.get_doc(
        {
            "doctype": "Jive Chat Logs",
            "user": frappe.session.user,
            "mode": mode,
            "session_id": session_id,
            "status": "Active",
        }
    )
    chat_log.insert(ignore_permissions=True)
    safe_commit()
    return chat_log


def get_messages_from_log(chat_log, max_messages: int = 10):
    """Flatten the persisted child rows into the UI history format."""
    if not getattr(chat_log, "logs", None):
        return []

    collected_chunks = deque()
    collected_messages = 0
    for log in reversed(chat_log.logs):
        expanded = _expand_chat_log_row(log)
        if not expanded:
            continue

        if max_messages and collected_messages and (collected_messages + len(expanded) > max_messages):
            break

        collected_chunks.appendleft(expanded)
        collected_messages += len(expanded)

        if max_messages and collected_messages >= max_messages:
            break

    history = []
    for chunk in collected_chunks:
        history.extend(chunk)
    return history


def _normalize_feedback_value(raw_feedback: str = None) -> Optional[str]:
    """Normalize stored feedback to the UI vocabulary."""
    if raw_feedback in ("Like", "Positive"):
        return "Like"
    if raw_feedback in ("Dislike", "Negative"):
        return "Dislike"
    return None


def _build_history_message(log, role: str, content: str, feedback: str = None) -> dict:
    """Serialize a child row into the flat message structure used by the UI."""
    timestamp = getattr(log, "timestamp", None)
    normalized_feedback = _normalize_feedback_value(feedback)

    return {
        "role": role or "user",
        "content": content or "",
        "mode": getattr(log, "mode", None) or "query",
        "timestamp": str(timestamp) if timestamp else None,
        "status": getattr(log, "status", None) or None,
        "tokens_in": int(getattr(log, "tokens_in", 0) or 0),
        "tokens_out": int(getattr(log, "tokens_out", 0) or 0),
        "total_tokens": int(getattr(log, "total_tokens", 0) or 0),
        "processing_time_ms": int(getattr(log, "processing_time_ms", 0) or 0),
        "feedback": normalized_feedback if role == "assistant" else None,
        "feedback_submitted": bool(normalized_feedback) if role == "assistant" else False,
        "feedback_open": None,
        "comment": getattr(log, "comment", None) or None,
        "error_message": getattr(log, "error_message", None) or None,
        "error_traceback": getattr(log, "error_traceback", None) or None,
        "tool_used": getattr(log, "tool_used", None) or None,
    }


def _expand_chat_log_row(log) -> list:
    """Expand a persisted row into the flat message list expected by the chat UI."""
    role = (getattr(log, "role", None) or "user").lower()
    question = getattr(log, "question", None) or ""
    response = getattr(log, "response", None) or ""
    content = getattr(log, "content", None) or ""
    feedback = getattr(log, "feedback", None) or None

    messages = []
    if question:
        messages.append(_build_history_message(log, "user", question))
    if response:
        messages.append(_build_history_message(log, "assistant", response, feedback=feedback))
        return messages
    if role == "assistant" and content:
        messages.append(_build_history_message(log, "assistant", content, feedback=feedback))
        return messages
    if role not in ("turn", "user", "assistant") and content:
        messages.append(_build_history_message(log, role, content))
        return messages
    if not messages and content:
        fallback_role = "assistant" if role == "assistant" else "user"
        messages.append(_build_history_message(log, fallback_role, content, feedback=feedback))
    return messages


def _get_last_token_usage_detail() -> dict:
    """Return the latest raw token usage captured for the active request."""
    detail = getattr(frappe.local, "jive_token_usage_detail", None)
    return detail if isinstance(detail, dict) else {}


def _assistant_log_payload(
    status: str = "success",
    error_message: str = None,
    error_traceback: str = None,
    feedback: str = None,
    comment: str = None,
) -> dict:
    """Build metadata for an assistant log row from the latest token usage."""
    token_usage = _get_last_token_usage_detail()
    return {
        "status": status,
        "tokens_in": token_usage.get("tokens_in", 0),
        "tokens_out": token_usage.get("tokens_out", 0),
        "processing_time_ms": token_usage.get("processing_time_ms", 0),
        "feedback": feedback,
        "comment": comment,
        "error_message": error_message,
        "error_traceback": error_traceback,
    }


def _is_error_response(response_text: str) -> bool:
    """Best-effort detection for error responses returned as plain text."""
    if not response_text:
        return False

    error_markers = (
        "i encountered an error",
        "openai api key is not configured",
        "request timed out",
        "failed to get response",
        "an error occurred",
        "**error**",
    )
    normalized = response_text.strip().lower()
    return any(marker in normalized for marker in error_markers)


def add_message_to_log(
    chat_log,
    role: str,
    content: str,
    mode: str = "query",
    status: str = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    processing_time_ms: int = 0,
    feedback: str = None,
    comment: str = None,
    error_message: str = None,
    error_traceback: str = None,
    request_payload: Any = None,
):
    """Add or complete a single chat turn in the child table."""
    normalized_role = (role or "user").lower()
    now_value = frappe.utils.now()

    if normalized_role == "user":
        row = {
            "role": "turn",
            "question": content,
            "content": content,
            "mode": mode,
            "timestamp": now_value,
        }
        if request_payload is not None:
            row["request_payload"] = _serialize_request_payload(request_payload)
        chat_log.append("logs", row)
        chat_log.save(ignore_permissions=True)
        safe_commit()
        return

    pending_turn = None
    if normalized_role == "assistant" and getattr(chat_log, "logs", None):
        for log in reversed(chat_log.logs):
            log_role = (getattr(log, "role", None) or "").lower()
            if log_role != "turn":
                continue
            if str(getattr(log, "mode", None) or "").lower() != str(mode or "").lower():
                continue
            if getattr(log, "question", None) and not getattr(log, "response", None):
                pending_turn = log
                break

    if pending_turn:
        pending_turn.response = content
        pending_turn.content = content
        pending_turn.role = "turn"
        pending_turn.mode = mode
        pending_turn.timestamp = pending_turn.timestamp or now_value
        if request_payload is not None:
            pending_turn.request_payload = _serialize_request_payload(request_payload)
        if status:
            pending_turn.status = status
        elif not pending_turn.status:
            pending_turn.status = "error" if error_message or error_traceback else "success"
        pending_turn.tokens_in = int(tokens_in or 0)
        pending_turn.tokens_out = int(tokens_out or 0)
        pending_turn.total_tokens = int(tokens_in or 0) + int(tokens_out or 0)
        pending_turn.processing_time_ms = int(processing_time_ms or 0)
        pending_turn.feedback = feedback or pending_turn.feedback
        pending_turn.comment = comment or pending_turn.comment
        if error_message:
            pending_turn.error_message = error_message
        if error_traceback:
            pending_turn.error_traceback = error_traceback
    else:
        row = {
            "role": normalized_role,
            "content": content,
            "mode": mode,
            "timestamp": now_value,
        }
        if request_payload is not None:
            row["request_payload"] = _serialize_request_payload(request_payload)
        if status:
            row["status"] = status
        if normalized_role == "assistant":
            row["tokens_in"] = int(tokens_in or 0)
            row["tokens_out"] = int(tokens_out or 0)
            row["total_tokens"] = int(tokens_in or 0) + int(tokens_out or 0)
            row["processing_time_ms"] = int(processing_time_ms or 0)
            if error_message:
                row["error_message"] = error_message
            if error_traceback:
                row["error_traceback"] = error_traceback
        if feedback:
            row["feedback"] = feedback
        if comment:
            row["comment"] = comment
        chat_log.append("logs", row)

    chat_log.save(ignore_permissions=True)
    safe_commit()
