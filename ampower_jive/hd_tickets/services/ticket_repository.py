"""Live Helpdesk ticket reads for the HD Tickets mode."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

import frappe

from ampower_jive.api_features.access import is_website_user
from ampower_jive.hd_tickets.constants import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    RELATED_SEARCH_LIMIT,
    TICKET_LIST_FIELDS,
)
from ampower_jive.utils.app_dependencies import get_helpdesk_customer_links, is_helpdesk_installed

TICKET_DETAIL_FIELDS = list(
    dict.fromkeys(
        [
            *TICKET_LIST_FIELDS,
            "description",
            "contact",
            "raised_by",
        ]
    )
)
CONTACT_FIELDS = ["name", "email_id", "phone", "mobile_no", "image"]
COMMUNICATION_FIELDS = [
    "name",
    "subject",
    "content",
    "sender",
    "recipients",
    "cc",
    "bcc",
    "sent_or_received",
    "user",
    "creation",
    "communication_date",
    "delivery_status",
]


class TicketRepository:
    """Read-only access to Helpdesk ticket data with native permissions."""

    def list_tickets(
        self,
        filters: Dict | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        fields: List[str] | None = None,
        search_text: str = "",
        order_by: str = "modified desc",
    ) -> List[Dict]:
        """Return visible ticket rows for the current user."""
        or_filters = self._build_direct_search_filters(search_text)
        return self._query_tickets(
            filters=filters,
            or_filters=or_filters,
            fields=fields or list(TICKET_LIST_FIELDS),
            limit=min(limit or DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT),
            offset=max(offset or 0, 0),
            limit_cap=MAX_LIST_LIMIT,
            order_by=order_by,
        )

    def count_tickets(self, filters: Dict | None = None) -> int:
        """Count visible tickets without bypassing doctype permissions."""
        if self._uses_manual_visibility():
            return int(frappe.db.count("HD Ticket", self._scoped_ticket_filters(filters)) or 0)

        rows = frappe.get_list("HD Ticket", filters=filters or {}, fields=["count(name) as total"], limit_page_length=1)
        if not rows:
            return 0
        return int(rows[0].get("total") or 0)

    def get_ticket_detail(self, ticket_id: str) -> Dict:
        """Return a full ticket payload using Helpdesk's own detail API."""
        if not is_helpdesk_installed():
            return {}
        if self._uses_manual_visibility():
            ticket = self._get_visible_ticket(ticket_id, fields=TICKET_DETAIL_FIELDS)
            if not ticket:
                return {}
            ticket["contact"] = self._get_contact_payload(ticket)
            return ticket

        from helpdesk.helpdesk.doctype.hd_ticket import api as hd_ticket_api

        return hd_ticket_api.get_one(ticket_id, is_customer_portal=is_website_user())

    def get_ticket_activities(self, ticket_id: str) -> Dict:
        """Return visible ticket activity data."""
        if not is_helpdesk_installed():
            return {}
        if self._uses_manual_visibility():
            ticket = self._get_visible_ticket(ticket_id, fields=["name"])
            if not ticket:
                return {}
            return {
                "communications": frappe.get_all(
                    "Communication",
                    filters={"reference_doctype": "HD Ticket", "reference_name": ticket_id},
                    fields=list(COMMUNICATION_FIELDS),
                    order_by="creation desc",
                    limit_page_length=MAX_LIST_LIMIT,
                ),
                "comments": [],
                "history": [],
                "views": [],
                "calls": [],
            }

        from helpdesk.helpdesk.doctype.hd_ticket import api as hd_ticket_api

        return hd_ticket_api.get_ticket_activities(ticket_id)

    def has_visible_ticket_for_customer(self, customer_name: str) -> bool:
        """Return whether the current user can see at least one ticket for a customer."""
        if not customer_name:
            return False
        return self.count_tickets({"customer": customer_name}) > 0

    def search_tickets(
        self,
        search_text: str,
        filters: Dict | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> Tuple[List[Dict], Dict[str, List[str]]]:
        """Search visible tickets by ticket fields and related ticket text."""
        matches = defaultdict(list)
        target_window = max((offset or 0) + (limit or DEFAULT_LIST_LIMIT), limit or DEFAULT_LIST_LIMIT, RELATED_SEARCH_LIMIT)
        direct_rows = self._query_tickets(
            filters=filters,
            or_filters=self._build_direct_search_filters(search_text),
            fields=list(TICKET_LIST_FIELDS),
            limit=target_window,
            offset=0,
            limit_cap=target_window,
            order_by="modified desc",
        )
        ordered_ticket_names = []
        ticket_map = {}

        for row in direct_rows:
            ticket_name = row.get("name")
            if not ticket_name:
                continue
            ordered_ticket_names.append(ticket_name)
            ticket_map[ticket_name] = row
            matches[ticket_name].append("ticket")

        related_names = self._search_related_ticket_names(search_text, limit=target_window)
        for ticket_name, sources in related_names.items():
            if ticket_name not in ordered_ticket_names:
                ordered_ticket_names.append(ticket_name)
            for source in sources:
                if source not in matches[ticket_name]:
                    matches[ticket_name].append(source)

        missing_names = [name for name in ordered_ticket_names if name not in ticket_map]
        if missing_names:
            extra_rows = self._query_tickets(
                filters={**(filters or {}), "name": ["in", missing_names]},
                fields=list(TICKET_LIST_FIELDS),
                limit=max(len(missing_names), DEFAULT_LIST_LIMIT),
                limit_cap=max(len(missing_names), DEFAULT_LIST_LIMIT),
                order_by="modified desc",
            )
            ticket_map.update({row.get("name"): row for row in extra_rows if row.get("name")})

        offset_value = max(offset or 0, 0)
        page_names = [name for name in ordered_ticket_names if name in ticket_map][offset_value : offset_value + limit]
        ordered_rows = [ticket_map[name] for name in page_names]
        ordered_sources = {name: matches[name] for name in page_names}
        return ordered_rows, ordered_sources

    def _get_linked_hd_customers(self, user: str) -> List[str]:
        return get_helpdesk_customer_links(user)

    def _get_visible_hd_customers(self, user: str) -> List[str]:
        if not user:
            return []

        permissions = frappe.defaults.get_user_permissions(user) or {}
        customer_names = {
            permission.get("doc")
            for permission in (permissions.get("HD Customer") or [])
            if permission.get("doc")
        }
        customer_names.update(customer_name for customer_name in self._get_linked_hd_customers(user) if customer_name)
        return sorted(customer_names)

    def _uses_manual_visibility(self, user: str | None = None) -> bool:
        user = user or frappe.session.user
        return bool(user and user != "Administrator" and self._get_visible_hd_customers(user))

    def _scoped_ticket_filters(self, filters: Dict | None = None, user: str | None = None) -> Dict:
        scoped_filters = dict(filters or {})
        visible_customers = self._get_visible_hd_customers(user or frappe.session.user)
        if not visible_customers:
            return scoped_filters

        customer_filter = scoped_filters.get("customer")
        if not customer_filter:
            scoped_filters["customer"] = ["in", visible_customers]
            return scoped_filters

        if isinstance(customer_filter, str):
            scoped_filters["customer"] = (
                customer_filter if customer_filter in visible_customers else "__no_visible_hd_customer__"
            )
            return scoped_filters

        if (
            isinstance(customer_filter, list)
            and len(customer_filter) == 2
            and customer_filter[0] == "in"
            and isinstance(customer_filter[1], (list, tuple, set))
        ):
            allowed_customers = [customer for customer in customer_filter[1] if customer in visible_customers]
            scoped_filters["customer"] = ["in", allowed_customers or ["__no_visible_hd_customer__"]]
            return scoped_filters

        scoped_filters["customer"] = ["in", visible_customers]
        return scoped_filters

    def _query_tickets(
        self,
        *,
        filters: Dict | None = None,
        or_filters: List[List[str]] | None = None,
        fields: List[str] | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        limit_cap: int | None = None,
        order_by: str = "modified desc",
    ) -> List[Dict]:
        cap_value = max(int(limit_cap or MAX_LIST_LIMIT), 1)
        limit_value = min(limit or DEFAULT_LIST_LIMIT, cap_value)
        offset_value = max(offset or 0, 0)
        if self._uses_manual_visibility():
            return frappe.get_all(
                "HD Ticket",
                filters=self._scoped_ticket_filters(filters),
                or_filters=or_filters or None,
                fields=fields or list(TICKET_LIST_FIELDS),
                limit_page_length=limit_value,
                start=offset_value,
                order_by=order_by,
            )

        return frappe.get_list(
            "HD Ticket",
            filters=filters or {},
            or_filters=or_filters or None,
            fields=fields or list(TICKET_LIST_FIELDS),
            limit_page_length=limit_value,
            start=offset_value,
            order_by=order_by,
        )

    def _get_visible_ticket(self, ticket_id: str, fields: List[str] | None = None) -> Dict:
        if not ticket_id:
            return {}
        rows = self._query_tickets(
            filters={"name": ticket_id},
            fields=fields or list(TICKET_DETAIL_FIELDS),
            limit=1,
            order_by="modified desc",
        )
        return rows[0] if rows else {}

    def _get_contact_payload(self, ticket: Dict) -> Dict:
        contact_name = ticket.get("contact")
        if contact_name:
            contact = frappe.db.get_value("Contact", contact_name, CONTACT_FIELDS, as_dict=True) or {}
            if contact:
                return contact

        raised_by = ticket.get("raised_by")
        if raised_by:
            return {
                "email_id": raised_by,
                "name": str(raised_by).split("@")[0],
            }
        return {}

    def _build_direct_search_filters(self, search_text: str) -> List[List[str]]:
        term = (search_text or "").strip()
        if not term:
            return []
        like_term = f"%{term}%"
        return [
            ["name", "like", like_term],
            ["subject", "like", like_term],
            ["description", "like", like_term],
        ]

    def _search_related_ticket_names(self, search_text: str, limit: int) -> Dict[str, List[str]]:
        term = (search_text or "").strip()
        if not term:
            return {}

        ticket_sources = defaultdict(list)
        like_term = f"%{term}%"
        self._collect_related_matches(
            ticket_sources=ticket_sources,
            doctype="HD Ticket Comment",
            filters={"content": ["like", like_term]},
            field_name="reference_ticket",
            source_name="comment",
            limit=limit,
        )
        self._collect_related_matches(
            ticket_sources=ticket_sources,
            doctype="Communication",
            filters={
                "reference_doctype": "HD Ticket",
                "content": ["like", like_term],
            },
            field_name="reference_name",
            source_name="communication",
            limit=limit,
        )
        return ticket_sources

    def _collect_related_matches(
        self,
        ticket_sources: Dict[str, List[str]],
        doctype: str,
        filters: Dict,
        field_name: str,
        source_name: str,
        limit: int,
    ) -> None:
        if self._uses_manual_visibility():
            rows = frappe.get_all(
                doctype,
                filters=filters,
                fields=[field_name],
                order_by="creation desc",
                limit_page_length=min(limit, RELATED_SEARCH_LIMIT),
            )
        else:
            if not frappe.has_permission(doctype, "read"):
                return

            rows = frappe.get_list(
                doctype,
                filters=filters,
                fields=[field_name],
                order_by="creation desc",
                limit_page_length=min(limit, RELATED_SEARCH_LIMIT),
            )
        for row in rows:
            ticket_name = row.get(field_name)
            if not ticket_name:
                continue
            if self._uses_manual_visibility():
                if not self._get_visible_ticket(ticket_name, fields=["name"]):
                    continue
            elif not frappe.has_permission("HD Ticket", "read", ticket_name):
                continue
            if source_name not in ticket_sources[ticket_name]:
                ticket_sources[ticket_name].append(source_name)
