"""Customer scope resolution for HD Tickets mode."""

from __future__ import annotations

from typing import List

import frappe

from ampower_jive.hd_tickets.dtos import CustomerOption, ScopeResolution
from ampower_jive.hd_tickets.services.ticket_repository import TicketRepository
from ampower_jive.utils.app_dependencies import get_helpdesk_customer_links, is_helpdesk_installed


class CustomerScopeService:
    """Resolve the customer scope without bypassing Helpdesk visibility rules."""

    def __init__(self, repository: TicketRepository):
        self._repository = repository

    def resolve_customer_scope(
        self,
        customer_hint: str = "",
        *,
        require_selection: bool = False,
        operation: str = "read",
    ) -> ScopeResolution:
        """Resolve a customer hint into a visible HD customer scope."""
        visible_customers = self.get_visible_customers()
        visible_labels = [customer.display_label for customer in visible_customers]

        if customer_hint:
            matches = self._match_customer_hint(customer_hint, visible_customers)
            if not matches and not visible_customers:
                matches = self._find_accessible_customers_by_hint(customer_hint)

            if len(matches) == 1:
                customer = matches[0]
                return ScopeResolution(
                    mode="specific_customer",
                    customer_name=customer.name,
                    customer_label=customer.display_label,
                    visible_customers=visible_labels,
                )

            if len(matches) > 1:
                options = ", ".join(customer.display_label for customer in matches[:5])
                return ScopeResolution(
                    mode="needs_clarification",
                    visible_customers=visible_labels,
                    clarify_question=f"I found multiple matching customers: {options}. Which one should I use?",
                )

            return ScopeResolution(
                mode="needs_clarification",
                visible_customers=visible_labels,
                clarify_question=f"I couldn't find a visible customer matching '{customer_hint}'.",
            )

        if require_selection and len(visible_customers) > 1:
            options = ", ".join(customer.display_label for customer in visible_customers[:5])
            question = f"You can access multiple customers: {options}. Which customer should I use?"
            if operation == "create":
                question = f"You can raise tickets for multiple customers: {options}. Which customer should I use?"
            return ScopeResolution(
                mode="needs_clarification",
                visible_customers=visible_labels,
                clarify_question=question,
            )

        if len(visible_customers) == 1:
            customer = visible_customers[0]
            return ScopeResolution(
                mode="specific_customer",
                customer_name=customer.name,
                customer_label=customer.display_label,
                visible_customers=visible_labels,
            )

        return ScopeResolution(mode="all_visible_tickets", visible_customers=visible_labels)

    def get_visible_customers(self) -> List[CustomerOption]:
        """Return HD customers explicitly or implicitly linked to the current user."""
        if not is_helpdesk_installed():
            return []

        user = frappe.session.user
        user_permissions = frappe.defaults.get_user_permissions(user) or {}
        customer_names = {
            permission.get("doc")
            for permission in (user_permissions.get("HD Customer") or [])
            if permission.get("doc")
        }

        for customer_name in get_helpdesk_customer_links(user):
            if customer_name:
                customer_names.add(customer_name)

        return self._load_customer_options(sorted(customer_names))

    def _load_customer_options(self, names: List[str]) -> List[CustomerOption]:
        if not names:
            return []
        rows = frappe.db.get_all(
            "HD Customer",
            filters={"name": ["in", names]},
            fields=["name", "customer_name", "erpnext_customer"],
        )
        options = [
            CustomerOption(
                name=row.get("name") or "",
                customer_name=row.get("customer_name") or "",
                erpnext_customer=row.get("erpnext_customer") or "",
            )
            for row in rows
            if row.get("name")
        ]
        return sorted(options, key=lambda option: option.display_label.lower())

    def _match_customer_hint(self, hint: str, options: List[CustomerOption]) -> List[CustomerOption]:
        if not hint:
            return []
        normalized_hint = self._normalize(hint)
        exact_matches = [
            option
            for option in options
            if normalized_hint in {
                self._normalize(option.name),
                self._normalize(option.customer_name),
                self._normalize(option.erpnext_customer),
            }
        ]
        if exact_matches:
            return exact_matches

        return [
            option
            for option in options
            if normalized_hint
            and (
                normalized_hint in self._normalize(option.name)
                or normalized_hint in self._normalize(option.customer_name)
                or normalized_hint in self._normalize(option.erpnext_customer)
            )
        ]

    def _find_accessible_customers_by_hint(self, hint: str) -> List[CustomerOption]:
        like_term = f"%{hint.strip()}%"
        rows = frappe.db.get_all(
            "HD Customer",
            or_filters=[
                ["HD Customer", "name", "like", like_term],
                ["HD Customer", "customer_name", "like", like_term],
                ["HD Customer", "erpnext_customer", "like", like_term],
            ],
            fields=["name", "customer_name", "erpnext_customer"],
            limit=10,
        )

        visible_matches = []
        for row in rows:
            customer_name = row.get("name") or ""
            if not customer_name or not self._repository.has_visible_ticket_for_customer(customer_name):
                continue
            visible_matches.append(
                CustomerOption(
                    name=customer_name,
                    customer_name=row.get("customer_name") or "",
                    erpnext_customer=row.get("erpnext_customer") or "",
                )
            )
        return visible_matches

    def _normalize(self, value: str) -> str:
        return " ".join((value or "").strip().lower().split())
