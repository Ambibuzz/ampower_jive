"""
Interaction Logger — Fire-and-forget LLM interaction logging to Jive Core.

Captures detailed request/response data for every LLM call and sends it
to the Jive Core instance asynchronously via frappe.enqueue.

Only active when `use_jive_core` is enabled in Jive Config.
When disabled, all calls are no-ops with zero overhead.
"""

import json
import time
import frappe
from typing import Dict, Any, Optional


class InteractionLogger:
    """
    Logs detailed LLM interactions to Jive Core.

    Usage:
        logger = InteractionLogger("helpdesk")
        logger.log(
            request_data={"messages": [...], "model": "gpt-4o-mini"},
            response_data={"content": "..."},
            model="gpt-4o-mini",
            processing_time_ms=1200,
        )

    Design:
        - Single Responsibility: only handles interaction logging
        - Open/Closed: extend by subclassing, not modifying
        - Fire-and-forget: uses frappe.enqueue, never blocks the response
        - Graceful degradation: all errors are caught and logged, never raised
    """

    def __init__(self, agent_type: str):
        """
        Initialize the logger for a specific agent type.

        Args:
            agent_type: The type of agent (data_query, helpdesk, agent_mode, insights)
        """
        self.agent_type = agent_type

    def log(
        self,
        request_data: Dict[str, Any] = None,
        response_data: Any = None,
        model: str = None,
        status: str = "success",
        error: Exception = None,
        error_traceback: str = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        processing_time_ms: int = 0,
        user: str = None,
        session_id: str = None,
    ):
        """
        Log an LLM interaction asynchronously.

        This method is fire-and-forget — it enqueues the log operation
        in the background and returns immediately. It never raises exceptions.

        Args:
            request_data: Dict containing messages, model, temperature etc.
            response_data: The LLM response (string or dict with 'content' key)
            model: LLM model name
            status: 'success', 'error', or 'timeout'
            error: Exception object if the call failed
            error_traceback: Full traceback string if the call failed
            tokens_in: Prompt token count
            tokens_out: Completion token count
            processing_time_ms: Duration of the LLM call in milliseconds
            user: User who triggered the request
            session_id: Chat session identifier
        """
        try:
            from ampower_jive.utils.config_provider import get_config_provider
            provider = get_config_provider()

            if not provider.is_core_mode():
                return

            # Serialize request data
            request_payload = None
            if request_data:
                try:
                    request_payload = json.dumps(
                        request_data, default=str, ensure_ascii=False
                    )
                    # Truncate very large payloads to avoid overwhelming the DB
                    if len(request_payload) > 100_000:
                        request_payload = request_payload[:100_000] + "\n... [truncated]"
                except (TypeError, ValueError):
                    request_payload = str(request_data)

            # Serialize response data
            response_payload = None
            if response_data is not None:
                if isinstance(response_data, dict):
                    response_payload = response_data.get("content", str(response_data))
                elif isinstance(response_data, str):
                    response_payload = response_data
                else:
                    response_payload = str(response_data)

                if len(response_payload) > 100_000:
                    response_payload = response_payload[:100_000] + "\n... [truncated]"

            # Build error info
            error_message = None
            if error:
                error_message = str(error)
                if not error_traceback:
                    error_traceback = frappe.get_traceback()

            # Build the log payload
            log_payload = {
                "agent_type": self.agent_type,
                "model": model,
                "status": status,
                "request_payload": request_payload,
                "response_payload": response_payload,
                "error_message": error_message,
                "error_traceback": error_traceback,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "processing_time_ms": processing_time_ms,
                "user": user or frappe.session.user,
                "session_id": session_id,
            }

            # Enqueue for async processing — never blocks the chat response
            frappe.enqueue(
                _send_interaction_log,
                queue="short",
                timeout=30,
                is_async=True,
                **log_payload,
            )

        except Exception as e:
            # Never let logging break the chat
            try:
                frappe.log_error(
                    message=f"InteractionLogger.log failed: {e}",
                    title="Interaction Logger Error",
                )
            except Exception:
                pass


def _send_interaction_log(
    agent_type: str,
    model: str = None,
    status: str = "success",
    request_payload: str = None,
    response_payload: str = None,
    error_message: str = None,
    error_traceback: str = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    processing_time_ms: int = 0,
    user: str = None,
    session_id: str = None,
):
    """
    Background job: send interaction log to Jive Core.

    This runs in a frappe.enqueue worker, separate from the request thread.
    """
    try:
        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        client = provider._get_core_client()

        if not client:
            return

        client.log_interaction(
            agent_type=agent_type,
            model=model,
            status=status,
            request_payload=request_payload,
            response_payload=response_payload,
            error_message=error_message,
            error_traceback=error_traceback,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            processing_time_ms=processing_time_ms,
            user=user,
            session_id=session_id,
        )

    except Exception as e:
        frappe.log_error(
            message=f"Failed to send interaction log to core: {e}",
            title="Interaction Log Send Error",
        )
