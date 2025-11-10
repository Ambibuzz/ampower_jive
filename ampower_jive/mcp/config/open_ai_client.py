# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import frappe
from openai import OpenAI


class OpenAIConfig:
    """OpenAI connection manager for Frappe applications."""

    def __init__(self):
        if hasattr(self, "_initialized"):
            return

        self._client = None
        self._config = None

    def _get_config(self):
        """Fetch OpenAI configuration from Jive Config singleton."""
        if not self._config:
            self._config = frappe.get_single("Jive Config")
        return self._config

    def _get_helpdesk_model(self) -> str:
        """Fetch OpenAI configuration from Jive Config singleton."""
        config = self._get_config()
        help_desk_model = config.get("help_desk_model")
        return help_desk_model

    @property
    def client(self):
        """Lazy-load OpenAI client instance."""
        if not self._client:
            config = self._get_config()
            api_key = config.get_password("open_ai_key")

            if not api_key:
                frappe.throw("Please setup OpenAI in Jive Config.")

            self._client = OpenAI(api_key=api_key)
        return self._client