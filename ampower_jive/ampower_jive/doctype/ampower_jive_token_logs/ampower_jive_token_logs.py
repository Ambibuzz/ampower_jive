# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class AmpowerJiveTokenLogs(Document):
    """Store token usage snapshots for the local AmPower Jive app."""

    def before_insert(self):
        if not self.timestamp:
            self.timestamp = now_datetime()

        self.total_tokens = int(self.tokens_in or 0) + int(self.tokens_out or 0)

        if not self.estimated_cost:
            self.estimated_cost = self.calculate_cost()

    def calculate_cost(self) -> float:
        """Estimate cost from the model and token counts."""
        pricing = {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-4o": {"input": 0.005, "output": 0.015},
            "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
            "default": {"input": 0.001, "output": 0.002},
        }

        model_pricing = pricing.get(self.model, pricing["default"])
        input_cost = (int(self.tokens_in or 0) / 1000) * model_pricing["input"]
        output_cost = (int(self.tokens_out or 0) / 1000) * model_pricing["output"]
        return round(input_cost + output_cost, 6)


def log_token_usage(
    site_name,
    agent_type,
    model,
    tokens_in,
    tokens_out,
    user=None,
    session_id=None,
    feature_type="chat",
    request_id=None,
    success=True,
    error_message=None,
    processing_time_ms=0,
    state=None,
):
    """Create a local token usage log and return the document name."""
    try:
        log = frappe.get_doc(
            {
                "doctype": "Ampower Jive Token Logs",
                "site_name": site_name,
                "state": state or "Without Jive Core",
                "user": user or frappe.session.user,
                "session_id": session_id,
                "agent_type": agent_type,
                "feature_type": feature_type,
                "model": model,
                "tokens_in": int(tokens_in or 0),
                "tokens_out": int(tokens_out or 0),
                "request_id": request_id,
                "success": 1 if success else 0,
                "error_message": error_message,
                "processing_time_ms": int(processing_time_ms or 0),
            }
        )
        log.flags.ignore_permissions = True
        log.insert()
        return log.name
    except Exception as exc:
        frappe.log_error(
            message=f"Failed to log local token usage: {exc}",
            title="Ampower Jive Token Log Error",
        )
        return None
