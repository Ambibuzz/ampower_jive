"""Helpdesk, support ticket, and feedback endpoints for Jive."""

from __future__ import annotations

import json
import os

import frappe

from ampower_jive.api_features.common import _save_local_feedback, _sync_feedback_to_core
from ampower_jive.utils.chat_support import add_message_to_log
from ampower_jive.utils.helpdesk_service import HelpdeskQueryService


def process_helpdesk_query(message: str, history: list, session_id: str = None, temperature: float = 0.3, max_tokens: int = 4096, custom_prompt: str = None) -> str | dict:
    """Process a helpdesk/how-to query using the service layer."""
    return HelpdeskQueryService().process(
        message=message,
        history=history,
        session_id=session_id,
        temperature=temperature,
        max_tokens=max_tokens,
        custom_prompt=custom_prompt,
    )


@frappe.whitelist()
def upload_helpdesk_context(file_url: str = None, file_name: str = None, session_id: str = None):
    """Upload and process a context file for helpdesk (per chat session)."""
    try:
        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        if not provider.is_feature_enabled("enable_file_upload"):
            return {"error": True, "message": "File upload is disabled in configuration"}

        from ampower_jive.utils.file_processor import extract_text_from_file, extract_from_file_doc, is_supported_file

        if not file_url and not file_name:
            return {"error": True, "message": "Either file_url or file_name is required"}

        if file_name:
            result = extract_from_file_doc(file_name)
        else:
            if not is_supported_file(file_url):
                return {"error": True, "message": "Unsupported file type. Supported: PDF, DOCX, CSV, TXT, JSON, MD"}
            result = extract_text_from_file(file_url)

        if not result.get("success"):
            return {"error": True, "message": result.get("error", "Failed to extract content")}

        content = result.get("content", "")
        session_id = session_id or "default"
        context_key = f"jive_context:{frappe.session.user}:{session_id}"
        existing_data = frappe.cache().hget(context_key, "files")
        existing_context = json.loads(existing_data) if existing_data else []
        display_name = os.path.basename(file_url or file_name or "file")

        context_entry = {
            "file_url": file_url or file_name,
            "file_name": display_name,
            "file_type": result.get("file_type"),
            "content": content,
            "char_count": result.get("char_count", len(content)),
            "added_at": frappe.utils.now(),
        }
        existing_context.append(context_entry)
        frappe.cache().hset(context_key, "files", json.dumps(existing_context))

        return {
            "error": False,
            "message": "Context added",
            "file_name": display_name,
            "file_type": result.get("file_type"),
            "char_count": result.get("char_count", len(content)),
            "total_context_files": len(existing_context),
        }

    except Exception as e:
        frappe.log_error("Upload Helpdesk Context Error", frappe.get_traceback())
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def get_helpdesk_context(session_id: str = None):
    """Get the current helpdesk context files for the session."""
    try:
        session_id = session_id or "default"
        context_key = f"jive_context:{frappe.session.user}:{session_id}"
        existing_data = frappe.cache().hget(context_key, "files")
        context_files = json.loads(existing_data) if existing_data else []

        summary = []
        for ctx in context_files:
            summary.append({
                "file_url": ctx.get("file_url"),
                "file_name": ctx.get("file_name", ctx.get("file_url", "").split("/")[-1]),
                "file_type": ctx.get("file_type"),
                "char_count": ctx.get("char_count"),
            })

        return {"error": False, "context_files": summary, "total_files": len(summary)}

    except Exception as e:
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def clear_helpdesk_context(session_id: str = None):
    """Clear all helpdesk context files for the session."""
    try:
        session_id = session_id or "default"
        context_key = f"jive_context:{frappe.session.user}:{session_id}"
        frappe.cache().hdel(context_key, "files")
        return {"error": False, "message": "Context cleared"}

    except Exception as e:
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def remove_helpdesk_context_file(file_url: str, session_id: str = None):
    """Remove a specific context file from the session."""
    try:
        session_id = session_id or "default"
        context_key = f"jive_context:{frappe.session.user}:{session_id}"
        existing_data = frappe.cache().hget(context_key, "files")
        context_files = json.loads(existing_data) if existing_data else []
        context_files = [ctx for ctx in context_files if ctx.get("file_url") != file_url]
        frappe.cache().hset(context_key, "files", json.dumps(context_files))
        return {"error": False, "message": "File removed", "remaining_files": len(context_files)}

    except Exception as e:
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def mark_issue_resolved(conversation_id: str, resolved: bool, feedback: str = None):
    """Mark whether the helpdesk issue was resolved and store feedback."""
    try:
        if not conversation_id:
            return {"error": True, "message": "Conversation ID required"}

        chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
        if chat_log.user != frappe.session.user:
            return {"error": True, "message": "Access denied"}

        feedback_msg = "User feedback: " + ("Issue resolved ✅" if resolved else "Issue not resolved ❌")
        if feedback:
            feedback_msg += f" - {feedback}"

        add_message_to_log(chat_log, "system", feedback_msg, chat_log.mode or "helpdesk")
        return {
            "error": False,
            "message": "Thank you for your feedback!" if resolved else "We're sorry we couldn't help. Please submit a support ticket.",
        }

    except Exception as e:
        frappe.log_error("Mark Issue Resolved Error", str(e))
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def submit_chat_message_feedback(conversation_id: str, feedback: str, comment: str = None, message_idx: int = None, response_snippet: str = None):
    """Submit like/dislike feedback for the assistant message."""
    try:
        if not conversation_id or not feedback:
            return {"error": True, "message": "conversation_id and feedback are required"}

        if feedback not in ["Like", "Dislike"]:
            return {"error": True, "message": "feedback must be 'Like' or 'Dislike'"}

        if not frappe.db.exists("Jive Chat Logs", conversation_id):
            return {"error": True, "message": "Conversation not found"}

        chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
        if chat_log.user != frappe.session.user:
            return {"error": True, "message": "Access denied"}

        local_saved = _save_local_feedback(chat_log, feedback, comment, response_snippet)
        from ampower_jive.utils.chat_support import safe_commit

        safe_commit()

        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        if not provider.is_core_mode():
            return {"error": False, "message": "Feedback saved locally"}

        core_synced = _sync_feedback_to_core(provider, chat_log.session_id, feedback, comment, response_snippet)
        if core_synced:
            return {"error": False, "message": "Feedback submitted successfully"}
        if local_saved:
            return {"error": False, "message": "Feedback saved locally (Core sync pending)"}
        return {"error": False, "message": "Feedback recorded"}

    except Exception as e:
        frappe.log_error(f"Submit Interaction Feedback Error: {e}", frappe.get_traceback())
        return {"error": True, "message": str(e)}
