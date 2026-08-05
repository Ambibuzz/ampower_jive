"""Entry handler for the HD Tickets mode."""

from __future__ import annotations

import time

import frappe

from ampower_jive.hd_tickets.constants import MODE_KEY, NO_RESULTS_MESSAGE
from ampower_jive.hd_tickets.graph_builder import HDTicketsGraphBuilder
from ampower_jive.utils.interaction_logger import InteractionLogger

_handler_instance = None


class HDTicketsModeHandler:
    """Run the HD Tickets graph and return a grounded text response."""

    def __init__(self):
        self._graph = HDTicketsGraphBuilder().build()
        self._logger = InteractionLogger(MODE_KEY)

    def process(
        self,
        message: str,
        history: list | None = None,
        conversation_id: str | None = None,
        session_id: str | None = None,
        context_payload=None,
    ) -> str | dict:
        """Run the HD Tickets workflow for a single user message."""
        started_at = time.time()
        try:
            state = {
                "message": message,
                "history": history or [],
                "conversation_id": conversation_id or "",
                "session_id": session_id or "default",
                "context_payload": context_payload,
            }
            result = self._graph.invoke(state)
            response = (result.get("response") if isinstance(result, dict) else "") or NO_RESULTS_MESSAGE
            self._logger.log(
                request_data={
                    "message": message,
                    "history_length": len(history or []),
                    "has_context_payload": bool(context_payload),
                },
                response_data=response,
                model="hd_tickets_graph",
                processing_time_ms=int((time.time() - started_at) * 1000),
                session_id=session_id,
            )
            if isinstance(result, dict) and result.get("needs_approval") and result.get("plan"):
                return {
                    "response": response,
                    "needs_approval": True,
                    "plan": result.get("plan"),
                }
            return response
        except Exception as exc:
            traceback_str = frappe.get_traceback()
            frappe.log_error("HD Tickets Mode Error", traceback_str)
            self._logger.log(
                request_data={"message": message, "has_context_payload": bool(context_payload)},
                model="hd_tickets_graph",
                status="error",
                error=exc,
                error_traceback=traceback_str,
                processing_time_ms=int((time.time() - started_at) * 1000),
                session_id=session_id,
            )
            return f"I encountered an error while checking your tickets: {str(exc)}"


def get_hd_tickets_handler() -> HDTicketsModeHandler:
    """Return a singleton HD Tickets handler."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = HDTicketsModeHandler()
    return _handler_instance
