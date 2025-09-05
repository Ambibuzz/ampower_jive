# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

from frappe.model.document import Document
import frappe
import json


class JiveLogs(Document):
    pass


@frappe.whitelist()
def write_jive_logs(user, logs, prompt=None, tool_name=None, doc_name=None, comment=None):
    if isinstance(logs, str):
        logs = json.loads(logs)

    if not isinstance(logs, list):
        return {"status": "error", "message": "Logs must be a list of entries"}

    def append_logs(doc):
        for log in logs:
            doc.append(
                "logs",
                {
                    "question": log.get("question"),
                    "answer": log.get("answer"),
                    "feedback": log.get("feedback"),
                    "tool": tool_name or log.get("tool_name"),
                    "prompt": prompt,
                    "comment": log.get("comment") or comment or "",
                },
            )

    if not doc_name:
        doc = frappe.get_doc({"doctype": "Jive Chat Logs", "user": user, "logs": []})
        append_logs(doc)
        status = "created"
    else:
        try:
            doc = frappe.get_doc("Jive Chat Logs", doc_name)
            append_logs(doc)
            status = "updated"
        except frappe.DoesNotExistError:
            return {"status": "error", "message": "Document not found"}

    (
        doc.insert(ignore_permissions=True)
        if status == "created"
        else doc.save(ignore_permissions=True)
    )
    frappe.db.commit()
    return {"status": status, "doc_name": doc.name}
