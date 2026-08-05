"""Ticket creation planning service for HD Tickets mode."""

from __future__ import annotations

import frappe

from ampower_jive.api_features.access import is_website_user
from ampower_jive.hd_tickets.services.customer_scope_service import CustomerScopeService
from ampower_jive.utils.app_dependencies import is_helpdesk_installed


class TicketCreateService:
    """Prepare approval-backed Helpdesk ticket creation actions."""

    MIN_MEANINGFUL_DESCRIPTION_WORDS = 5
    MIN_MEANINGFUL_DESCRIPTION_CHARS = 32

    def __init__(self, scope_service: CustomerScopeService):
        self._scope_service = scope_service

    def create_ticket(
        self,
        *,
        subject: str = "",
        description: str = "",
        priority: str = "",
        customer_hint: str = "",
    ) -> dict:
        if not is_helpdesk_installed():
            return self._failure("HD Tickets requires the Helpdesk app to be installed.")

        subject = (subject or "").strip()
        description = (description or "").strip()
        priority = (priority or "").strip()
        if not subject:
            return self._failure(
                "Please share the ticket subject before I prepare the plan.\n\n"
                "Subject: <short ticket title>"
            )
        if not self._has_usable_description(subject, description):
            return self._failure(
                f"I captured the subject as: {subject}\n\n"
                "Please add a fuller description before I prepare the plan.\n\n"
                "Description: <full issue description>"
            )
        valid_priorities = self._get_priority_catalog()
        if not priority:
            return self._failure(
                f"I captured the subject as: {subject}\n\n"
                "Please add the priority before I prepare the plan.\n\n"
                f"Priority: <one of {', '.join(valid_priorities) if valid_priorities else 'the available priorities'}>"
            )
        if valid_priorities and priority not in valid_priorities:
            return self._failure(
                f"The priority '{priority}' is not valid.\n\n"
                f"Please choose one of: {', '.join(valid_priorities)}"
            )

        scope = self._scope_service.resolve_customer_scope(
            customer_hint=customer_hint,
            require_selection=True,
            operation="create",
        )
        if scope.clarify_question:
            return self._failure(scope.clarify_question)

        payload = {
            "subject": subject,
            "description": description,
            "priority": priority,
            "raised_by": frappe.session.user,
            "via_customer_portal": bool(frappe.session.user and is_website_user()),
        }
        if scope.mode == "specific_customer" and scope.customer_name:
            payload["customer"] = scope.customer_name

        customer_label = scope.customer_label or payload.get("customer") or "the selected customer"
        plan = [
            {
                "action": "create",
                "doctype": "HD Ticket",
                "data": payload,
                "description": f"Create an HD Ticket for {customer_label} with subject '{subject}'",
            }
        ]
        response_lines = [
            "I prepared a ticket creation plan for your review.",
            f"Subject: {subject}",
            f"Priority: {priority}",
        ]
        if payload.get("customer"):
            response_lines.append(f"Customer: {payload['customer']}")
        response_lines.append("Description:")
        response_lines.append(description)
        response_lines.append("Approve the plan to create the ticket.")
        return {
            "success": True,
            "needs_approval": True,
            "response": "\n".join(response_lines),
            "plan": plan,
            "subject": subject,
            "description": description,
            "customer": payload.get("customer") or "",
        }

    def _get_priority_catalog(self) -> list[str]:
        return [
            str(priority).strip()
            for priority in frappe.get_all("HD Ticket Priority", filters={"disabled": 0}, pluck="name")
            if str(priority or "").strip()
        ]

    def get_priority_catalog(self) -> list[str]:
        """Return the visible HD ticket priorities."""
        return self._get_priority_catalog()

    def _failure(self, response: str) -> dict:
        return {
            "success": False,
            "response_ready": True,
            "requires_user_input": True,
            "response": response,
        }

    def _has_usable_description(self, subject: str, description: str) -> bool:
        if not description:
            return False

        normalized_subject = " ".join((subject or "").strip().lower().split())
        normalized_description = " ".join((description or "").strip().lower().split())
        if normalized_description != normalized_subject:
            return True

        word_count = len([word for word in normalized_description.split(" ") if word])
        if word_count >= self.MIN_MEANINGFUL_DESCRIPTION_WORDS:
            return True
        return len(normalized_description) >= self.MIN_MEANINGFUL_DESCRIPTION_CHARS
