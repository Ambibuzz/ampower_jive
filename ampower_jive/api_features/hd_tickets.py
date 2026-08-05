"""HD Tickets mode endpoints for Jive."""

from __future__ import annotations

from ampower_jive.utils.app_dependencies import is_helpdesk_installed


def process_hd_tickets_query(
    message: str,
    history: list,
    conversation_id: str = None,
    session_id: str = None,
    context_payload=None,
) -> str | dict:
    """Process an HD Tickets query using live Helpdesk data."""
    if not is_helpdesk_installed():
        return "HD Tickets mode requires the Helpdesk app to be installed."

    from ampower_jive.hd_tickets.handler import get_hd_tickets_handler

    return get_hd_tickets_handler().process(
        message=message,
        history=history,
        conversation_id=conversation_id,
        session_id=session_id,
        context_payload=context_payload,
    )
