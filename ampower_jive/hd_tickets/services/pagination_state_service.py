"""Conversation-scoped pagination state for HD Tickets lists and searches."""

from __future__ import annotations

from typing import Any, Dict

import frappe

from ampower_jive.hd_tickets.constants import MODE_KEY, PAGINATION_STATE_TTL_SECONDS


class PaginationStateService:
    """Persist and retrieve the last HD Tickets page state per conversation."""

    def get(self, conversation_id: str) -> Dict[str, Any]:
        if not conversation_id:
            return {}
        value = frappe.cache().get_value(self._cache_key(conversation_id))
        return value if isinstance(value, dict) else {}

    def set(self, conversation_id: str, payload: Dict[str, Any]) -> None:
        if not conversation_id:
            return
        frappe.cache().set_value(
            self._cache_key(conversation_id),
            payload or {},
            expires_in_sec=PAGINATION_STATE_TTL_SECONDS,
        )

    def _cache_key(self, conversation_id: str) -> str:
        return f"{MODE_KEY}_pagination_{frappe.session.user}_{conversation_id}"
