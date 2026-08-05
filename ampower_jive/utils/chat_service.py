"""Chat orchestration for the Jive API."""

from __future__ import annotations

import frappe

from ampower_jive.api_features.access import has_jive_access, is_mode_available, normalize_chat_mode
from ampower_jive.api_features.chat import (
    handle_agent_mode,
    handle_core_managed_agent_mode,
    process_data_query,
    process_rag_query,
)
from ampower_jive.api_features.hd_tickets import process_hd_tickets_query
from ampower_jive.api_features.common import (
    _append_helpdesk_recommendations,
    _ensure_local_monthly_quota,
    _log_context_debug,
    _log_mode_turn,
    _summarize_context_payload,
    _strip_followup_blocks_from_history,
)
from ampower_jive.api_features.helpdesk import process_helpdesk_query
from ampower_jive.api_features.insights import handle_insights_mode
from ampower_jive.utils.chat_support import (
    _assistant_log_payload,
    _is_error_response,
    add_message_to_log,
    create_new_conversation,
    get_messages_from_log,
    safe_commit,
)
from ampower_jive.utils.context_aware import process_context_aware_query
from ampower_jive.utils.prompt_provider import get_prompt_provider


class ChatOrchestrator:
    """Route chat requests to the correct mode handler with shared validation."""

    MAX_HISTORY_CAP = 6

    def process(
        self,
        message: str,
        conversation_id: str = None,
        mode: str = "query",
        session_id: str = None,
        context_payload=None,
        context_aware: int = 0,
        stream: int = 0,
        portal_access: int = 0,
    ):
        if not self._is_valid_message(message):
            return {"error": True, "message": "Message cannot be empty"}

        if not has_jive_access(portal_access=portal_access):
            return self._permission_denied_response()

        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        if not provider.is_active():
            return {"error": True, "message": "Jive is not active. Please enable it in Jive Config."}

        config = provider.get_local_config()
        mode = normalize_chat_mode(mode)
        if not is_mode_available(provider, mode, portal_access=portal_access):
            return {"error": True, "message": f"Mode '{mode}' is not available for this tenant."}

        if mode != "helpdesk":
            quota_response = _ensure_local_monthly_quota()
            if quota_response:
                return quota_response

        chat_log, conversation_id, is_new_conversation = self._get_chat_log(conversation_id, mode, session_id)
        if is_new_conversation:
            self._set_new_conversation_title(chat_log, message)

        max_history = min(config.get("max_history_messages") or 10, self.MAX_HISTORY_CAP)
        history = get_messages_from_log(chat_log, max_history)
        allowed_doctypes = self._get_allowed_doctypes(config)
        request_payload = {
            "message": message,
            "conversation_id": conversation_id,
            "mode": mode,
            "session_id": session_id,
            "context_payload": context_payload,
            "context_aware": context_aware,
            "stream": stream,
        }

        use_context_aware = self._is_truthy(context_aware)
        self._log_context_if_needed(mode, use_context_aware, chat_log.session_id, conversation_id, context_payload, _summarize_context_payload)

        try:
            return self._dispatch_mode(
                mode=mode,
                message=message,
                conversation_id=conversation_id,
                chat_log=chat_log,
                history=history,
                allowed_doctypes=allowed_doctypes,
                session_id=chat_log.session_id,
                context_payload=context_payload,
                context_aware=use_context_aware,
                stream=stream,
                config=config,
                request_payload=request_payload,
            )
        except Exception as exc:
            return self._handle_failure(chat_log, message, mode, exc, request_payload=request_payload)

    def _is_valid_message(self, message: str) -> bool:
        return bool(message and message.strip())

    def _permission_denied_response(self) -> dict:
        return {
            "error": True,
            "message": "You don't have permission to use Jive. Please contact your administrator to grant you the 'Jive User' role.",
            "permission_denied": True,
        }

    def _get_chat_log(self, conversation_id: str, mode: str, session_id: str):
        is_new_conversation = False
        if conversation_id:
            try:
                chat_log = frappe.get_doc("Jive Chat Logs", conversation_id)
                if chat_log.user != frappe.session.user:
                    return None, conversation_id, False
            except frappe.DoesNotExistError:
                chat_log = create_new_conversation(mode, session_id)
                conversation_id = chat_log.name
                is_new_conversation = True
        else:
            chat_log = create_new_conversation(mode, session_id)
            conversation_id = chat_log.name
            is_new_conversation = True
        return chat_log, conversation_id, is_new_conversation

    def _set_new_conversation_title(self, chat_log, message: str) -> None:
        chat_log.title = (message or "").strip()[:100]
        chat_log.save(ignore_permissions=True)

        safe_commit()

    def _get_allowed_doctypes(self, config) -> list:
        allowed_doctypes = []
        if config and config.included_doctypes:
            for row in config.included_doctypes:
                dt = row.doctype_name
                if dt and frappe.has_permission(dt, "read"):
                    allowed_doctypes.append(dt)
        return allowed_doctypes

    def _is_truthy(self, value) -> bool:
        try:
            return str(value).lower() in ("1", "true", "yes", "on")
        except Exception:
            return bool(value)

    def _log_context_if_needed(self, mode, use_context_aware, session_id, conversation_id, context_payload, summarize_fn) -> None:
        if mode == "rag" or use_context_aware:
            _log_context_debug(
                "tenant.chat.received",
                {
                    "mode": mode,
                    "context_aware": use_context_aware,
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "payload": summarize_fn(context_payload),
                },
            )

    def _handle_helpdesk_mode(self, message, history, session_id, context_payload, config):
        prompt_provider = get_prompt_provider()
        helpdesk_prompt = prompt_provider.get_prompt("helpdesk")
        visible_response = process_helpdesk_query(
            message,
            history,
            session_id,
            config.get("helpdesk_temperature") or 0.3,
            config.get("helpdesk_max_tokens") or 4096,
            helpdesk_prompt,
        )
        if isinstance(visible_response, dict):
            return visible_response, None

        response_text = _append_helpdesk_recommendations(message, visible_response, history)
        gif_url = None
        if config.get("enable_gif_generation", 1):
            try:
                from ampower_jive.utils import generate_helpdesk_gif

                if generate_helpdesk_gif:
                    gif_url = generate_helpdesk_gif(
                        response_text=visible_response,
                        title="Quick Guide",
                        theme_name="dark",
                    )
            except Exception as exc:
                frappe.log_error(f"GIF generation failed: {exc}", "Helpdesk GIF Error")
        return response_text, gif_url

    def _handle_rag_mode(self, message, history, chat_log, conversation_id, context_payload, context_aware, stream, request_payload=None):
        rag_response = process_rag_query(
            message,
            history,
            session_id=chat_log.session_id,
            conversation_id=conversation_id,
            context_aware=context_aware,
            context_payload=context_payload,
            stream=stream,
        )
        if not rag_response.get("success", False):
            error_message = rag_response.get("message", "RAG query failed.")
            payload = request_payload or {"message": message, "mode": "rag", "conversation_id": conversation_id}
            add_message_to_log(chat_log, "user", message, "rag", request_payload=payload)
            assistant_kwargs = _assistant_log_payload(status="error", error_message=error_message)
            assistant_kwargs["request_payload"] = payload
            add_message_to_log(
                chat_log,
                "assistant",
                error_message,
                "rag",
                **assistant_kwargs,
            )
            return None, {"error": True, "message": error_message}, None

        response_text = rag_response.get("response", "")
        token_usage = rag_response.get("token_usage") or getattr(frappe.local, "jive_token_usage", None)
        return response_text, None, token_usage

    def _handle_builtin_query_mode(self, message, history, allowed_doctypes, context_payload, session_id, context_aware):
        query_history = _strip_followup_blocks_from_history(history)
        if context_aware:
            return process_context_aware_query(message, query_history, allowed_doctypes, context_payload, session_id)
        return process_data_query(message, query_history, allowed_doctypes, session_id)

    def _build_standard_mode_response(self, chat_log, message: str, conversation_id: str, mode: str, response_text: str, gif_url=None, token_usage=None, request_payload=None):
        assistant_status = "error" if _is_error_response(response_text) else "success"
        assistant_error = response_text if assistant_status == "error" else None
        payload = request_payload or {"message": message, "mode": mode, "conversation_id": conversation_id}
        add_message_to_log(chat_log, "user", message, mode, request_payload=payload)
        assistant_kwargs = _assistant_log_payload(status=assistant_status, error_message=assistant_error)
        assistant_kwargs["request_payload"] = payload
        add_message_to_log(
            chat_log,
            "assistant",
            response_text,
            mode,
            **assistant_kwargs,
        )
        return {
            "error": False,
            "response": response_text,
            "conversation_id": conversation_id,
            "mode": mode,
            "gif_url": gif_url,
            "title": chat_log.title,
            "token_usage": token_usage or getattr(frappe.local, "jive_token_usage", None),
        }

    def _dispatch_mode(
        self,
        mode: str,
        message: str,
        conversation_id: str,
        chat_log,
        history: list,
        allowed_doctypes: list,
        session_id: str,
        context_payload,
        context_aware: bool,
        stream: int,
        config,
        request_payload=None,
    ):
        gif_url = None
        response_text = ""
        token_usage = None

        if mode == "helpdesk":
            response_text, gif_url = self._handle_helpdesk_mode(message, history, session_id, context_payload, config)
            if isinstance(response_text, dict):
                return response_text

        elif mode == "rag":
            response_text, rag_error, token_usage = self._handle_rag_mode(
                message,
                history,
                chat_log,
                conversation_id,
                context_payload,
                context_aware,
                stream,
                request_payload=request_payload,
            )
            if rag_error:
                return rag_error

        elif mode == "agent":
            return handle_agent_mode(
                message,
                conversation_id,
                chat_log,
                history,
                allowed_doctypes,
                chat_log.session_id,
                context_payload=context_payload,
                context_aware=context_aware,
                request_payload=request_payload,
            )

        elif mode == "insights":
            return handle_insights_mode(
                message,
                conversation_id,
                chat_log,
                history,
                chat_log.session_id,
                context_payload=context_payload,
                context_aware=context_aware,
                request_payload=request_payload,
            )

        elif mode == "hd_tickets":
            response_text = process_hd_tickets_query(
                message=message,
                history=history,
                conversation_id=conversation_id,
                session_id=chat_log.session_id,
                context_payload=context_payload,
            )
            if isinstance(response_text, dict):
                if response_text.get("needs_approval") and response_text.get("plan"):
                    plan_key = f"agent_plan_{frappe.session.user}_{conversation_id}"
                    frappe.cache().set_value(plan_key, response_text.get("plan"), expires_in_sec=300)
                    return _log_mode_turn(
                        chat_log,
                        message,
                        "hd_tickets",
                        response_text.get("response") or "I prepared a ticket creation plan for your review.",
                        extra={
                            "conversation_id": conversation_id,
                            "needs_approval": True,
                            "plan": response_text.get("plan"),
                        },
                        request_payload=request_payload,
                    )
                return response_text

        elif mode in {"query", "helpdesk", "agent", "insights", "rag"}:
            response_text = self._handle_builtin_query_mode(
                message,
                history,
                allowed_doctypes,
                context_payload,
                chat_log.session_id,
                context_aware and mode == "query",
            )
        else:
            return handle_core_managed_agent_mode(
                mode,
                message,
                conversation_id,
                chat_log,
                history,
                allowed_doctypes,
                session_id=chat_log.session_id,
                context_payload=context_payload,
                context_aware=context_aware,
                request_payload=request_payload,
            )

        return self._build_standard_mode_response(
            chat_log,
            message,
            conversation_id,
            mode,
            response_text,
            gif_url=gif_url,
            token_usage=token_usage,
            request_payload=request_payload,
        )

    def _handle_failure(self, chat_log, message: str, mode: str, exc: Exception, request_payload=None):
        traceback_str = frappe.get_traceback()
        frappe.log_error("Jive Chat Error", traceback_str)
        try:
            if chat_log:
                payload = request_payload or {"message": message, "mode": mode, "conversation_id": getattr(chat_log, "name", None)}
                add_message_to_log(chat_log, "user", message, mode, request_payload=payload)
                assistant_kwargs = _assistant_log_payload(status="error", error_message=str(exc), error_traceback=traceback_str)
                assistant_kwargs["request_payload"] = payload
                add_message_to_log(
                    chat_log,
                    "assistant",
                    f"An error occurred: {str(exc)}",
                    mode,
                    **assistant_kwargs,
                )
        except Exception:
            pass

        try:
            from ampower_jive.utils.interaction_logger import InteractionLogger

            InteractionLogger(mode).log(
                status="error",
                error=exc,
                error_traceback=traceback_str,
                request_data={"message": message, "mode": mode},
            )
        except Exception:
            pass

        return {"error": True, "message": f"An error occurred: {str(exc)}"}
