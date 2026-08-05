"""Shared LLM access for HD Tickets planning and summaries."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from ampower_jive.agent.llm_pool import get_cached_llm
from ampower_jive.hd_tickets.constants import MODE_KEY
from ampower_jive.utils.config_provider import get_config_provider
from ampower_jive.utils.tokens import TokenUsageCallbackHandler


class TicketLLMService:
    """Provide the configured HD Tickets model."""

    TIMEOUT_SECONDS = 25
    NO_TEMP_MODELS = ("o1", "o3", "search-preview", "gpt-5")

    def __init__(self):
        self._provider = get_config_provider()

    def get_llm(self):
        """Return the configured HD Tickets model."""
        settings = self._provider.get_model_settings("hd_tickets") or {}
        model = settings.get("model") or "gpt-4o-mini"
        temperature = settings.get("temperature", 0.1)
        callbacks = [TokenUsageCallbackHandler(MODE_KEY)]

        llm = get_cached_llm(
            purpose=MODE_KEY,
            model=model,
            temperature=temperature,
            timeout=self.TIMEOUT_SECONDS,
            callbacks=callbacks,
        )
        if llm:
            return llm

        api_key = self._provider.get_api_key()
        if not api_key:
            return None

        supports_temperature = not any(token in model.lower() for token in self.NO_TEMP_MODELS)
        kwargs = {
            "model": model,
            "api_key": api_key,
            "timeout": self.TIMEOUT_SECONDS,
            "max_retries": 1,
            "callbacks": callbacks,
        }
        if supports_temperature:
            kwargs["temperature"] = temperature
        return ChatOpenAI(**kwargs)

    def get_bound_llm(self, tools):
        """Return the configured HD Tickets model bound to the provided tools."""
        llm = self.get_llm()
        return llm.bind_tools(tools) if llm else None
