# ampower_jive/prompt_provider.py

import time
import frappe
from typing import Dict


class PromptProvider:
    """
    Fetches and caches system prompts from Jive Config or Jive Core.
    TTL-based in-process cache (no Redis).
    
    Uses the config provider abstraction which automatically determines
    whether to fetch prompts locally or from a remote Jive Core instance.
    """

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._last_init: Dict[str, float] = {}
        self._ttl = 300  # 5 minutes

    def get_prompt(self, key: str) -> str:
        """
        Fetch a system prompt by key.

        Valid keys:
        - agent
        - query
        - helpdesk
        - hd_tickets
        - insights
        - context
        
        Automatically fetches from Jive Core if enabled.
        """
        key = (key or "").lower().strip()
        now = time.time()

        # Return cached prompt if valid
        if key in self._cache and (now - self._last_init.get(key, 0)) < self._ttl:
            return self._cache[key]

        # Use config provider (handles local vs remote)
        from .config_provider import get_config_provider
        
        provider = get_config_provider()
        prompt = provider.get_prompt(key)

        # Cache result
        prompt = (prompt or "").strip()
        self._cache[key] = prompt
        self._last_init[key] = now

        return prompt

    def invalidate(self, key: str = None):
        """
        Clear cached prompts.

        If key is provided, clears only that prompt.
        If key is None, clears all cached prompts.
        """
        if key:
            key = key.lower().strip()
            self._cache.pop(key, None)
            self._last_init.pop(key, None)
        else:
            self._cache.clear()
            self._last_init.clear()

_prompt_provider = None


def get_prompt_provider() -> PromptProvider:
    global _prompt_provider
    if _prompt_provider is None:
        _prompt_provider = PromptProvider()
    return _prompt_provider
