# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

from __future__ import annotations

from frappe.model.document import Document
from frappe.utils import now_datetime


class JiveChatMessage(Document):
    """Store one chat turn with both the question and response."""

    def before_insert(self):
        if not self.timestamp:
            self.timestamp = now_datetime()

        self._normalize_turn_fields()
        self._sync_total_tokens()

        if not self.status and getattr(self, "response", None):
            self.status = "error" if self.error_message or self.error_traceback else "success"

    def validate(self):
        self._normalize_turn_fields()
        self._sync_total_tokens()
        if not self.status and getattr(self, "response", None):
            self.status = "error" if self.error_message or self.error_traceback else "success"

    def _normalize_turn_fields(self) -> None:
        """Backfill new fields from legacy rows and keep the stored row consistent."""
        question = getattr(self, "question", None)
        response = getattr(self, "response", None)
        content = getattr(self, "content", None)
        role = (getattr(self, "role", None) or "").lower()

        if not question and role == "user" and content:
            self.question = content

        if not response:
            if role == "assistant" and content:
                self.response = content

        if getattr(self, "response", None):
            self.content = self.response
        elif getattr(self, "question", None):
            self.content = self.question

        if getattr(self, "question", None) and getattr(self, "response", None):
            self.role = "turn"
        elif role == "turn":
            self.role = "turn"

    def _sync_total_tokens(self) -> None:
        self.total_tokens = int(self.tokens_in or 0) + int(self.tokens_out or 0)
