"""Extract compact HD Ticket detail payload for HD Tickets responses."""

from __future__ import annotations

import json
from typing import Any, Dict

from ampower_jive.hd_tickets.dtos import TicketRequestContext


class TicketRequestContextService:
    """Normalize explicit HD Ticket detail payload into a compact evidence block."""

    TICKET_DOCTYPE = "HD Ticket"

    def extract(self, context_payload: Any) -> TicketRequestContext:
        payload = self._normalize_payload(context_payload)
        if not payload:
            return TicketRequestContext()

        current_doc = payload.get("current_doc") if isinstance(payload.get("current_doc"), dict) else {}
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        page_field_values = payload.get("page_field_values") if isinstance(payload.get("page_field_values"), dict) else {}

        doctype = self._first_text(
            payload.get("doctype"),
            meta.get("doctype"),
            current_doc.get("doctype"),
        )
        if doctype != self.TICKET_DOCTYPE:
            return TicketRequestContext()

        customer_name = self._first_text(
            current_doc.get("customer"),
            page_field_values.get("customer"),
            payload.get("customer"),
        )
        customer_label = self._first_text(
            current_doc.get("customer_name"),
            current_doc.get("customer_display"),
            payload.get("label"),
            customer_name,
        )

        return TicketRequestContext(
            ticket_id=self._first_text(
                current_doc.get("name"),
                payload.get("name"),
                payload.get("docname"),
                page_field_values.get("name"),
            ),
            customer_name=customer_name,
            customer_label=customer_label,
            status=self._first_text(current_doc.get("status"), page_field_values.get("status")),
            subject=self._first_text(current_doc.get("subject"), payload.get("document_title"), payload.get("title")),
            priority=self._first_text(current_doc.get("priority"), page_field_values.get("priority")),
            agent_group=self._first_text(current_doc.get("agent_group"), page_field_values.get("agent_group")),
            description=self._first_text(current_doc.get("description")),
            source_type=self._first_text(payload.get("source_type")),
        )

    def _normalize_payload(self, context_payload: Any) -> Dict[str, Any]:
        if not context_payload:
            return {}
        if isinstance(context_payload, dict):
            return context_payload
        if isinstance(context_payload, str):
            try:
                parsed = json.loads(context_payload)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _first_text(self, *values: Any) -> str:
        for value in values:
            if value in (None, "", [], {}):
                continue
            text = str(value).strip()
            if text:
                return text
        return ""
