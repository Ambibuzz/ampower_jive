"""Helpers for optional app dependencies."""

from __future__ import annotations

from typing import List

import frappe


def is_app_installed(app_name: str) -> bool:
    """Return whether the given app is installed on the current site."""
    try:
        return app_name in (frappe.get_installed_apps() or [])
    except Exception:
        return False


def is_helpdesk_installed() -> bool:
    """Return whether the Helpdesk app is installed on the current site."""
    return is_app_installed("helpdesk")


def get_helpdesk_customer_links(user: str) -> List[str]:
    """Return linked HD Customer names for a user when Helpdesk is installed."""
    if not user or not is_helpdesk_installed():
        return []

    try:
        from helpdesk.utils import get_customer

        return list(get_customer(user) or [])
    except Exception:
        return []


def is_helpdesk_agent(user: str | None = None) -> bool:
    """Return whether the user is a Helpdesk agent when Helpdesk is installed."""
    if not is_helpdesk_installed():
        return False

    try:
        from helpdesk.utils import is_agent

        return bool(is_agent(user) if user else is_agent())
    except Exception:
        return False
