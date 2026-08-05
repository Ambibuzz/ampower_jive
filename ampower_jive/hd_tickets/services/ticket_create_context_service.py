"""Infer HD ticket creation fields from plain-language conversation turns."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


class TicketCreateContextService:
    """Hydrate create-plan arguments from the conversation when fields are omitted."""

    SUBJECT_CAPTURE_RE = re.compile(r"I captured the subject as:\s*(.+)", re.IGNORECASE)
    SUBJECT_LINE_RE = re.compile(r"^Subject:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    PRIORITY_LINE_RE = re.compile(r"^Priority:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    DESCRIPTION_REQUEST_RE = re.compile(r"Please add a fuller description", re.IGNORECASE)
    SUBJECT_REQUEST_RE = re.compile(r"Please share the ticket subject", re.IGNORECASE)
    PRIORITY_REQUEST_RE = re.compile(r"Please add the priority", re.IGNORECASE)
    CUSTOMER_REQUEST_RE = re.compile(r"Which customer should I use\?", re.IGNORECASE)
    QUOTED_TEXT_RE = re.compile(r'"([^"]+)"')

    def enrich(self, tool_args: Dict[str, Any], messages: List[Any], priority_catalog: Iterable[str] | None = None) -> Dict[str, Any]:
        """Fill missing create fields from prior assistant prompts and user follow-ups."""
        enriched = {
            "subject": self._normalize_text(tool_args.get("subject")),
            "description": self._normalize_description(tool_args.get("description")),
            "priority": self._normalize_text(tool_args.get("priority")),
            "customer_hint": self._normalize_text(tool_args.get("customer_hint")),
        }
        normalized_priorities = self._normalize_priorities(priority_catalog or [])
        latest_user_message = self._get_latest_human_message(messages)
        last_assistant_message = self._get_latest_assistant_message(messages)

        remembered = self._extract_confirmed_fields(messages, normalized_priorities)
        for field_name in ("subject", "description", "priority", "customer_hint"):
            if not enriched[field_name]:
                enriched[field_name] = remembered.get(field_name, "")

        inferred_from_latest = self._extract_fields_from_text(latest_user_message, normalized_priorities)
        for field_name in ("subject", "description", "priority", "customer_hint"):
            if not enriched[field_name] and inferred_from_latest.get(field_name):
                enriched[field_name] = inferred_from_latest[field_name]

        missing_fields = self._detect_requested_fields(last_assistant_message)
        if "subject" in missing_fields and not enriched["subject"] and self._is_meaningful_text(latest_user_message):
            enriched["subject"] = latest_user_message.strip()

        if "description" in missing_fields and not enriched["description"] and self._is_meaningful_text(latest_user_message):
            enriched["description"] = self._normalize_description(latest_user_message)

        if "priority" in missing_fields and not enriched["priority"]:
            enriched["priority"] = self._extract_priority_from_text(latest_user_message, normalized_priorities)

        if "customer_hint" in missing_fields and not enriched["customer_hint"] and self._is_meaningful_text(latest_user_message):
            enriched["customer_hint"] = latest_user_message.strip()

        if enriched["subject"] and not enriched["description"] and self._looks_like_issue_detail(latest_user_message, enriched["subject"]):
            enriched["description"] = self._normalize_description(latest_user_message)

        return enriched

    def _extract_confirmed_fields(self, messages: List[Any], priority_catalog: Dict[str, str]) -> Dict[str, str]:
        remembered = {
            "subject": "",
            "description": "",
            "priority": "",
            "customer_hint": "",
        }
        pending_fields: set[str] = set()
        for message in messages or []:
            role = self._message_role(message)
            content = str(getattr(message, "content", "") or "")

            if role == "assistant":
                subject_match = self.SUBJECT_CAPTURE_RE.search(content) or self.SUBJECT_LINE_RE.search(content)
                if subject_match:
                    remembered["subject"] = self._normalize_text(subject_match.group(1))

                priority_match = self.PRIORITY_LINE_RE.search(content)
                if priority_match:
                    remembered["priority"] = self._normalize_priority(priority_match.group(1), priority_catalog)

                pending_fields = self._detect_requested_fields(content)
                continue

            if role != "user":
                continue

            extracted = self._extract_fields_from_text(content, priority_catalog)
            for field_name, value in extracted.items():
                if value:
                    remembered[field_name] = value

            if "subject" in pending_fields and not remembered["subject"] and self._is_meaningful_text(content):
                remembered["subject"] = self._normalize_text(content)

            if "description" in pending_fields and self._is_meaningful_text(content):
                remembered["description"] = self._normalize_description(content)

            if "priority" in pending_fields and not remembered["priority"]:
                remembered["priority"] = self._extract_priority_from_text(content, priority_catalog)

            if "customer_hint" in pending_fields and not remembered["customer_hint"] and self._is_meaningful_text(content):
                remembered["customer_hint"] = self._normalize_text(content)

            pending_fields = set()
        return remembered

    def _extract_fields_from_text(self, text: str, priority_catalog: Dict[str, str]) -> Dict[str, str]:
        raw_text = str(text or "")
        normalized_text = self._normalize_text(raw_text)
        lowered = normalized_text.lower()
        fields = {
            "subject": "",
            "description": "",
            "priority": "",
            "customer_hint": "",
        }
        if not normalized_text:
            return fields

        quoted = self.QUOTED_TEXT_RE.search(raw_text)
        if quoted:
            fields["subject"] = self._normalize_text(quoted.group(1))

        fields["priority"] = self._extract_priority_from_text(normalized_text, priority_catalog)

        description_match = re.search(r"(?is)\bdescription\s*(?:is|:|-)\s*(.+)$", raw_text.strip())
        if description_match:
            fields["description"] = self._normalize_description(description_match.group(1))

        subject_match = re.search(r"(?i)\bsubject\s*(?:is|:|-)\s*(.+?)(?:\s+\bdescription\b|$)", normalized_text)
        if subject_match:
            fields["subject"] = self._normalize_text(subject_match.group(1))

        customer_match = re.search(r"(?i)\bfor\s+customer\s+(.+)$", normalized_text)
        if customer_match:
            fields["customer_hint"] = self._normalize_text(customer_match.group(1))

        if not fields["description"] and self._looks_like_issue_detail(normalized_text, fields["subject"]):
            fields["description"] = self._normalize_description(raw_text)

        if not fields["subject"] and self._looks_like_ticket_request(lowered):
            subject = re.sub(
                r"(?i)\b(?:please|kindly|can you|could you|would you)\b", "", normalized_text,
            )
            subject = re.sub(
                r"(?i)\b(?:create|raise|open|log|submit|file)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:support\s+)?ticket\b", "", subject,
            )
            subject = re.sub(r"(?i)\b(?:for|about|regarding)\b", "", subject).strip(" .:-")
            if subject:
                fields["subject"] = self._normalize_text(subject)

        return fields

    def _detect_requested_fields(self, last_assistant_message: str) -> set[str]:
        fields = set()
        if self.SUBJECT_REQUEST_RE.search(last_assistant_message or ""):
            fields.add("subject")
        if self.DESCRIPTION_REQUEST_RE.search(last_assistant_message or ""):
            fields.add("description")
        if self.PRIORITY_REQUEST_RE.search(last_assistant_message or ""):
            fields.add("priority")
        if self.CUSTOMER_REQUEST_RE.search(last_assistant_message or ""):
            fields.add("customer_hint")
        return fields

    def _extract_priority_from_text(self, text: str, priority_catalog: Dict[str, str]) -> str:
        normalized_text = self._normalize_text(text).lower()
        if not normalized_text:
            return ""
        priority_match = re.search(r"(?i)\bpriority\s*(?:is|:|-)?\s*([A-Za-z ]+)$", text or "")
        if priority_match:
            return self._normalize_priority(priority_match.group(1), priority_catalog)
        for lowered_name, original_name in priority_catalog.items():
            if re.search(rf"\b{re.escape(lowered_name)}\b", normalized_text):
                return original_name
        return ""

    def _looks_like_issue_detail(self, text: str, subject: str = "") -> bool:
        normalized_text = self._normalize_text(text)
        if not normalized_text:
            return False
        lowered = normalized_text.lower()
        if lowered in {"yes", "no", "ok", "okay", "done"}:
            return False
        if subject and lowered == self._normalize_text(subject).lower() and len(lowered) < 32:
            return False
        issue_markers = (
            "error",
            "freeze",
            "stuck",
            "save",
            "open",
            "screen",
            "document",
            "when",
            "while",
            "unable",
            "fails",
            "issue",
            "problem",
        )
        return len(normalized_text) >= 18 and any(marker in lowered for marker in issue_markers)

    def _looks_like_ticket_request(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in (
                "create a ticket",
                "raise a ticket",
                "open a ticket",
                "log a ticket",
                "submit a ticket",
                "file a ticket",
            )
        )

    def _get_latest_human_message(self, messages: List[Any]) -> str:
        for message in reversed(messages or []):
            if self._message_role(message) == "user":
                return str(getattr(message, "content", "") or "")
        return ""

    def _get_latest_assistant_message(self, messages: List[Any]) -> str:
        for message in reversed(messages or []):
            if self._message_role(message) != "assistant":
                continue
            content = str(getattr(message, "content", "") or "")
            if not content.strip():
                continue
            return content
        return ""

    def _normalize_priorities(self, priorities: Iterable[str]) -> Dict[str, str]:
        normalized = {}
        for priority in priorities or []:
            original = self._normalize_text(priority)
            if original:
                normalized[original.lower()] = original
        return normalized

    def _normalize_priority(self, value: str, priority_catalog: Dict[str, str]) -> str:
        normalized = self._normalize_text(value).lower()
        return priority_catalog.get(normalized, "")

    def _normalize_text(self, value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    def _normalize_description(self, value: Any) -> str:
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        return "\n".join(line.rstrip() for line in text.split("\n"))

    def _is_meaningful_text(self, value: str) -> bool:
        text = self._normalize_text(value)
        return bool(text and len(text) >= 3 and text.lower() not in {"yes", "no", "ok", "okay"})

    def _message_role(self, message: Any) -> str:
        name = message.__class__.__name__.lower()
        if "human" in name:
            return "user"
        if "ai" in name or "assistant" in name:
            return "assistant"
        return ""
