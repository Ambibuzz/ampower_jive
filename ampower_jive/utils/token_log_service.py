"""
Token log service for local AmPower Jive usage tracking.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_first_day, nowdate

from ampower_jive.ampower_jive.doctype.ampower_jive_token_logs.ampower_jive_token_logs import (
    log_token_usage,
)


class TokenLogService:
    """Persist and summarize local token usage logs."""

    DAILY_USAGE_FIELD = "local_daily_token_usage"
    MONTHLY_USAGE_FIELD = "local_monthly_token_usage"
    MONTHLY_LIMIT_FIELD = "local_monthly_token_limit"

    def __init__(self, site_name: str | None = None):
        self.site_name = site_name or frappe.local.site

    def log_usage(
        self,
        agent_type: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        user: str = None,
        session_id: str = None,
        feature_type: str = "chat",
        request_id: str = None,
        success: bool = True,
        error_message: str = None,
        processing_time_ms: int = 0,
        state: str = None,
        sync_cached_usage: bool = True,
    ) -> str | None:
        """Create a local token log record and optionally refresh the cached usage snapshot."""
        try:
            state = state or self._current_state_label()

            log_name = log_token_usage(
                site_name=self.site_name,
                agent_type=agent_type,
                model=model,
                tokens_in=int(tokens_in or 0),
                tokens_out=int(tokens_out or 0),
                user=user or frappe.session.user,
                session_id=session_id,
                feature_type=feature_type,
                request_id=request_id,
                success=success,
                error_message=error_message,
                processing_time_ms=processing_time_ms,
                state=state,
            )

            if not log_name:
                return None

            snapshot = self.refresh_usage_snapshot() if sync_cached_usage else self.get_usage_snapshot()
            self._set_runtime_usage(tokens_in, tokens_out, state, snapshot)
            return log_name
        except Exception as exc:
            frappe.log_error(
                message=f"Failed to log local token usage: {exc}",
                title="Ampower Jive Token Log Error",
            )
            return None

    def get_usage_snapshot(self) -> dict:
        """Return the current local usage snapshot without persisting it."""
        daily_current, monthly_current = self._read_usage_totals()
        monthly_limit = self._read_counter(self.MONTHLY_LIMIT_FIELD)
        return {
            "daily": self._build_quota(daily_current, 0),
            "monthly": self._build_quota(monthly_current, monthly_limit),
        }

    def refresh_usage_snapshot(self) -> dict:
        """Recalculate local usage and persist the projection to Jive Config."""
        snapshot = self.get_usage_snapshot()
        self._sync_cached_usage(snapshot)
        return snapshot

    def is_monthly_quota_exceeded(self) -> bool:
        """Return True when the local monthly quota has already been exceeded."""
        monthly = self.get_usage_snapshot().get("monthly", {})
        if monthly.get("unlimited"):
            return False
        return int(monthly.get("current", 0)) > int(monthly.get("limit", 0))

    def build_quota_exceeded_response(self) -> dict:
        """Build a consistent quota-exceeded payload for API responses."""
        snapshot = self.get_usage_snapshot()
        return {
            "status": "error",
            "error": True,
            "quota_exceeded": True,
            "message": "Quota used",
            "token_usage": snapshot,
        }

    def _current_state_label(self) -> str:
        try:
            from ampower_jive.utils.config_provider import get_config_provider

            provider = get_config_provider()
            return "With Jive Core" if provider.is_core_mode() else "Without Jive Core"
        except Exception:
            return "Without Jive Core"

    def _read_usage_totals(self) -> tuple[int, int]:
        """Read daily and monthly totals from the local token log table."""
        try:
            start_of_day = nowdate()
            start_of_month = get_first_day(nowdate())
            result = frappe.db.sql(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN timestamp >= %s THEN total_tokens ELSE 0 END), 0) AS daily_tokens,
                    COALESCE(SUM(total_tokens), 0) AS monthly_tokens
                FROM `tabAmpower Jive Token Logs`
                WHERE site_name = %s
                  AND timestamp >= %s
                """,
                (start_of_day, self.site_name, start_of_month),
                as_dict=True,
            )
            row = result[0] if result else {}
            return int(row.get("daily_tokens") or 0), int(row.get("monthly_tokens") or 0)
        except Exception as exc:
            frappe.log_error(
                message=f"Failed to read local token usage totals: {exc}",
                title="Ampower Jive Token Usage Error",
            )
            return 0, 0

    def _sync_cached_usage(self, snapshot: dict) -> None:
        """Persist the latest usage projection back to Jive Config."""
        try:
            frappe.db.set_single_value(
                "Jive Config",
                self.DAILY_USAGE_FIELD,
                int(snapshot.get("daily", {}).get("current", 0)),
            )
            frappe.db.set_single_value(
                "Jive Config",
                self.MONTHLY_USAGE_FIELD,
                int(snapshot.get("monthly", {}).get("current", 0)),
            )
        except Exception as exc:
            frappe.log_error(
                message=f"Failed to refresh local token counters: {exc}",
                title="Ampower Jive Token Counter Error",
            )

    def _set_runtime_usage(self, tokens_in: int, tokens_out: int, state: str, snapshot: dict) -> None:
        """Expose the latest token usage and snapshot on frappe.local."""
        detail = {
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
            "total_tokens": int(tokens_in or 0) + int(tokens_out or 0),
            "state": state,
            "site_name": self.site_name,
        }
        frappe.local.jive_token_usage_detail = detail
        frappe.local.jive_token_usage = snapshot

    def _read_counter(self, fieldname: str) -> int:
        try:
            value = frappe.db.get_single_value("Jive Config", fieldname)
            return int(value or 0)
        except Exception:
            return 0

    @staticmethod
    def _build_quota(current: int, limit: int) -> dict:
        current = int(current or 0)
        limit = int(limit or 0)

        quota = {
            "current": current,
            "limit": limit,
            "unlimited": limit == 0,
            "allowed": True if limit == 0 else current <= limit,
            "projected": current,
        }
        if limit > 0:
            quota["remaining"] = max(0, limit - current)
        return quota
