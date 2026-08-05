"""
Token Usage Reporting Callback Handler
"""

import frappe
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from typing import Dict, Any, List, Optional
from .config_provider import get_config_provider


class TokenUsageCallbackHandler(BaseCallbackHandler):
    """Callback Handler that logs token usage to Jive Core."""
    
    def __init__(self, agent_type: str, user: str = None, session_id: str = None):
        """
        Initialize callback handler.
        
        Args:
            agent_type: The type of agent (data_query, helpdesk, etc.)
            user: The user who initiated the request
            session_id: The session ID
        """
        self.agent_type = agent_type
        self.user = user or frappe.session.user
        self.session_id = session_id
        self.config_provider = get_config_provider()

    @staticmethod
    def _get_request_log_keys() -> set:
        """Return the per-request registry used to suppress duplicate logs."""
        keys = getattr(frappe.local, "_jive_token_usage_log_keys", None)
        if not isinstance(keys, set):
            keys = set()
            frappe.local._jive_token_usage_log_keys = keys
        return keys

    def _build_event_key(self, response: LLMResult, kwargs: Dict[str, Any]) -> str:
        """
        Build a stable key for the current LLM run.

        LangChain forwards the same run metadata to every callback instance, so
        this lets us ignore duplicate handlers for the same completion while
        still allowing separate completions in the same request to log normally.
        """
        run_id = kwargs.get("run_id")
        if run_id:
            return f"run:{run_id}"

        llm_output = getattr(response, "llm_output", {}) or {}
        token_usage = llm_output.get("token_usage") or {}
        prompt_tokens = int(token_usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(token_usage.get("completion_tokens", 0) or 0)
        total_tokens = int(token_usage.get("total_tokens", 0) or 0)
        model_name = llm_output.get("model_name", "") or ""

        # Fallback to the response object identity so duplicate handlers on the
        # same run collapse cleanly even when LangChain does not expose run_id.
        return (
            f"resp:{id(response)}:"
            f"{self.agent_type}:{model_name}:{prompt_tokens}:{completion_tokens}:{total_tokens}:"
            f"{self.user}:{self.session_id}"
        )

    def _already_logged(self, event_key: str) -> bool:
        """Mark the event key as seen and return True if it was already processed."""
        keys = self._get_request_log_keys()
        if event_key in keys:
            return True
        keys.add(event_key)
        return False
        
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Run when LLM ends running."""
        try:
            # Determine user dynamically if possible (for pooled/cached usage)
            try:
                current_user = frappe.session.user
            except Exception:
                current_user = self.user
            
            # If system/guest, fallback to init user
            if not current_user or current_user == "Guest":
                current_user = self.user

            # print(f"DEBUG: on_llm_end called for {self.agent_type}")
            
            if not response.llm_output:
                return
                
            token_usage = response.llm_output.get("token_usage")
            model_name = response.llm_output.get("model_name", "")
            
            if token_usage:
                prompt_tokens = token_usage.get("prompt_tokens", 0)
                completion_tokens = token_usage.get("completion_tokens", 0)
                total_tokens = token_usage.get("total_tokens", 0)
                
                if total_tokens > 0:
                    event_key = self._build_event_key(response, kwargs)
                    if self._already_logged(event_key):
                        return

                    self.config_provider.report_usage(
                        agent_type=self.agent_type,
                        model=model_name,
                        tokens_in=prompt_tokens,
                        tokens_out=completion_tokens,
                        user=current_user,
                        session_id=self.session_id
                    )
        except Exception as e:
            # Don't fail the request if logging fails
            frappe.log_error(
                message=f"Error in TokenUsageCallbackHandler: {e}",
                title="Token Usage Callback Error"
            )
