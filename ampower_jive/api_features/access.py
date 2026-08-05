"""Access control and configuration endpoints for Jive."""

from __future__ import annotations

import frappe

from ampower_jive.utils.app_dependencies import is_helpdesk_installed as _is_helpdesk_installed
from ampower_jive.utils.chat_support import safe_commit
from ampower_jive.utils.config_defaults import apply_default_jive_config


def _is_truthy(value) -> bool:
    try:
        return str(value).lower() in ("1", "true", "yes", "on")
    except Exception:
        return bool(value)


def is_website_user(user=None) -> bool:
    """Return whether the given user is a website user."""
    if not user:
        user = frappe.session.user

    if not user or user in ("Guest", "Administrator"):
        return False

    try:
        return frappe.db.get_value("User", user, "user_type") == "Website User"
    except Exception:
        return False


def has_jive_access(user=None, portal_access: int | bool = False):
    """
    Check if user has access to USE Jive chat.

    Access is granted ONLY if:
    - User is "Administrator" (always has access)
    - User has "Jive User" role explicitly assigned
    - Portal access is explicitly enabled for a logged-in website user
    """
    if not user:
        user = frappe.session.user

    if user == "Administrator":
        return True

    if _is_truthy(portal_access) and is_website_user(user):
        return True

    if "Jive User" in frappe.get_roles(user):
        return True

    return False


def is_system_manager(user=None):
    """Check if user is a System Manager (can configure Jive)."""
    if not user:
        user = frappe.session.user

    if user == "Administrator":
        return True

    return "System Manager" in frappe.get_roles(user)


@frappe.whitelist()
def check_helpdesk_installed():
    """Return whether the Helpdesk app is installed for this site."""
    return {"installed": _is_helpdesk_installed()}


@frappe.whitelist()
def check_jive_access(portal_access: int = 0):
    """Check if the current user has access to Jive."""
    user = frappe.session.user
    has_access = has_jive_access(user, portal_access=portal_access)
    is_admin = is_system_manager(user)

    if has_access:
        message = "You have access to Jive"
    elif is_admin:
        message = "Configure Jive to start using it"
    else:
        message = "You don't have permission to use Jive. Please contact your administrator to grant you the 'Jive User' role."

    return {
        "has_access": has_access,
        "is_admin": is_admin,
        "user": user,
        "roles": frappe.get_roles(user),
        "message": message,
    }


def get_allowed_doctypes_list(config):
    """Get allowed doctypes from child table."""
    allowed_doctypes = []
    if config.included_doctypes:
        for row in config.included_doctypes:
            dt = row.doctype_name
            if dt and frappe.has_permission(dt, "read"):
                allowed_doctypes.append(dt)
    return allowed_doctypes


BUILTIN_CHAT_MODES = {"query", "helpdesk", "hd_tickets", "agent", "insights", "rag"}


def normalize_chat_mode(mode: str) -> str:
    mode = (mode or "query").lower().strip()
    return "query" if mode == "context" else mode


def get_mode_config(provider, mode: str) -> dict:
    """Get mode metadata from the provider, if it exists."""
    try:
        mode_config = provider.get_agent_config(mode) or {}
        return mode_config if mode_config.get("is_available", False) else {}
    except Exception:
        return {}


def is_mode_available(provider, mode: str, portal_access: int | bool = False) -> bool:
    """Check whether a mode is enabled for the current tenant."""
    normalized_mode = normalize_chat_mode(mode)
    if normalized_mode == "context":
        normalized_mode = "query"

    try:
        if normalized_mode == "rag" and _is_truthy(portal_access):
            config = provider.get_all_config_for_frontend() or {}
            return bool(config.get("enable_rag_helpdesk")) and bool((provider.get_agent_config(normalized_mode) or {}).get("visible_in_chat", True))

        return bool((provider.get_agent_config(normalized_mode) or {}).get("is_available", False))
    except Exception:
        return False


@frappe.whitelist()
def get_jive_config(portal_access: int = 0):
    """
    Get the Jive configuration for the current user.
    Returns config settings needed by the frontend.
    Creates the config singleton if it doesn't exist.
    """
    try:
        user = frappe.session.user
        user_has_access = has_jive_access(user, portal_access=portal_access)
        user_is_admin = is_system_manager(user)

        try:
            config = frappe.get_single("Jive Config")
        except frappe.DoesNotExistError:
            config = frappe.new_doc("Jive Config")
            apply_default_jive_config(config)
            config.save(ignore_permissions=True)
            safe_commit()

        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        config_data = provider.get_all_config_for_frontend()
        if config_data.get("active"):
            try:
                from ampower_jive.agent.schema_cache import refresh_schema_cache

                frappe.enqueue(
                    refresh_schema_cache,
                    queue="short",
                    timeout=60,
                    force=False,
                )
            except Exception:
                pass

        config_data["rag_helpdesk_documents"] = []
        if _is_truthy(portal_access) and config_data.get("enable_rag_helpdesk"):
            try:
                from ampower_jive.agent.rag_resolution import RagResolver, VECTOR_DATABASE_MODE
                from ampower_jive.agent.vector_database_service import VectorDatabaseRagService

                target = RagResolver().resolve(user=user)
                if target.pipeline_mode == VECTOR_DATABASE_MODE and target.vector_databases:
                    document_titles = []
                    seen_titles = set()
                    for vector_database_name in target.vector_databases:
                        service = VectorDatabaseRagService(vector_database_name, site_name=frappe.local.site)
                        for row in service.get_documents():
                            title = str(getattr(row, "document_title", "") or "").strip()
                            if not title or title in seen_titles:
                                continue
                            seen_titles.add(title)
                            document_titles.append(title)
                    config_data["rag_helpdesk_documents"] = document_titles
            except Exception:
                config_data["rag_helpdesk_documents"] = []

        config_data["has_access"] = user_has_access
        config_data["is_admin"] = user_is_admin
        config_data["user"] = user
        config_data["portal_access"] = _is_truthy(portal_access)
        return config_data

    except Exception as e:
        frappe.log_error("Jive Config Error", str(e))
        return {
            "active": False,
            "allowed_doctypes": [],
            "has_access": is_system_manager(),
            "is_admin": is_system_manager(),
            "error": str(e),
            "setup_required": True,
        }
