"""Service layer for helpdesk queries."""

from __future__ import annotations

import json
import frappe

from ampower_jive.utils.agent_prompt_defaults import build_helpdesk_fallback_prompt
from ampower_jive.api_features.common import _ensure_local_monthly_quota
from ampower_jive.agent.llm_pool import compress_history, get_cached_llm
from ampower_jive.utils.followup_suggestions import append_followup_prompt
from ampower_jive.utils.tokens import TokenUsageCallbackHandler


HELPDESK_FAST_RESPONSES = {
    r"how\s+to\s+create\s+(a\s+)?(sales\s+)?invoice": """**Creating a Sales Invoice in ERPNext:**

1. Go to **Selling → Sales Invoice → New**
2. Select **Customer** (mandatory)
3. Add items in the **Items table**
4. Set **Posting Date** and **Due Date**
5. Click **Save** then **Submit**

**Quick tip:** You can also create from Sales Order using "Make → Sales Invoice".""",
    r"how\s+to\s+create\s+(a\s+)?customer": """**Creating a Customer in ERPNext:**

1. Go to **Selling → Customer → New**
2. Enter **Customer Name** (mandatory)
3. Set **Customer Type**: Individual/Company
4. Set **Customer Group** and **Territory**
5. Click **Save**

**Quick tip:** Customers can also be auto-created from Quotation or Sales Order.""",
    r"how\s+to\s+create\s+(an?\s+)?item": """**Creating an Item in ERPNext:**

1. Go to **Stock → Item → New**
2. Enter **Item Code** and **Item Name**
3. Set **Item Group** and **Stock UOM**
4. Check **Maintain Stock** if it's a physical item
5. Click **Save**

**Quick tip:** You can duplicate an existing item to save time.""",
}


