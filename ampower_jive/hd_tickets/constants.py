"""Constants used by the HD Tickets mode."""

from __future__ import annotations

MODE_KEY = "hd_tickets"

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 25
RELATED_SEARCH_LIMIT = 40
MAX_ACTIVITY_ITEMS = 12
PAGINATION_STATE_TTL_SECONDS = 900

TICKET_LIST_FIELDS = [
    "name",
    "subject",
    "status",
    "priority",
    "customer",
    "agent_group",
    "modified",
    "creation",
]

NO_RESULTS_MESSAGE = "I couldn't find any visible tickets matching that request."
