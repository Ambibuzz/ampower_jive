"""Chat, data query, and agent orchestration endpoints."""

from __future__ import annotations

import json
from typing import Optional

import frappe

from ampower_jive.api_features.access import get_mode_config, normalize_chat_mode
from ampower_jive.api_features.common import (
    _append_helpdesk_recommendations,
    _ensure_local_monthly_quota,
    _log_context_debug,
    _log_mode_error,
    _log_mode_turn,
    _summarize_context_payload,
    _strip_followup_blocks_from_history,
)
from ampower_jive.utils.context_aware import build_context_aware_prompt


@frappe.whitelist()
def chat(
    message: str,
    conversation_id: str = None,
    mode: str = "query",
    session_id: str = None,
    context_payload: str = None,
    context_aware: int = 0,
    stream: int = 0,
    portal_access: int = 0,
):
    """Main chat endpoint that routes requests through the chat orchestrator."""
    from ampower_jive.utils.chat_service import ChatOrchestrator

    return ChatOrchestrator().process(
        message=message,
        conversation_id=conversation_id,
        mode=mode,
        session_id=session_id,
        context_payload=context_payload,
        context_aware=context_aware,
        stream=stream,
        portal_access=portal_access,
    )


def process_rag_query(
    message: str,
    history: list,
    session_id: str = None,
    conversation_id: str = None,
    context_aware: bool = False,
    context_payload=None,
    stream: int = 0,
    stream_callback=None,
):
    """Process a RAG query through the tenant-side RAG service."""
    try:
        quota_response = _ensure_local_monthly_quota()
        if quota_response:
            return quota_response

        from ampower_jive.agent.rag_resolution import VECTOR_DATABASE_MODE, RagResolver
        from ampower_jive.agent.rag_service import RagService
        from ampower_jive.agent.vector_database_service import MultiVectorDatabaseRagService, VectorDatabaseRagService

        if context_aware or context_payload:
            _log_context_debug(
                "tenant.rag.received",
                {
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "context_aware": context_aware,
                    "payload": _summarize_context_payload(context_payload),
                },
            )

        target = RagResolver().resolve(user=frappe.session.user, context_payload=context_payload)
        if target.pipeline_mode == VECTOR_DATABASE_MODE:
            if not target.vector_databases:
                return {"success": False, "message": "No vector database is mapped for this user."}
            if target.has_multiple_vector_databases:
                service = MultiVectorDatabaseRagService(target.vector_databases, site_name=frappe.local.site)
            else:
                service = VectorDatabaseRagService(target.vector_database, site_name=frappe.local.site)
        else:
            service = RagService(frappe.local.site)

        return service.query(
            question=message,
            history=_strip_followup_blocks_from_history(history),
            session_id=session_id,
            conversation_id=conversation_id,
            user=frappe.session.user,
            context_aware=context_aware,
            context_payload=context_payload,
            stream=bool(stream),
            stream_callback=stream_callback,
        )
    except Exception as e:
        frappe.log_error(message=f"Failed to process local RAG query: {e}", title="Jive RAG Query Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def enqueue_rag_index_build(site_name: Optional[str] = None, vector_database_name: Optional[str] = None) -> dict:
    """Queue a local RAG rebuild for the current tenant."""
    try:
        from ampower_jive.agent.rag_resolution import VECTOR_DATABASE_MODE, RagResolver
        from ampower_jive.agent.rag_service import enqueue_rag_index_build as _enqueue_rag_index_build
        from ampower_jive.agent.vector_database_service import (
            enqueue_all_vector_database_index_builds,
            enqueue_vector_database_index_build as _enqueue_vector_database_index_build,
        )

        if vector_database_name:
            return _enqueue_vector_database_index_build(vector_database_name=vector_database_name, site_name=site_name or frappe.local.site)

        pipeline_mode = RagResolver().get_pipeline_mode()
        if pipeline_mode == VECTOR_DATABASE_MODE:
            config = frappe.get_single("Jive Config")
            default_vdb = getattr(config, "rag_default_vector_database", "") if config else ""
            if default_vdb:
                return _enqueue_vector_database_index_build(vector_database_name=default_vdb, site_name=site_name or frappe.local.site)
            return enqueue_all_vector_database_index_builds(site_name=site_name or frappe.local.site)

        return _enqueue_rag_index_build(site_name=site_name or frappe.local.site)
    except Exception as e:
        frappe.log_error(message=f"Failed to queue local RAG build: {e}", title="Jive RAG Queue Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def enqueue_vector_database_index_build(vector_database_name: str, site_name: Optional[str] = None) -> dict:
    """Queue processing for a single user-specific vector database."""
    try:
        from ampower_jive.agent.vector_database_service import enqueue_vector_database_index_build as _enqueue_vector_database_index_build

        return _enqueue_vector_database_index_build(vector_database_name=vector_database_name, site_name=site_name or frappe.local.site)
    except Exception as e:
        frappe.log_error(message=f"Failed to queue vector database build: {e}", title="Jive Vector DB Queue Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def process_data_query(
    message: str,
    history: list,
    allowed_doctypes: list,
    session_id: str = None,
    system_prompt: str = None,
) -> str | dict:
    """Process a data query using the full LangGraph agent."""
    try:
        quota_response = _ensure_local_monthly_quota()
        if quota_response:
            return quota_response

        from ampower_jive.agent import get_agent

        agent = get_agent()
        return agent.chat(
            message=message,
            history=history,
            allowed_doctypes=allowed_doctypes,
            session_id=session_id,
            system_prompt=system_prompt,
        )

    except Exception as e:
        traceback_str = frappe.get_traceback()
        frappe.log_error("Data Query Error", traceback_str)
        try:
            from ampower_jive.utils.interaction_logger import InteractionLogger

            InteractionLogger("data_query").log(
                status="error",
                error=e,
                error_traceback=traceback_str,
                request_data={"message": message},
                session_id=session_id,
            )
        except Exception:
            pass
        return f"I encountered an error while querying your data: {str(e)}"


def handle_agent_mode(message: str, conversation_id: str, chat_log, history: list, allowed_doctypes: list, session_id: str = None, context_payload=None, context_aware: bool = False, request_payload=None):
    """Handle agent mode for R/W operations."""
    try:
        quota_response = _ensure_local_monthly_quota()
        if quota_response:
            return quota_response

        from ampower_jive.agent import AgentModeGraph
        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        require_approval = provider.get_agent_require_approval()

        if context_aware and context_payload:
            try:
                context_prompt = build_context_aware_prompt(context_payload, message, history=history)
            except Exception:
                context_prompt = ""

            if context_prompt:
                history = (history or []) + [{"role": "system", "content": context_prompt}]

        agent = AgentModeGraph()
        result = agent.process(message, history, allowed_doctypes, session_id=session_id)

        if result.get("needs_approval") and require_approval:
            plan_key = f"agent_plan_{frappe.session.user}_{conversation_id}"
            frappe.cache().set_value(plan_key, result.get("plan"), expires_in_sec=300)
            return _log_mode_turn(
                chat_log,
                message,
                "agent",
                result.get("thinking", "Planning operation..."),
                extra={
                    "conversation_id": conversation_id,
                    "needs_approval": True,
                    "plan": result.get("plan"),
                },
                request_payload=request_payload,
            )

        if result.get("needs_approval") and not require_approval:
            from ampower_jive.agent.agent_tools import execute_planned_action

            execution_results = []
            for action in result.get("plan", []):
                execution_results.append(execute_planned_action(action))

            response_text = f"Operations completed: {json.dumps(execution_results, indent=2)}"
        else:
            response_text = result.get("response", "")

        return _log_mode_turn(
            chat_log,
            message,
            "agent",
            response_text,
            extra={"conversation_id": conversation_id},
            request_payload=request_payload,
        )

    except Exception as e:
        return _log_mode_error(chat_log, message, "agent", e, "Agent Mode Error", request_payload=request_payload)


def handle_core_managed_agent_mode(
    agent_key: str,
    message: str,
    conversation_id: str,
    chat_log,
    history: list,
    allowed_doctypes: list,
    session_id: str = None,
    context_payload=None,
    context_aware: bool = False,
    request_payload=None,
):
    """Handle a core-managed agent using its synced tenant configuration."""
    try:
        from ampower_jive.api_features.helpdesk import process_helpdesk_query
        from ampower_jive.api_features.insights import handle_insights_mode
        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        agent_cfg = get_mode_config(provider, agent_key)

        if not agent_cfg or not agent_cfg.get("is_available", False):
            error_message = f"Agent '{agent_key}' is not available for this tenant."
            return _log_mode_error(chat_log, message, agent_key, error_message, f"Core Agent Mode Error ({agent_key})", request_payload=request_payload)

        handler_type = (agent_cfg.get("handler_type") or "query").lower().strip()
        system_prompt = (agent_cfg.get("system_prompt") or "").strip()
        response_text = ""

        if handler_type == "query":
            if not system_prompt:
                error_message = f"Agent '{agent_key}' is missing a system prompt in Jive Core."
                return _log_mode_error(chat_log, message, agent_key, error_message, f"Core Agent Mode Error ({agent_key})", request_payload=request_payload)

            query_history = _strip_followup_blocks_from_history(history)
            response_text = process_data_query(
                message=message,
                history=query_history,
                allowed_doctypes=allowed_doctypes,
                session_id=session_id,
                system_prompt=system_prompt,
            )
            if isinstance(response_text, dict):
                return response_text

        elif handler_type == "helpdesk":
            visible_response = process_helpdesk_query(
                message,
                history,
                session_id,
                temperature=agent_cfg.get("temperature") or 0.3,
                max_tokens=agent_cfg.get("max_tokens") or 4096,
                custom_prompt=system_prompt or None,
            )
            if isinstance(visible_response, dict):
                return visible_response
            response_text = _append_helpdesk_recommendations(message, visible_response, history)

        elif handler_type == "agent":
            response_text = handle_agent_mode(
                message,
                conversation_id,
                chat_log,
                history,
                allowed_doctypes,
                session_id=session_id,
                request_payload=request_payload,
            )
            return response_text

        elif handler_type == "insights":
            response_text = handle_insights_mode(
                message,
                conversation_id,
                chat_log,
                history,
                session_id=session_id,
                request_payload=request_payload,
            )
            return response_text

        else:
            error_message = f"Unsupported core agent handler '{handler_type}'."
            return _log_mode_error(chat_log, message, agent_key, error_message, f"Core Agent Mode Error ({agent_key})", request_payload=request_payload)

        return _log_mode_turn(
            chat_log,
            message,
            agent_key,
            response_text,
            extra={"conversation_id": conversation_id},
            request_payload=request_payload,
        )

    except Exception as e:
        return _log_mode_error(chat_log, message, agent_key, e, f"Core Agent Mode Error ({agent_key})", request_payload=request_payload)