class HelpdeskQueryService:
    """Encapsulate the helpdesk query flow behind a small service object."""

    DEFAULT_PROMPT = build_helpdesk_fallback_prompt()
    FILE_LIMIT = 3
    FILE_CHAR_LIMIT = 8000
    FILE_CONTEXT_LIMIT = 20000
    HISTORY_LIMIT = 3
    HISTORY_CHAR_LIMIT = 1200
    LLM_TIMEOUT = 30
    NO_TEMP_MODELS = ("o1", "o3", "search-preview", "gpt-5")

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or "default"
        self.interaction_logger = None

    def process(
        self,
        message: str,
        history: list,
        session_id: str = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        custom_prompt: str = None,
    ) -> str | dict:
        from ampower_jive.utils.interaction_logger import InteractionLogger

        self.session_id = session_id or self.session_id
        self.interaction_logger = InteractionLogger("helpdesk")

        try:
            fast_response = self._match_fast_response(message) if not history else None
            if fast_response:
                self._log_success(
                    message=message,
                    response=fast_response,
                    model="helpdesk_fast_path",
                    temperature=temperature,
                    session_id=self.session_id,
                    request_data={"message": message, "fast_path": True},
                )
                return fast_response

            api_key, model = self._resolve_model()
            if not api_key:
                return "OpenAI API key is not configured. Please set it up in Jive Config or enable Jive Core."

            quota_response = _ensure_local_monthly_quota()
            if quota_response:
                return quota_response

            context_files = self._load_context_files()
            file_context = self._build_file_context(context_files)
            helpdesk_prompt = self._build_prompt(custom_prompt, file_context)
            llm = self._build_llm(model=model, temperature=temperature, max_tokens=max_tokens, api_key=api_key)

            compressed_history = compress_history(history or [], max_messages=self.HISTORY_LIMIT, max_chars=self.HISTORY_CHAR_LIMIT)
            messages = [{"role": "system", "content": helpdesk_prompt}]
            messages.extend({"role": msg["role"], "content": msg["content"]} for msg in compressed_history)
            messages.append({"role": "user", "content": message})

            return self._invoke_llm(
                llm=llm,
                messages=messages,
                message=message,
                model=model,
                temperature=temperature,
                session_id=self.session_id,
            )
        except Exception as exc:
            traceback_str = frappe.get_traceback()
            frappe.log_error("Helpdesk Query Error", traceback_str)
            self._log_error(
                message=message,
                error=exc,
                traceback_str=traceback_str,
                session_id=self.session_id,
            )
            return f"I encountered an error while processing your question: {str(exc)}"

    def _resolve_model(self) -> tuple[str | None, str]:
        from ampower_jive.utils.config_provider import get_config_provider

        provider = get_config_provider()
        api_key = provider.get_api_key()
        config = provider.get_local_config()
        model = (config.get("help_desk_model") if config else None) or "gpt-4o-mini"
        return api_key, model

    def _load_context_files(self) -> list:
        context_key = f"jive_context:{frappe.session.user}:{self.session_id}"
        existing_data = frappe.cache().hget(context_key, "files")
        if not existing_data:
            return []

        try:
            return json.loads(existing_data) or []
        except Exception:
            return []

    def _build_file_context(self, context_files: list) -> str:
        if not context_files:
            return ""

        parts = []
        for ctx in context_files[: self.FILE_LIMIT]:
            if not isinstance(ctx, dict):
                continue

            file_content = (ctx.get("content") or "")[: self.FILE_CHAR_LIMIT]
            if len(ctx.get("content") or "") > self.FILE_CHAR_LIMIT:
                file_content += "\n... [truncated]"

            file_type = ctx.get("file_type", "unknown")
            parts.append(f"[{file_type.upper()}]:\n{file_content}")

        file_context = "\n\n".join(parts)
        if len(file_context) > self.FILE_CONTEXT_LIMIT:
            file_context = f"{file_context[: self.FILE_CONTEXT_LIMIT]}\n... [truncated]"
        return file_context

    def _build_prompt(self, custom_prompt: str, file_context: str) -> str:
        base_prompt = custom_prompt or self.DEFAULT_PROMPT
        base_prompt = append_followup_prompt(base_prompt)

        if not file_context:
            return base_prompt

        prompt = (
            "You are a helpful AI assistant with document context.\n\n"
            "=== DOCUMENT CONTENT ===\n"
            f"{file_context}\n"
            "=== END ===\n\n"
            "Answer based on the documents above. Be precise and quote relevant info.\n"
            "REQUIRED: After the answer, include exactly 3 strong follow-up questions "
            "in the hidden follow-up block unless you genuinely cannot produce them."
        )
        return append_followup_prompt(prompt)

    def _build_llm(self, model: str, temperature: float, max_tokens: int, api_key: str):
        temperature_value = 0.0 if any(token in (model or "").lower() for token in self.NO_TEMP_MODELS) else temperature

        llm = get_cached_llm(
            purpose="helpdesk",
            model=model,
            temperature=temperature_value,
            timeout=self.LLM_TIMEOUT,
            callbacks=[TokenUsageCallbackHandler("helpdesk")],
        )
        if llm:
            return llm

        from langchain_openai import ChatOpenAI

        supports_temperature = not any(token in (model or "").lower() for token in self.NO_TEMP_MODELS)
        kwargs = {
            "model": model,
            "api_key": api_key,
            "max_tokens": max_tokens,
            "timeout": self.LLM_TIMEOUT,
            "max_retries": 1,
            "callbacks": [TokenUsageCallbackHandler("helpdesk")],
        }
        if supports_temperature:
            kwargs["temperature"] = temperature
        return ChatOpenAI(**kwargs)

    def _invoke_llm(
        self,
        llm,
        messages: list,
        message: str,
        model: str,
        temperature: float,
        session_id: str,
    ) -> str:
        import time

        llm_start = time.time()
        try:
            response = llm.invoke(messages)
            raw_response = response.content if response and getattr(response, "content", None) else ""
            processing_time_ms = int((time.time() - llm_start) * 1000)
            self._log_success(
                message=message,
                response=raw_response,
                model=model,
                temperature=temperature,
                session_id=session_id,
                request_data={"messages": messages, "model": model, "temperature": temperature},
                processing_time_ms=processing_time_ms,
            )
            return raw_response
        except Exception as exc:
            processing_time_ms = int((time.time() - llm_start) * 1000)
            status = "timeout" if "timeout" in str(exc).lower() else "error"
            self._log_error(
                message=message,
                error=exc,
                traceback_str=frappe.get_traceback(),
                session_id=session_id,
                request_data={"messages": messages, "model": model, "temperature": temperature},
                status=status,
                processing_time_ms=processing_time_ms,
            )
            if status == "timeout":
                return "⏱️ Request timed out. Please try a shorter question."
            raise

    def _match_fast_response(self, message: str) -> str | None:
        import re

        msg_lower = (message or "").lower()
        for pattern, response in HELPDESK_FAST_RESPONSES.items():
            if re.search(pattern, msg_lower):
                return response
        return None

    def _log_success(
        self,
        message: str,
        response: str,
        model: str,
        temperature: float,
        session_id: str,
        request_data: dict | None = None,
        processing_time_ms: int = 0,
    ) -> None:
        if not self.interaction_logger:
            return

        self.interaction_logger.log(
            request_data=request_data or {"message": message, "model": model, "temperature": temperature},
            response_data=response,
            model=model,
            status="success",
            processing_time_ms=processing_time_ms,
            session_id=session_id,
        )

    def _log_error(
        self,
        message: str,
        error: Exception,
        traceback_str: str,
        session_id: str,
        request_data: dict | None = None,
        status: str = "error",
        processing_time_ms: int = 0,
    ) -> None:
        if not self.interaction_logger:
            return

        try:
            self.interaction_logger.log(
                request_data=request_data or {"message": message},
                model="helpdesk",
                status=status,
                error=error,
                error_traceback=traceback_str,
                processing_time_ms=processing_time_ms,
                session_id=session_id,
            )
        except Exception:
            pass
