"""Conversation management endpoints for Jive."""

from __future__ import annotations

import frappe

from ampower_jive.utils.chat_support import _expand_chat_log_row, safe_commit


@frappe.whitelist()
def get_conversation_history(conversation_id: str):
    """Get the conversation history for a given conversation."""
    try:
        chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
        if chat_log.user != frappe.session.user:
            return {"error": True, "message": "Access denied"}

        messages = []
        if chat_log.logs:
            for log in chat_log.logs:
                messages.extend(_expand_chat_log_row(log))

        return {
            "error": False,
            "messages": messages,
            "conversation_id": conversation_id,
            "title": chat_log.title,
            "mode": chat_log.mode or "query",
        }

    except frappe.DoesNotExistError:
        return {"error": True, "message": "Conversation not found"}
    except Exception as e:
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def get_user_conversations():
    """Get list of user's conversations with titles."""
    try:
        conversations = frappe.get_all(
            "Jive Chat Logs",
            filters={"user": frappe.session.user, "status": "Active"},
            fields=["name", "title", "mode", "creation", "modified"],
            order_by="modified desc",
            limit=50,
        )

        for conv in conversations:
            if not conv.get("title"):
                try:
                    chat_log = frappe.get_doc("Jive Chat Logs", conv.name)
                    if chat_log.logs and len(chat_log.logs) > 0:
                        first_log = chat_log.logs[0]
                        first_content = (
                            getattr(first_log, "question", None)
                            or getattr(first_log, "content", None)
                            or getattr(first_log, "response", None)
                            or ""
                        )
                        title = first_content[:50] + "..." if len(first_content) > 50 else first_content
                        conv["title"] = title or "New conversation"
                        if title:
                            frappe.db.set_value("Jive Chat Logs", conv.name, "title", title[:100], update_modified=False)
                    else:
                        conv["title"] = "New conversation"
                except Exception:
                    conv["title"] = "New conversation"

        safe_commit()
        return {"error": False, "conversations": conversations}

    except Exception as e:
        frappe.log_error("Get User Conversations Error", frappe.get_traceback())
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def clear_conversation(conversation_id: str):
    """Clear/delete a conversation."""
    try:
        chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
        if chat_log.user != frappe.session.user:
            return {"error": True, "message": "Access denied"}

        frappe.delete_doc("Jive Chat Logs", conversation_id, ignore_permissions=True)
        safe_commit()
        return {"error": False, "message": "Conversation deleted"}

    except Exception as e:
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def archive_conversation(conversation_id: str):
    """Archive a conversation instead of deleting."""
    try:
        chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
        if chat_log.user != frappe.session.user:
            return {"error": True, "message": "Access denied"}

        chat_log.status = "Archived"
        chat_log.save(ignore_permissions=True)
        safe_commit()
        return {"error": False, "message": "Conversation archived"}

    except Exception as e:
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def update_conversation_title(conversation_id: str, title: str):
    """Update the title of a conversation."""
    try:
        if not title or not title.strip():
            return {"error": True, "message": "Title cannot be empty"}

        chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
        if chat_log.user != frappe.session.user:
            return {"error": True, "message": "Access denied"}

        chat_log.title = title.strip()[:100]
        chat_log.save(ignore_permissions=True)
        safe_commit()
        return {"error": False, "message": "Title updated", "title": chat_log.title}

    except Exception as e:
        return {"error": True, "message": str(e)}
