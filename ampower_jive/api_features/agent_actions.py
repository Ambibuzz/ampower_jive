"""Agent approval actions for Jive."""

from __future__ import annotations

import json

import frappe

from ampower_jive.utils.chat_support import _assistant_log_payload, add_message_to_log


@frappe.whitelist()
def approve_plan(conversation_id: str):
    """Approve and execute a pending agent plan."""
    try:
        plan_key = f"agent_plan_{frappe.session.user}_{conversation_id}"
        plan = frappe.cache().get_value(plan_key)

        if not plan:
            return {"error": True, "message": "No pending plan found or plan expired"}

        from ampower_jive.agent.agent_tools import execute_planned_action

        results = []
        for action in plan:
            results.append(execute_planned_action(action))

        frappe.cache().delete_value(plan_key)
        all_success = all(r.get("success") for r in results)

        try:
            chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
            chat_mode = getattr(chat_log, "mode", None) or "agent"
            result_summary = "✅ All operations completed successfully" if all_success else "⚠️ Some operations failed"
            add_message_to_log(
                chat_log,
                "assistant",
                f"{result_summary}\n\n{json.dumps(results, indent=2)}",
                chat_mode,
                **_assistant_log_payload(status="success" if all_success else "error"),
            )
        except Exception:
            pass

        return {
            "error": not all_success,
            "message": "All operations completed successfully" if all_success else "Some operations failed",
            "results": results,
        }

    except Exception as e:
        frappe.log_error("Plan Approval Error", frappe.get_traceback())
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def reject_plan(conversation_id: str):
    """Reject a pending agent plan."""
    plan_key = f"agent_plan_{frappe.session.user}_{conversation_id}"
    frappe.cache().delete_value(plan_key)

    try:
        chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
        chat_mode = getattr(chat_log, "mode", None) or "agent"
        add_message_to_log(
            chat_log,
            "assistant",
            "Operation cancelled by user.",
            chat_mode,
            **_assistant_log_payload(status="success"),
        )
    except Exception:
        pass

    return {"error": False, "message": "Plan rejected"}
