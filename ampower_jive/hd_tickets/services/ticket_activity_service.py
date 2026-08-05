"""Ticket activity reads for HD Tickets mode."""

from __future__ import annotations

from typing import Dict

from ampower_jive.hd_tickets.services.ticket_repository import TicketRepository


class TicketActivityService:
    """Fetch visible ticket activities through the shared repository."""

    def __init__(self, repository: TicketRepository):
        self._repository = repository

    def get_ticket_activities(self, ticket_id: str) -> Dict:
        """Return ticket activity data for a visible ticket."""
        return self._repository.get_ticket_activities(ticket_id)
