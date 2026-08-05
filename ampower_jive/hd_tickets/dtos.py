"""Data transfer objects for the HD Tickets mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, TypedDict


@dataclass(slots=True)
class TicketRequestContext:
    """Compact ticket context extracted from the current UI payload."""

    ticket_id: str = ""
    customer_name: str = ""
    customer_label: str = ""
    status: str = ""
    subject: str = ""
    priority: str = ""
    agent_group: str = ""
    description: str = ""
    source_type: str = ""

    @property
    def has_ticket(self) -> bool:
        return bool(self.ticket_id)

    def to_prompt_payload(self) -> Dict[str, str]:
        """Return a compact, prompt-safe view of the current ticket context."""
        payload = {
            "ticket_id": self.ticket_id,
            "customer": self.customer_name,
            "customer_label": self.customer_label,
            "status": self.status,
            "subject": self.subject,
            "priority": self.priority,
            "agent_group": self.agent_group,
            "source_type": self.source_type,
        }
        if self.description:
            payload["description"] = self.description
        return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


@dataclass(slots=True)
class CustomerOption:
    """Visible customer metadata for scope selection."""

    name: str
    customer_name: str = ""
    erpnext_customer: str = ""

    @property
    def display_label(self) -> str:
        return self.customer_name or self.erpnext_customer or self.name


@dataclass(slots=True)
class ScopeResolution:
    """Resolved customer scope used by HD ticket tools."""

    mode: str = "all_visible_tickets"
    customer_name: str = ""
    customer_label: str = ""
    visible_customers: List[str] = field(default_factory=list)
    clarify_question: str = ""


class HDTicketsGraphState(TypedDict, total=False):
    """LangGraph state for the HD Tickets tool-driven workflow."""

    message: str
    history: List[Dict[str, str]]
    conversation_id: str
    session_id: str
    context_payload: Any
    request_context: TicketRequestContext
    messages: List[Any]
    iteration_count: int
    plan: List[Dict[str, Any]]
    needs_approval: bool
    done: bool
    response: str
