"""Permission helpers used by RAG routing and retrieval."""

from __future__ import annotations

import frappe


def _has_user_permission(user: str, doctype: str, value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return True
    if user == "Administrator":
        return True

    try:
        user_permissions = frappe.defaults.get_user_permissions(user or frappe.session.user) or {}
        allowed_documents = {
            perm.get("doc")
            for perm in (user_permissions.get(doctype) or [])
            if perm.get("doc")
        }
        return value in allowed_documents
    except Exception:
        return False


def can_access_scoped_vector_database(user: str, company: str = "", customer: str = "") -> bool:
    """Return whether the user is allowed to query a scoped vector database."""
    return _has_user_permission(user, "Company", company) and _has_user_permission(user, "Customer", customer)
