"""Write-side services for HD Tickets mode."""

from __future__ import annotations

from typing import Any

import frappe

from ampower_jive.hd_tickets.services.ticket_repository import TicketRepository
from ampower_jive.utils.app_dependencies import is_helpdesk_agent


class TicketWriteService:
    """Prepare and execute ticket communication and comment actions."""

    TICKET_DOCTYPE = "HD Ticket"
    COMMENT_DOCTYPE = "HD Ticket Comment"
    COMMUNICATION_DOCTYPE = "Communication"
    COMMENT_ACTION = "add_comment"
    COMMUNICATION_ACTION = "add_communication"

    def __init__(self, repository: TicketRepository | None = None):
        self._repository = repository or TicketRepository()

    def prepare_comment_plan(self, *, ticket_id: str = "", content: str = "") -> dict[str, Any]:
        """Build an approval-backed plan for adding an internal ticket comment."""
        return self._prepare_activity_plan(
            action=self.COMMENT_ACTION,
            ticket_id=ticket_id,
            content=content,
            content_key="content",
            activity_label="comment",
            description_template="Add an internal comment to HD Ticket {ticket_id}",
            require_agent=True,
            permission_error="Only Helpdesk agents can add internal ticket comments.",
        )

    def prepare_communication_plan(
        self, *, ticket_id: str = "", message: str = ""
    ) -> dict[str, Any]:
        """Build an approval-backed plan for adding a ticket communication."""
        return self._prepare_activity_plan(
            action=self.COMMUNICATION_ACTION,
            ticket_id=ticket_id,
            content=message,
            content_key="message",
            activity_label="communication",
            description_template="Add a communication to HD Ticket {ticket_id}",
            require_agent=False,
            permission_error="",
        )

    def add_comment(self, *, ticket_id: str, content: str) -> dict[str, Any]:
        """Append an internal comment to a visible ticket."""
        ticket = self._get_ticket(
            ticket_id,
            require_agent=True,
            permission_error="Only Helpdesk agents can add internal ticket comments.",
        )
        if isinstance(ticket, dict):
            return ticket

        normalized_content = self._normalize_content(content)
        if not normalized_content:
            return self._failure("Please share the comment text you want to add.")

        ticket.new_comment(content=normalized_content, attachments=[])
        return {
            "success": True,
            "message": f"Internal comment added to HD Ticket '{ticket.name}'.",
            "name": ticket.name,
            "doctype": self.TICKET_DOCTYPE,
        }

    def add_communication(self, *, ticket_id: str, message: str) -> dict[str, Any]:
        """Append a communication entry to a visible ticket."""
        ticket = self._get_ticket(
            ticket_id,
            require_agent=False,
            permission_error="",
        )
        if isinstance(ticket, dict):
            return ticket

        normalized_message = self._normalize_content(message)
        if not normalized_message:
            return self._failure("Please share the communication text you want to add.")

        if is_helpdesk_agent():
            communication = self._build_communication_doc(
                ticket=ticket,
                message=normalized_message,
                sent_or_received="Sent",
                sender=frappe.session.user,
                recipients=ticket.raised_by or "",
            )
            communication.insert(ignore_permissions=True)
            communication_name = communication.name
        else:
            ticket.create_communication_via_contact(
                normalized_message,
                attachments=[],
                new_ticket=False,
            )
            latest_communication = ticket.get_last_communication()
            communication_name = latest_communication.name if latest_communication else ""

        return {
            "success": True,
            "message": f"Communication added to HD Ticket '{ticket.name}'.",
            "name": ticket.name,
            "doctype": self.TICKET_DOCTYPE,
            "communication": communication_name,
        }

    def ensure_initial_communication(self, ticket: Any) -> dict[str, Any]:
        """Guarantee that a newly created ticket has its starter communication."""
        ticket_doc = self._coerce_ticket(ticket)
        if isinstance(ticket_doc, dict):
            return ticket_doc

        if not self._normalize_content(ticket_doc.description):
            return {"success": True, "skipped": True}

        if frappe.db.exists(
            self.COMMUNICATION_DOCTYPE,
            {
                "reference_doctype": self.TICKET_DOCTYPE,
                "reference_name": ticket_doc.name,
            },
        ):
            return {"success": True, "skipped": True}

        ticket_doc.create_communication_via_contact(
            ticket_doc.description,
            attachments=[],
            new_ticket=True,
        )
        latest_communication = ticket_doc.get_last_communication()
        return {
            "success": True,
            "name": ticket_doc.name,
            "doctype": self.TICKET_DOCTYPE,
            "communication": latest_communication.name if latest_communication else "",
        }

    def _prepare_activity_plan(
        self,
        *,
        action: str,
        ticket_id: str,
        content: str,
        content_key: str,
        activity_label: str,
        description_template: str,
        require_agent: bool,
        permission_error: str,
    ) -> dict[str, Any]:
        if require_agent and not is_helpdesk_agent():
            return self._failure(permission_error)

        normalized_ticket_id = self._normalize_ticket_id(ticket_id)
        if not normalized_ticket_id:
            return self._failure(f"Please specify the ticket id before I prepare the {activity_label} plan.")

        normalized_content = self._normalize_content(content)
        if not normalized_content:
            return self._failure(f"Please share the {activity_label} text before I prepare the plan.")

        ticket = self._get_ticket(
            normalized_ticket_id,
            require_agent=require_agent,
            permission_error=permission_error,
        )
        if isinstance(ticket, dict):
            return ticket

        return {
            "success": True,
            "needs_approval": True,
            "response": (
                f"I prepared a plan to add a {activity_label} to ticket {ticket.name}.\n"
                "Approve the plan to continue."
            ),
            "plan": [
                {
                    "action": action,
                    "doctype": self.TICKET_DOCTYPE,
                    "name": ticket.name,
                    "data": {content_key: normalized_content},
                    "description": description_template.format(ticket_id=ticket.name),
                }
            ],
        }

    def _build_communication_doc(
        self,
        *,
        ticket,
        message: str,
        sent_or_received: str,
        sender: str,
        recipients: str = "",
    ):
        communication = frappe.get_doc(
            {
                "doctype": self.COMMUNICATION_DOCTYPE,
                "communication_type": "Communication",
                "communication_medium": "Email",
                "sent_or_received": sent_or_received,
                "email_status": "Open",
                "status": "Linked",
                "subject": self._build_communication_subject(ticket.subject),
                "sender": sender,
                "recipients": recipients,
                "user": frappe.session.user,
                "content": message,
                "reference_doctype": self.TICKET_DOCTYPE,
                "reference_name": ticket.name,
            }
        )

        last_communication = (
            ticket.get_last_communication()
            if hasattr(ticket, "get_last_communication")
            else None
        )
        if last_communication and getattr(last_communication, "message_id", None):
            communication.in_reply_to = last_communication.name
        return communication

    def _get_ticket(self, ticket_id: str, *, require_agent: bool, permission_error: str):
        ticket_doc = self._coerce_ticket(ticket_id)
        if isinstance(ticket_doc, dict):
            return ticket_doc

        if require_agent and not is_helpdesk_agent():
            return self._failure(permission_error)
        return ticket_doc

    def _coerce_ticket(self, ticket: Any):
        if hasattr(ticket, "doctype") and getattr(ticket, "doctype", "") == self.TICKET_DOCTYPE:
            ticket_doc = ticket
            ticket_name = ticket_doc.name
        else:
            ticket_name = self._normalize_ticket_id(ticket)
            if not ticket_name:
                return self._failure("Ticket id is required.")
            if not frappe.db.exists(self.TICKET_DOCTYPE, ticket_name):
                return self._failure(f"HD Ticket '{ticket_name}' does not exist.")
            if not self._repository.get_ticket_detail(ticket_name):
                return self._failure(f"You do not have access to HD Ticket '{ticket_name}'.")
            ticket_doc = frappe.get_doc(self.TICKET_DOCTYPE, ticket_name)
        return ticket_doc

    def _build_communication_subject(self, subject: str) -> str:
        normalized_subject = (subject or "").strip()
        return f"Re: {normalized_subject}" if normalized_subject else "Re: HD Ticket"

    def _normalize_ticket_id(self, ticket_id: Any) -> str:
        value = str(ticket_id or "").strip().upper()
        if value.isdigit():
            return value.zfill(4)
        return value

    def _normalize_content(self, content: Any) -> str:
        return str(content or "").strip()

    def _failure(self, response: str) -> dict[str, Any]:
        return {
            "success": False,
            "response_ready": True,
            "requires_user_input": True,
            "response": response,
        }
