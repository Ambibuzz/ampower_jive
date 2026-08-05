"""Compact, log-safe context payload summaries."""

from __future__ import annotations

import json
from typing import Any, Dict


_SUMMARY_FIELDS = ("source_type", "doctype", "name", "label", "workspace_name", "route")
_TITLE_FIELDS = ("title", "title_field", "document_title")
_META_FIELDS = ("title_field", "title_value")


def _add_non_empty_values(summary: Dict[str, Any], payload: Dict[str, Any], fieldnames) -> None:
    for fieldname in fieldnames:
        value = payload.get(fieldname)
        if value not in (None, "", [], {}):
            summary[fieldname] = value


def _summarize_snapshot(summary: Dict[str, Any], payload: Dict[str, Any], fieldname: str, prefix: str) -> None:
    snapshot = payload.get(fieldname)
    if not isinstance(snapshot, dict):
        return

    summary[f"{prefix}_kind"] = snapshot.get("kind")
    summary[f"{prefix}_source"] = snapshot.get("source")

    counts = {
        "controls": f"{prefix}_control_count",
        "charts": f"{prefix}_chart_count",
        "visible_text": f"{prefix}_text_count",
        "summary_cards": f"{prefix}_summary_card_count",
    }
    for key, output_key in counts.items():
        value = snapshot.get(key)
        if isinstance(value, list):
            summary[output_key] = len(value or [])


def summarize_context_payload(context_payload: Any) -> Dict[str, Any]:
    """Return a compact summary suitable for structured debug logs."""
    if not context_payload:
        return {"present": False}

    summary = {
        "present": True,
        "type": type(context_payload).__name__,
    }

    payload = context_payload
    if isinstance(context_payload, str):
        summary["chars"] = len(context_payload)
        try:
            payload = json.loads(context_payload)
        except Exception:
            summary["raw_preview"] = context_payload[:500]
            return summary

    if not isinstance(payload, dict):
        return summary

    summary["keys"] = sorted(payload.keys())[:30]
    _add_non_empty_values(summary, payload, _SUMMARY_FIELDS)
    _add_non_empty_values(summary, payload, _TITLE_FIELDS)

    meta = payload.get("meta")
    if isinstance(meta, dict):
        summary["meta_keys"] = sorted(meta.keys())[:20]
        if meta.get("field_count") not in (None, "", [], {}):
            summary["meta_field_count"] = meta.get("field_count")
        _add_non_empty_values(summary, meta, _META_FIELDS)

    current_doc = payload.get("current_doc")
    if isinstance(current_doc, dict):
        summary["current_doc_keys"] = sorted(current_doc.keys())[:20]

    _summarize_snapshot(summary, payload, "page_snapshot", "page_snapshot")
    _summarize_snapshot(summary, payload, "dashboard_snapshot", "dashboard_snapshot")

    page_fields = payload.get("page_fields")
    if isinstance(page_fields, list):
        summary["page_field_count"] = len(page_fields)
        summary["page_field_names"] = [
            field.get("fieldname")
            for field in page_fields
            if isinstance(field, dict) and field.get("fieldname")
        ][:20]

    page_field_values = payload.get("page_field_values")
    if isinstance(page_field_values, dict):
        summary["page_field_value_count"] = len(page_field_values)

    return summary

