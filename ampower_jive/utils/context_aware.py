"""
Context Aware Mode helpers.

This module keeps the context-aware flow separate from the existing data query
mode so we can reuse the same Frappe permissions and LLM plumbing without
duplicating the old chat pipeline.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict

import frappe
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from ampower_jive.agent.llm_pool import compress_history, get_cached_llm
from ampower_jive.utils.followup_suggestions import append_followup_prompt, strip_followup_block
from ampower_jive.utils.config_provider import get_config_provider
from ampower_jive.utils.prompt_provider import get_prompt_provider
from ampower_jive.utils.tokens import TokenUsageCallbackHandler


DEFAULT_CONTEXT_PROMPT = """You are AI Agent in Context Aware Mode.

Your job is to answer the user's question using the current page context.

Rules:
- Use the provided JSON context as the source of truth.
- The context is already organized and trimmed to the relevant fields, child tables, and linked records for the question.
- If the page is a dashboard or analytics page, use the dashboard snapshot, summary cards, chart summaries, controls, and visible text as the source of truth.
- When a page snapshot contains a metric label and a value, treat that value as exact.
- If visible text contains a KPI, percentage, amount, alert, or recommendation, answer from that text directly instead of asking for more data.
- Do not say the metric is missing if it already appears anywhere in the page snapshot or visible text.
- If a title or field value is present, treat it as an exact value, not a suggestion.
- Summarize, explain fields, identify patterns, and answer data questions.
- Use linked-doctype metadata and linked record data when present to improve cross-document accuracy.
- Use child-table data when present to answer questions about checklist rows, nested detail rows, and line items.
- If the metadata includes related-title matches, use those exact matches from the register to answer questions about similar or duplicate items/assets.
- If the context is incomplete or the user is asking about a related record that is not present, ask one concise clarifying question instead of guessing.
- Only rely on linked-doctype details when they are present in the linked context; do not assume every relation has been expanded.
- If a linked record or child table is present, do not answer that the details are missing.
- Mention when the context is truncated or incomplete.
- If the view is unsupported or missing, say so clearly.
- Do not invent values that are not present in the context.
- Prefer concise, helpful answers with bullets when useful.
- If you can provide exactly 3 strong follow-up questions, append the hidden follow-up block at the end using the required JSON format.

Context JSON:
{context_json}

Metadata JSON:
{metadata_json}

User question:
{user_question}
"""

DEFAULT_CONTEXT_FALLBACK_MESSAGE = (
    "I could not detect a supported open view. Open a form, list, or workspace "
    "and I will use that page as context."
)

INTERNAL_DOC_KEYS = {
    "_assign",
    "_comments",
    "_liked_by",
    "_user_tags",
    "__islocal",
    "__onload",
    "__unsaved",
    "__deleted",
}

IGNORED_META_FIELD_TYPES = {
    "Section Break",
    "Column Break",
    "Tab Break",
    "HTML",
    "Button",
    "Fold",
}

LINK_FIELD_TYPES = {"Link", "Dynamic Link"}
MAX_LINKED_DOCTYPES = 5
MAX_LINKED_FIELDS = 12
MAX_LINKED_RECORD_FIELDS = 8
MAX_CHILD_TABLES = 8
MAX_CHILD_TABLE_SAMPLE_ROWS = 5
MAX_CHILD_TABLE_SAMPLE_FIELDS = 8
MAX_CHILD_TABLE_FULL_ROWS = 35
MAX_CHILD_TABLE_VALUE_CHARS = 4000
MAX_CONTEXT_JSON_CHARS = 20000
MAX_METADATA_JSON_CHARS = 12000
DEFAULT_MAX_CONTEXT_TOKENS = 12000
RELATED_TITLE_TARGETS = {
    "Item": ("Item", "Asset"),
    "Asset": ("Asset", "Item"),
}
RELATED_TITLE_FIELD_CANDIDATES = ("item_name", "asset_name", "title", "subject", "name")


class ContextBudgetExceededError(Exception):
    """Raised when the prompt remains over budget after trimming."""

    def __init__(self, limit: int, estimated: int, source_label: str = ""):
        self.limit = limit
        self.estimated = estimated
        self.source_label = source_label
        label = f" for {source_label}" if source_label else ""
        super().__init__(
            f"Current page context{label} exceeds the configured token limit ({estimated} > {limit})."
        )


@dataclass
class ContextExtractionResult:
    ok: bool
    source_type: str = ""
    source_label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "source_type": self.source_type,
            "source_label": self.source_label,
            "metadata": self.metadata,
            "data": self.data,
            "warnings": self.warnings,
            "error": self.error,
        }


def _safe_json_copy(value: Any) -> Any:
    """Convert a Python object into a JSON-safe structure."""
    try:
        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except Exception:
        return value


def _truncate_string(value: str, max_chars: Optional[int] = None) -> str:
    if value is None:
        return ""
    if max_chars is None:
        return value
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "\n... [truncated]"


def _sanitize_value(value: Any, max_chars: Optional[int] = None) -> Any:
    """Recursively sanitize values for prompt-safe JSON."""
    if isinstance(value, str):
        return _truncate_string(value, max_chars=max_chars)

    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key in INTERNAL_DOC_KEYS:
                continue
            sanitized[key] = _sanitize_value(item, max_chars=max_chars)
        return sanitized

    if isinstance(value, list):
        cleaned = []
        for item in value:
            if isinstance(item, dict):
                cleaned.append(_clean_child_row(item))
            else:
                cleaned.append(_sanitize_value(item, max_chars=max_chars))
        return cleaned

    return _safe_json_copy(value)


def _clean_child_row(row: Dict[str, Any], child_meta=None, max_chars: Optional[int] = None) -> Dict[str, Any]:
    """Strip system-only child row fields while preserving the business data."""
    if not isinstance(row, dict):
        return {}

    system_fields = {
        "doctype",
        "name",
        "idx",
        "docstatus",
        "owner",
        "creation",
        "modified",
        "modified_by",
        "parent",
        "parenttype",
        "parentfield",
        "_user_tags",
        "_comments",
        "_liked_by",
        "_assign",
        "__islocal",
        "__onload",
        "__unsaved",
        "__deleted",
    }

    if child_meta:
        allowed = {
            field.fieldname
            for field in getattr(child_meta, "fields", [])
            if getattr(field, "fieldname", None) and getattr(field, "fieldtype", None) not in IGNORED_META_FIELD_TYPES
        }
        allowed.update({"name"})
        return {
            key: _sanitize_value(value, max_chars=max_chars)
            for key, value in row.items()
            if key in allowed and key not in system_fields
        }

    return {
        key: _sanitize_value(value, max_chars=max_chars)
        for key, value in row.items()
        if key not in system_fields and not str(key).startswith("_")
    }


def _truncate_child_tables(
    data: Dict[str, Any],
    child_limit: Optional[int] = None,
    full_row_threshold: int = MAX_CHILD_TABLE_FULL_ROWS,
    value_chars: int = MAX_CHILD_TABLE_VALUE_CHARS,
    preferred_tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Keep child tables compact while preserving the relevant business rows."""
    sanitized: Dict[str, Any] = {}
    truncated_tables: Dict[str, Dict[str, int]] = {}
    preferred_table_set = set(preferred_tables or [])
    base_row_limit = child_limit if isinstance(child_limit, int) and child_limit > 0 else full_row_threshold
    base_row_limit = max(1, base_row_limit)
    sample_row_limit = min(base_row_limit, MAX_CHILD_TABLE_SAMPLE_ROWS)

    for key, value in (data or {}).items():
        if key in INTERNAL_DOC_KEYS:
            continue

        if isinstance(value, list):
            try:
                if preferred_table_set:
                    row_limit = len(value) if key in preferred_table_set else sample_row_limit
                else:
                    row_limit = base_row_limit

                row_limit = min(max(1, row_limit), len(value)) if value else 0
                row_items = value[:row_limit] if row_limit else []
                cleaned_rows = [
                    _clean_child_row(item, max_chars=value_chars)
                    for item in row_items
                    if isinstance(item, dict)
                ]
                sanitized[key] = cleaned_rows

                if len(value) > len(cleaned_rows):
                    truncated_tables[key] = {
                        "original_row_count": len(value),
                        "returned_row_count": len(cleaned_rows),
                        "row_limit": row_limit,
                    }
            except Exception:
                sanitized[key] = [_sanitize_value(item, max_chars=value_chars) for item in value]
        else:
            sanitized[key] = _sanitize_value(value, max_chars=value_chars)

    return {
        "data": sanitized,
        "truncated_tables": truncated_tables,
    }


def _render_prompt_template(template: str, values: Dict[str, str]) -> str:
    """Replace known placeholders without touching unrelated braces."""
    rendered = template or DEFAULT_CONTEXT_PROMPT
    placeholder_used = False

    for key, value in values.items():
        placeholder = "{" + key + "}"
        if placeholder in rendered:
            rendered = rendered.replace(placeholder, value)
            placeholder_used = True

    if placeholder_used:
        return rendered

    return (
        rendered.rstrip()
        + "\n\n=== VIEW CONTEXT ===\n"
        + values.get("context_json", "{}")
        + "\n\n=== METADATA ===\n"
        + values.get("metadata_json", "{}")
        + "\n\n=== USER QUESTION ===\n"
        + values.get("user_question", "")
    )


def _route_to_source_type(route: Any) -> str:
    route_parts = []
    if isinstance(route, list):
        route_parts = [str(part or "").lower() for part in route]
    elif isinstance(route, str):
        route_parts = [part.strip().lower() for part in route.split("/") if part.strip()]

    if "form" in route_parts:
        return "form"
    if "list" in route_parts:
        return "list"
    if "workspace" in route_parts or "workspaces" in route_parts:
        return "workspace"
    if "dashboard-view" in route_parts or "dashboard" in route_parts:
        return "page"
    if "page" in route_parts:
        return "page"
    return ""


def _get_route_label(route: Any) -> str:
    if isinstance(route, list):
        return "/".join([str(part) for part in route if part is not None])
    if isinstance(route, str):
        return route
    return ""


def _is_ignored_meta_field(field) -> bool:
    return not field or not field.fieldname or field.fieldtype in IGNORED_META_FIELD_TYPES


def _is_link_field(field) -> bool:
    return bool(field and field.fieldtype in LINK_FIELD_TYPES)


def _sanitize_field_options(field) -> Optional[str]:
    if not field:
        return None
    if field.fieldtype not in {"Link", "Select", "Table", "Dynamic Link"}:
        return None
    options = getattr(field, "options", None)
    return options or None


def _summarize_doctype_meta(doctype: str, field_limit: int = MAX_LINKED_FIELDS) -> Dict[str, Any]:
    meta = frappe.get_meta(doctype)
    fields = []
    for field in meta.fields:
        if _is_ignored_meta_field(field):
            continue
        fields.append(
            {
                "fieldname": field.fieldname,
                "label": field.label or field.fieldname,
                "fieldtype": field.fieldtype,
                "reqd": bool(field.reqd),
                "read_only": bool(field.read_only),
                "options": _sanitize_field_options(field),
            }
        )

    return {
        "doctype": doctype,
        "label": getattr(meta, "label", None) or doctype,
        "title_field": getattr(meta, "title_field", None),
        "sort_field": getattr(meta, "sort_field", None),
        "is_submittable": bool(meta.is_submittable),
        "field_count": len(fields),
        "fields": fields[:field_limit],
    }


def _pick_title_value(meta, doc_dict: Dict[str, Any]) -> Any:
    candidates = [
        getattr(meta, "title_field", None),
        "title",
        "subject",
        "customer_name",
        "item_name",
        "full_name",
        "company_name",
        "name",
    ]
    for key in candidates:
        if key and doc_dict.get(key) not in (None, ""):
            return doc_dict.get(key)
    return None


def _summarize_linked_record(doc, meta, field_limit: int = MAX_LINKED_RECORD_FIELDS) -> Dict[str, Any]:
    doc_dict = _safe_json_copy(doc.as_dict())
    summary_fields = []

    priority_fields = []
    title_field = getattr(meta, "title_field", None)
    if title_field:
        priority_fields.append(title_field)

    for field in meta.fields:
        if _is_ignored_meta_field(field):
            continue
        if field.fieldname in {"name", "docstatus", "modified", "owner", "creation"}:
            if field.fieldname not in priority_fields:
                priority_fields.append(field.fieldname)
        elif field.fieldtype not in {"Table", "Table MultiSelect"} and field.fieldname not in priority_fields:
            priority_fields.append(field.fieldname)

    seen = set()
    for fieldname in priority_fields:
        if not fieldname or fieldname in seen:
            continue
        if fieldname not in doc_dict:
            continue
        seen.add(fieldname)
        field = meta.get_field(fieldname)
        summary_fields.append(
            {
                "fieldname": fieldname,
                "label": (field.label if field else fieldname),
                "fieldtype": (field.fieldtype if field else None),
                "value": _sanitize_value(doc_dict.get(fieldname), max_chars=600),
            }
        )
        if len(summary_fields) >= field_limit:
            break

    return {
        "doctype": meta.name,
        "name": doc_dict.get("name"),
        "label": _pick_title_value(meta, doc_dict),
        "summary_fields": summary_fields,
    }


def _priority_fieldnames(meta, row: Dict[str, Any], limit: int = 6) -> List[str]:
    """Pick a compact set of fields that best describe a child table row."""
    priorities: List[str] = []

    candidates = [
        getattr(meta, "title_field", None) if meta else None,
        "name",
        "idx",
        "item_code",
        "item_name",
        "checklist_item",
        "checklist",
        "parameter",
        "field",
        "label",
        "question",
        "description",
        "status",
        "result",
        "value",
        "remarks",
        "comments",
        "observation",
    ]

    seen = set()
    for fieldname in candidates:
        if not fieldname or fieldname in seen:
            continue
        seen.add(fieldname)
        if fieldname in row:
            priorities.append(fieldname)
        if len(priorities) >= limit:
            return priorities

    if meta:
        for field in getattr(meta, "fields", []):
            fieldname = getattr(field, "fieldname", None)
            if not fieldname or fieldname in seen:
                continue
            if fieldname in row and field.fieldtype not in IGNORED_META_FIELD_TYPES:
                priorities.append(fieldname)
                if len(priorities) >= limit:
                    break
    else:
        for fieldname in row.keys():
            if fieldname not in seen:
                priorities.append(fieldname)
                if len(priorities) >= limit:
                    break

    return priorities


def _summarize_child_table_rows(child_doctype: str, rows: List[Dict[str, Any]], row_limit: int = MAX_CHILD_TABLE_SAMPLE_ROWS) -> Dict[str, Any]:
    """Return a compact summary for a child table."""
    try:
        child_meta = frappe.get_meta(child_doctype)
    except Exception:
        child_meta = None

    sample_rows = []
    for row in rows[:row_limit]:
        if not isinstance(row, dict):
            continue
        fieldnames = _priority_fieldnames(child_meta, row, limit=MAX_CHILD_TABLE_SAMPLE_FIELDS) if child_meta else list(row.keys())[:MAX_CHILD_TABLE_SAMPLE_FIELDS]
        sample_rows.append({
            field: _sanitize_value(row.get(field), max_chars=250)
            for field in fieldnames
            if row.get(field) is not None
        })

    if len(rows) <= row_limit:
        sample_rows = [_sanitize_value(row, max_chars=600) for row in rows if isinstance(row, dict)]

    return {
        "child_doctype": child_doctype,
        "row_count": len(rows),
        "showing": len(sample_rows),
        "sample_rows": sample_rows,
    }


def _collect_child_table_context(meta, source_data: Dict[str, Any], user_question: str = "", selected_tables: Optional[List[str]] = None) -> Dict[str, Any]:
    """Collect child table context and include a compact sample of rows."""
    child_tables = []
    child_table_index = []
    selected_table_set = set(selected_tables or [])
    any_truncated = False

    for field in getattr(meta, "fields", []):
        if field.fieldtype != "Table" or not field.fieldname:
            continue

        rows = source_data.get(field.fieldname)
        if not isinstance(rows, list):
            continue

        if selected_table_set and field.fieldname not in selected_table_set:
            continue

        child_doctype = field.options or None
        child_meta = None
        table_entry: Dict[str, Any] = {
            "fieldname": field.fieldname,
            "label": field.label or field.fieldname,
            "child_doctype": child_doctype,
            "row_count": len(rows),
            "is_child_table": True,
        }

        if child_doctype and frappe.has_permission(child_doctype, "read"):
            try:
                child_meta = frappe.get_meta(child_doctype)
                child_fields = []
                for cfield in child_meta.fields:
                    if cfield.fieldtype in IGNORED_META_FIELD_TYPES:
                        continue
                    if not cfield.fieldname:
                        continue
                    child_fields.append(
                        {
                            "fieldname": cfield.fieldname,
                            "label": cfield.label or cfield.fieldname,
                            "fieldtype": cfield.fieldtype,
                            "required": bool(cfield.reqd),
                            "read_only": bool(cfield.read_only),
                            "options": cfield.options if cfield.fieldtype in {"Link", "Select", "Table", "Dynamic Link"} else None,
                        }
                    )

                table_entry.update(
                    {
                        "child_label": getattr(child_meta, "label", None) or child_doctype,
                        "title_field": getattr(child_meta, "title_field", None),
                        "fields": child_fields[:12],
                        "queryable_fields": [
                            item["fieldname"]
                            for item in child_fields
                            if item["fieldname"] not in {"idx", "docstatus", "owner", "modified_by", "parent", "parenttype", "parentfield"}
                        ][:12],
                    }
                )
            except Exception:
                table_entry.update(
                    {
                        "child_label": child_doctype,
                        "fields": [],
                        "queryable_fields": ["name"],
                    }
                )
        else:
            table_entry.update(
                {
                    "child_label": child_doctype or field.label or field.fieldname,
                    "fields": [],
                    "queryable_fields": ["name"],
                }
            )

        row_limit = len(rows) if selected_table_set and field.fieldname in selected_table_set else min(len(rows), MAX_CHILD_TABLE_SAMPLE_ROWS)
        table_rows = rows[:row_limit]
        table_entry["rows"] = [_clean_child_row(row, child_meta=child_meta, max_chars=250) for row in table_rows if isinstance(row, dict)]
        table_entry["sample_row_count"] = len(table_entry["rows"])
        table_entry["truncated"] = len(rows) > len(table_entry["rows"])
        if table_entry["truncated"]:
            any_truncated = True
        child_tables.append(table_entry)
        child_table_index.append(
            {
                "fieldname": field.fieldname,
                "label": field.label or field.fieldname,
                "child_doctype": child_doctype,
                "row_count": len(rows),
            }
        )

    return {
        "child_tables": child_tables,
        "child_tables_count": len(child_tables),
        "child_tables_truncated": any_truncated,
        "child_table_index": child_table_index,
        "child_table_focus": list(selected_table_set),
    }


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize_norm(value: Any) -> List[str]:
    text = _normalize_text(value)
    if not text:
        return []
    tokens = []
    for token in text.split():
        if len(token) > 3 and token.endswith("s"):
            tokens.append(token[:-1])
        else:
            tokens.append(token)
    return [token for token in tokens if token]


def _text_matches_question(question: str, candidate: Any) -> bool:
    q_text = _normalize_text(question)
    c_text = _normalize_text(candidate)
    if not q_text or not c_text:
        return False

    if c_text in q_text:
        return True

    q_tokens = set(_tokenize_norm(q_text))
    c_tokens = _tokenize_norm(c_text)
    if not c_tokens:
        return False

    matched = sum(1 for token in c_tokens if token in q_tokens)
    if matched == len(c_tokens):
        return True
    return matched >= max(1, min(2, len(c_tokens)))


def _is_related_title_question(question: str) -> bool:
    text = _normalize_text(question)
    if not text:
        return False

    patterns = (
        r"\bsame title\b",
        r"\bsimilar title\b",
        r"\bsame name\b",
        r"\bmatching title\b",
        r"\bduplicate\b",
        r"\brelated (?:item|items|asset|assets|record|records|register)\b",
        r"\b(?:item|asset|record)s?\s+from\s+the\s+register\b",
        r"\blist (?:all )?(?:items|assets).*(?:same|similar).*(?:title|name)\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _select_title_field(meta, doc_dict: Dict[str, Any]) -> Optional[str]:
    candidates = [
        getattr(meta, "title_field", None),
        "item_name",
        "asset_name",
        "title",
        "subject",
        "customer_name",
        "company_name",
        "name",
    ]
    for fieldname in candidates:
        if not fieldname:
            continue
        if fieldname in doc_dict and doc_dict.get(fieldname) not in (None, ""):
            return fieldname
        if meta and meta.get_field(fieldname):
            return fieldname
    return None


def _build_related_title_record_summary(meta, doc_dict: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "doctype": meta.name,
        "name": doc_dict.get("name"),
        "label": _pick_title_value(meta, doc_dict),
        "match_field": None,
        "match_value": None,
        "summary_fields": [],
    }

    title_field = _select_title_field(meta, doc_dict)
    if title_field and doc_dict.get(title_field) not in (None, ""):
        summary["match_field"] = title_field
        summary["match_value"] = doc_dict.get(title_field)

    priority_fields = [
        "name",
        "item_code",
        "item_name",
        "asset_name",
        "item_group",
        "asset_category",
        "docstatus",
        "status",
        "disabled",
        "is_stock_item",
        "is_fixed_asset",
        "description",
        "brand",
        "company",
    ]
    seen = set()
    for fieldname in priority_fields:
        if fieldname in seen or fieldname not in doc_dict or doc_dict.get(fieldname) in (None, ""):
            continue
        seen.add(fieldname)
        summary["summary_fields"].append(
            {
                "fieldname": fieldname,
                "label": (meta.get_field(fieldname).label if meta.get_field(fieldname) else fieldname),
                "fieldtype": (meta.get_field(fieldname).fieldtype if meta.get_field(fieldname) else None),
                "value": _sanitize_value(doc_dict.get(fieldname), max_chars=300),
            }
        )
        if len(summary["summary_fields"]) >= 8:
            break

    return summary


def _fetch_related_title_records(doctype: str, title_value: Any, current_name: str = None) -> List[Dict[str, Any]]:
    if not doctype or title_value in (None, ""):
        return []
    if not frappe.has_permission(doctype, "read"):
        return []

    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return []

    candidate_fields = []
    for fieldname in RELATED_TITLE_FIELD_CANDIDATES:
        if meta.get_field(fieldname):
            candidate_fields.append(fieldname)

    if getattr(meta, "title_field", None) and meta.title_field not in candidate_fields and meta.get_field(meta.title_field):
        candidate_fields.insert(0, meta.title_field)

    if not candidate_fields:
        return []

    records = []
    seen = set()
    for fieldname in candidate_fields:
        try:
            rows = frappe.get_all(
                doctype,
                filters={fieldname: title_value},
                fields=[
                    "name",
                    *(field for field in candidate_fields if field != fieldname),
                    "docstatus",
                    "modified",
                ],
                limit=10,
                order_by="modified desc",
            )
        except Exception:
            rows = []

        for row in rows or []:
            row_name = row.get("name")
            if current_name and row_name == current_name:
                continue
            key = (doctype, row_name)
            if key in seen:
                continue
            seen.add(key)
            try:
                doc = frappe.get_doc(doctype, row_name)
                records.append(_build_related_title_record_summary(meta, _safe_json_copy(doc.as_dict())))
            except Exception:
                records.append(
                    {
                        "doctype": doctype,
                        "name": row_name,
                        "label": row.get(fieldname) or row_name,
                        "match_field": fieldname,
                        "match_value": row.get(fieldname),
                        "summary_fields": [
                            {
                                "fieldname": fieldname,
                                "label": fieldname,
                                "fieldtype": meta.get_field(fieldname).fieldtype if meta.get_field(fieldname) else None,
                                "value": _sanitize_value(row.get(fieldname), max_chars=300),
                            }
                        ],
                    }
                )

    return records[:8]


def _build_link_field_index(meta, source_data: Dict[str, Any], source_type: str = "form") -> List[Dict[str, Any]]:
    """Return a lightweight map of link fields without expanding linked records."""
    source_data = source_data or {}
    items: List[Dict[str, Any]] = []

    for field in meta.fields:
        if not _is_link_field(field):
            continue

        resolved_target_doctype = None
        target_doctype_field = None
        source_value = source_data.get(field.fieldname)

        if field.fieldtype == "Link":
            resolved_target_doctype = field.options or None
        elif field.fieldtype == "Dynamic Link":
            target_doctype_field = field.options or None
            resolved_target_doctype = source_data.get(target_doctype_field) if target_doctype_field else None

        items.append(
            {
                "fieldname": field.fieldname,
                "label": field.label or field.fieldname,
                "fieldtype": field.fieldtype,
                "target_doctype": resolved_target_doctype,
                "target_doctype_field": target_doctype_field,
                "source_value": _sanitize_value(source_value, max_chars=200) if source_value not in (None, "") else None,
                "target_label": None,
            }
        )

        if len(items) >= MAX_LINKED_FIELDS * 2:
            break

    for item in items:
        target_doctype = item.get("target_doctype")
        if not target_doctype:
            continue
        try:
            linked_meta = frappe.get_meta(target_doctype)
            item["target_label"] = getattr(linked_meta, "label", None) or target_doctype
        except Exception:
            item["target_label"] = target_doctype

    return items[:MAX_LINKED_FIELDS * 2]


def _select_link_fields_for_question(link_fields: List[Dict[str, Any]], user_question: str) -> List[Dict[str, Any]]:
    if not user_question:
        return []

    selected = []
    for item in link_fields or []:
        candidates = [
            item.get("fieldname"),
            item.get("label"),
            item.get("target_doctype"),
            item.get("target_label"),
        ]
        if any(_text_matches_question(user_question, candidate) for candidate in candidates if candidate):
            selected.append(item)

    return selected[:MAX_LINKED_DOCTYPES]


def _select_child_tables_for_question(meta, user_question: str) -> List[str]:
    if not user_question:
        return []

    selected = []
    for field in getattr(meta, "fields", []):
        if getattr(field, "fieldtype", None) != "Table" or not getattr(field, "fieldname", None):
            continue

        candidates = [
            getattr(field, "fieldname", None),
            getattr(field, "label", None),
            getattr(field, "options", None),
        ]
        if any(_text_matches_question(user_question, candidate) for candidate in candidates if candidate):
            selected.append(field.fieldname)

    return selected[:MAX_CHILD_TABLES]


def _fetch_selected_linked_context(selected_link_fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []

    for item in selected_link_fields or []:
        target_doctype = item.get("target_doctype")
        target_name = item.get("source_value")
        if not target_doctype:
            continue

        if not frappe.has_permission(target_doctype, "read"):
            continue

        entry = {
            "doctype": target_doctype,
            "label": item.get("target_label") or target_doctype,
            "source_field": item.get("fieldname"),
            "source_field_label": item.get("label"),
            "fieldtype": item.get("fieldtype"),
            "record_found": False,
            "linked_record_name": target_name,
            "doctype_meta": None,
            "linked_record_data": None,
        }

        try:
            entry["doctype_meta"] = _summarize_doctype_meta(target_doctype)
        except Exception:
            entry["doctype_meta"] = {
                "doctype": target_doctype,
                "label": target_doctype,
                "field_count": 0,
                "fields": [],
            }

        if target_name:
            try:
                linked_doc = frappe.get_doc(target_doctype, target_name)
                entry["linked_record_data"] = _sanitize_value(linked_doc.as_dict(), max_chars=None)
                entry["record_found"] = True
            except Exception:
                entry["record_found"] = False

        result.append(entry)

    return result


def _collect_linked_context(meta, source_data: Dict[str, Any], user_question: str = "", source_type: str = "form") -> Dict[str, Any]:
    """Collect lightweight link-field metadata and expand only the fields relevant to the question."""
    link_fields = _build_link_field_index(meta, source_data, source_type=source_type)
    selected_link_fields = _select_link_fields_for_question(link_fields, user_question)
    linked_doctypes = _fetch_selected_linked_context(selected_link_fields)

    return {
        "link_fields": link_fields,
        "link_fields_count": len(link_fields),
        "link_fields_truncated": len(link_fields) > MAX_LINKED_FIELDS * 2,
        "selected_link_fields": [
            {
                "fieldname": item.get("fieldname"),
                "label": item.get("label"),
                "fieldtype": item.get("fieldtype"),
                "target_doctype": item.get("target_doctype"),
            }
            for item in selected_link_fields
        ],
        "selected_link_fields_count": len(selected_link_fields),
        "linked_doctypes": linked_doctypes,
        "linked_doctypes_count": len(linked_doctypes),
        "linked_doctypes_truncated": len(selected_link_fields) > len(linked_doctypes),
        "source_type": source_type,
    }


def _get_form_context(payload: Dict[str, Any], user_question: str = "") -> ContextExtractionResult:
    doctype = payload.get("doctype")
    name = payload.get("name") or payload.get("docname")
    if not doctype:
        return ContextExtractionResult(
            ok=False,
            error="No doctype found for the current form view.",
        )

    if not frappe.has_permission(doctype, "read"):
        return ContextExtractionResult(
            ok=False,
            source_type="form",
            source_label=f"{doctype}{' ' + name if name else ''}".strip(),
            error=f"No permission to read {doctype}.",
        )

    try:
        snapshot = payload.get("current_doc")
        if isinstance(snapshot, dict) and snapshot:
            doc_dict = _safe_json_copy(snapshot)
            if name:
                try:
                    doc = frappe.get_doc(doctype, name)
                    merged_doc = _safe_json_copy(doc.as_dict())
                    merged_doc.update(doc_dict)
                    doc_dict = merged_doc
                except Exception:
                    pass
        else:
            doc = frappe.get_doc(doctype, name) if name else frappe.new_doc(doctype)
            doc_dict = doc.as_dict()

        meta = frappe.get_meta(doctype)
        selected_child_tables = _select_child_tables_for_question(meta, user_question)
        serialized = _truncate_child_tables(doc_dict, preferred_tables=selected_child_tables)
        field_summary = []
        for field in meta.fields:
            if field.fieldtype in IGNORED_META_FIELD_TYPES:
                continue
            if not field.fieldname:
                continue
            field_summary.append(
                {
                    "fieldname": field.fieldname,
                    "label": field.label or field.fieldname,
                    "fieldtype": field.fieldtype,
                    "reqd": bool(field.reqd),
                    "read_only": bool(field.read_only),
                    "options": field.options if field.fieldtype in {"Link", "Select", "Table"} else None,
                }
            )

        metadata = {
            "doctype": doctype,
            "name": name,
            "title": (snapshot or {}).get("title") or getattr(locals().get("doc"), "title", None),
            "docstatus": (snapshot or {}).get("docstatus") if isinstance(snapshot, dict) and snapshot and (snapshot or {}).get("docstatus") is not None else getattr(locals().get("doc"), "docstatus", None),
            "is_submittable": bool(meta.is_submittable),
            "route": _get_route_label(payload.get("route")),
            "field_count": len(field_summary),
            "fields": field_summary[:40],
            "truncated_tables": serialized.get("truncated_tables", {}),
        }

        linked_context = _collect_linked_context(meta, serialized["data"], user_question=user_question, source_type="form")
        metadata.update(linked_context)
        metadata.update(_collect_child_table_context(meta, serialized["data"], user_question=user_question, selected_tables=selected_child_tables))
        if selected_child_tables:
            metadata["child_table_focus"] = selected_child_tables

        title_field = _select_title_field(meta, serialized["data"])
        title_value = serialized["data"].get(title_field) if title_field else None
        if title_value and _is_related_title_question(user_question):
            related_targets = [doctype]
            for target_doctype in RELATED_TITLE_TARGETS.get(doctype, ()):
                if target_doctype not in related_targets:
                    related_targets.append(target_doctype)

            related_records = []
            for target_doctype in related_targets:
                related_records.extend(
                    {
                        **record,
                        "source_doctype": target_doctype,
                    }
                    for record in _fetch_related_title_records(
                        target_doctype,
                        title_value,
                        current_name=name if target_doctype == doctype else None,
                    )
                )

            if related_records:
                metadata["related_title_lookup"] = {
                    "field": title_field,
                    "value": _sanitize_value(title_value, max_chars=240),
                    "targets": related_targets,
                    "match_count": len(related_records),
                }
                metadata["related_title_records"] = related_records
                metadata["related_title_records_count"] = len(related_records)
                metadata["related_title_records_truncated"] = len(related_records) >= 8
                metadata["related_title_hint"] = (
                    "Use these exact-title matches from the register before saying nothing was found."
                )

        if isinstance(snapshot, dict) and snapshot:
            metadata["frontend_snapshot_present"] = True
            metadata["frontend_snapshot_dirty"] = bool(payload.get("is_dirty"))
            metadata["frontend_snapshot"] = _sanitize_value(snapshot)

        return ContextExtractionResult(
            ok=True,
            source_type="form",
            source_label=f"{doctype}{' ' + name if name else ''}".strip(),
            metadata=metadata,
            data=serialized["data"],
        )
    except frappe.DoesNotExistError:
        return ContextExtractionResult(
            ok=False,
            source_type="form",
            source_label=f"{doctype}{' ' + name if name else ''}".strip(),
            error=f"{doctype} '{name}' was not found.",
        )
    except Exception as exc:
        frappe.log_error(
            message=f"Context form extraction failed for {doctype}: {exc}\n\n{frappe.get_traceback()}",
            title="Jive Context Extraction",
        )
        return ContextExtractionResult(
            ok=False,
            source_type="form",
            source_label=f"{doctype}{' ' + name if name else ''}".strip(),
            error=str(exc),
        )

def _get_list_fields(doctype: str, requested_fields: Optional[List[str]] = None) -> List[str]:
    meta = frappe.get_meta(doctype)
    allowed = []
    excluded_types = IGNORED_META_FIELD_TYPES | {"Table", "Table MultiSelect"}

    if requested_fields:
        for fieldname in requested_fields:
            field = meta.get_field(fieldname)
            if not field:
                continue
            if field.fieldtype in excluded_types:
                continue
            if field.fieldname and field.fieldname not in allowed:
                allowed.append(field.fieldname)
    else:
        for field in meta.fields:
            if field.fieldtype in excluded_types:
                continue
            if not field.fieldname:
                continue
            if field.fieldname.startswith("_"):
                continue
            if field.fieldname not in allowed:
                allowed.append(field.fieldname)

    if "name" not in allowed:
        allowed.insert(0, "name")

    return allowed[:20]


def _get_list_context(payload: Dict[str, Any], user_question: str = "") -> ContextExtractionResult:
    doctype = payload.get("doctype") or payload.get("source") or payload.get("list_doctype")
    if not doctype:
        return ContextExtractionResult(
            ok=False,
            source_type="list",
            error="Missing list doctype in context payload.",
        )

    try:
        requested_fields = payload.get("fields") or []
        fields = _get_list_fields(doctype, requested_fields=requested_fields)
        limit = min(int(payload.get("limit") or payload.get("page_length") or 20), 50)
        filters = payload.get("filters") or []
        order_by = payload.get("order_by") or payload.get("sort_by") or None
        from ampower_jive.agent.tools import apply_default_filters, sanitize_filters

        filters_with_defaults, order_by = apply_default_filters(doctype, filters, order_by)
        safe_filters = sanitize_filters(filters_with_defaults, doctype)

        rows = frappe.get_list(
            doctype,
            fields=fields,
            filters=safe_filters,
            limit_page_length=limit,
            order_by=order_by,
        )

        meta = frappe.get_meta(doctype)
        metadata = {
            "doctype": doctype,
            "route": _get_route_label(payload.get("route")),
            "filters": _safe_json_copy(filters),
            "resolved_filters": _safe_json_copy(safe_filters),
            "fields": fields,
            "order_by": order_by,
            "page_length": limit,
            "result_count": len(rows),
            "is_submittable": bool(meta.is_submittable),
        }

        first_row = rows[0] if rows else {}
        linked_context = _collect_linked_context(meta, first_row, user_question=user_question, source_type="list")
        metadata.update(linked_context)

        if payload.get("current_filters"):
            metadata["frontend_filters"] = _sanitize_value(payload.get("current_filters"))
        if payload.get("visible_fields"):
            metadata["frontend_visible_fields"] = _sanitize_value(payload.get("visible_fields"))

        return ContextExtractionResult(
            ok=True,
            source_type="list",
            source_label=doctype,
            metadata=metadata,
            data={
                "rows": [_sanitize_value(row) for row in rows],
                "count": len(rows),
                "showing": len(rows),
                "truncated": len(rows) >= limit,
            },
        )
    except Exception as exc:
        frappe.log_error(
            message=f"Context list extraction failed for {doctype}: {exc}\n\n{frappe.get_traceback()}",
            title="Jive Context Extraction",
        )
        return ContextExtractionResult(
            ok=False,
            source_type="list",
            source_label=doctype,
            error=str(exc),
        )


def _get_workspace_context(payload: Dict[str, Any]) -> ContextExtractionResult:
    workspace_name = payload.get("workspace_name") or payload.get("name") or payload.get("workspace")
    if not workspace_name:
        return ContextExtractionResult(
            ok=False,
            error="No workspace name found for the current workspace view.",
        )

    try:
        workspace = frappe.get_doc("Workspace", workspace_name)
        serialized = _truncate_child_tables(workspace.as_dict(), child_limit=12)
        metadata = {
            "workspace_name": workspace_name,
            "title": getattr(workspace, "label", None) or getattr(workspace, "title", None) or workspace_name,
            "route": _get_route_label(payload.get("route")),
            "public": bool(getattr(workspace, "public", 0)),
            "parent_page": getattr(workspace, "parent_page", None),
            "is_hidden": bool(getattr(workspace, "is_hidden", 0)),
            "truncated_tables": serialized.get("truncated_tables", {}),
        }

        return ContextExtractionResult(
            ok=True,
            source_type="workspace",
            source_label=workspace_name,
            metadata=metadata,
            data=serialized["data"],
        )
    except frappe.DoesNotExistError:
        return ContextExtractionResult(
            ok=False,
            source_type="workspace",
            source_label=workspace_name,
            error=f"Workspace '{workspace_name}' was not found.",
        )
    except Exception as exc:
        frappe.log_error(
            message=f"Context workspace extraction failed for {workspace_name}: {exc}\n\n{frappe.get_traceback()}",
            title="Jive Context Extraction",
        )
        return ContextExtractionResult(
            ok=False,
            source_type="workspace",
            source_label=workspace_name,
            error=str(exc),
        )

def _get_page_context(payload: Dict[str, Any]) -> ContextExtractionResult:
    page_name = payload.get("page_name") or payload.get("name") or ""
    if not page_name:
        route = payload.get("route")
        if isinstance(route, list) and len(route) > 0:
            page_name = route[-1]
            
    if not page_name:
        return ContextExtractionResult(
            ok=False,
            error="No page name found for the current page view.",
        )

    try:
        page_doc = frappe.get_doc("Page", page_name)
        page_fields = payload.get("page_fields") or []
        page_field_values = payload.get("page_field_values") or {}
        page_summary_cards = payload.get("page_summary_cards") or []
        page_snapshot = payload.get("page_snapshot") or {}
        page_kind = (payload.get("page_kind") or page_snapshot.get("kind") or "page").lower().strip()
        if page_kind not in {"page", "dashboard", "report"}:
            page_kind = "page"
        metadata = {
            "page_name": page_name,
            "title": getattr(page_doc, "title", None) or page_name,
            "route": _get_route_label(payload.get("route")),
            "module": getattr(page_doc, "module", None),
            "roles": [r.role for r in getattr(page_doc, "roles", [])],
            "page_kind": page_kind,
            "page_field_count": payload.get("page_field_count") or len(page_fields),
            "page_field_value_count": payload.get("page_field_value_count")
            or (len(page_field_values) if isinstance(page_field_values, dict) else 0),
            "page_summary_card_count": payload.get("page_summary_card_count")
            or (len(page_summary_cards) if isinstance(page_summary_cards, list) else 0),
        }

        if page_kind == "report":
            metadata["report_name"] = page_name
            metadata["report_title"] = getattr(page_doc, "title", None) or page_name

        result = ContextExtractionResult(
            ok=True, 
            source_type="page",
            source_label=page_name,
            metadata=metadata,
            data={
                "page_name": page_name,
                "type": "Custom Page",
            "page_fields": page_fields,
            "page_field_values": page_field_values,
            "page_summary_cards": page_summary_cards,
            "page_snapshot": page_snapshot,
        },
    )
        return result
    except frappe.DoesNotExistError:
        result = ContextExtractionResult(
            ok=False,
            source_type="page",
            source_label=page_name,
            error=f"Page '{page_name}' was not found.",
        )
        return result
    except Exception as exc:
        frappe.log_error(
            message=f"Context page extraction failed for {page_name}: {exc}\n\n{frappe.get_traceback()}",
            title="Jive Context Extraction",
        )
        return ContextExtractionResult(
            ok=False,
            source_type="page",
            source_label=page_name,
            error=str(exc),
        )


def _get_dashboard_context(payload: Dict[str, Any]) -> ContextExtractionResult:
    dashboard_name = (
        payload.get("doctype")
        or payload.get("dashboard_name")
        or payload.get("page_name")
        or payload.get("name")
        or ""
    )
    if not dashboard_name:
        route = payload.get("route")
        if isinstance(route, list) and len(route) > 1:
            dashboard_name = route[1]
        elif isinstance(route, list) and len(route) > 0:
            dashboard_name = route[-1]

    if not dashboard_name:
        return ContextExtractionResult(
            ok=False,
            source_type="dashboard",
            error="No dashboard name found for the current dashboard view.",
        )

    dashboard_snapshot = payload.get("dashboard_snapshot") or payload.get("page_snapshot") or {}
    page_fields = payload.get("page_fields") or []
    page_field_values = payload.get("page_field_values") or {}
    page_summary_cards = payload.get("page_summary_cards") or payload.get("summary_cards") or []
    page_kind = (payload.get("page_kind") or dashboard_snapshot.get("kind") or "dashboard").lower().strip()
    metadata = {
        "dashboard_name": dashboard_name,
        "title": payload.get("label") or dashboard_name,
        "route": _get_route_label(payload.get("route")),
        "page_kind": "dashboard",
        "page_field_count": payload.get("page_field_count") or len(page_fields),
        "page_field_value_count": payload.get("page_field_value_count")
        or (len(page_field_values) if isinstance(page_field_values, dict) else 0),
        "page_summary_card_count": payload.get("page_summary_card_count")
        or (len(page_summary_cards) if isinstance(page_summary_cards, list) else 0),
        "dashboard_snapshot_source": dashboard_snapshot.get("source"),
        "dashboard_snapshot_kind": dashboard_snapshot.get("kind") or page_kind,
    }

    result = ContextExtractionResult(
        ok=True,
        source_type="dashboard",
        source_label=dashboard_name,
        metadata=metadata,
        data={
            "dashboard_name": dashboard_name,
            "dashboard_snapshot": dashboard_snapshot,
            "page_fields": page_fields,
            "page_field_values": page_field_values,
            "page_summary_cards": page_summary_cards,
            "page_snapshot": dashboard_snapshot,
        },
    )
    return result

class ContextExtractorFactory:
    """Resolve a payload into a source-specific extractor."""

    def extract(self, payload: Dict[str, Any], user_question: str = "") -> ContextExtractionResult:
        payload = payload or {}
        source_type = (payload.get("source_type") or "").lower().strip()
        route_source_type = _route_to_source_type(payload.get("route"))
        source_type = source_type or route_source_type
        page_snapshot = payload.get("page_snapshot")
        page_kind = (payload.get("page_kind") or (page_snapshot.get("kind") if isinstance(page_snapshot, dict) else "") or "").lower().strip()
        has_dashboard_snapshot = isinstance(payload.get("dashboard_snapshot"), dict)

        if source_type == "form":
            return _get_form_context(payload, user_question=user_question)
        if source_type == "list":
            return _get_list_context(payload, user_question=user_question)
        if source_type == "workspace":
            return _get_workspace_context(payload)
        if source_type == "page" and (page_kind == "dashboard" or has_dashboard_snapshot):
            return _get_dashboard_context(payload)
        if source_type == "page":
            return _get_page_context(payload)
        if source_type == "dashboard":
            return _get_dashboard_context(payload)

        if payload.get("doctype") and payload.get("name"):
            return _get_form_context(payload, user_question=user_question)
        if payload.get("doctype") and payload.get("filters") is not None:
            return _get_list_context(payload, user_question=user_question)

        return ContextExtractionResult(
            ok=False,
            source_type=source_type or "unknown",
            source_label=_get_route_label(payload.get("route")) or "current view",
            error="Unsupported or missing view context.",
        )


def _compact_json(value: Any, limit: Optional[int] = None) -> str:
    """Serialize a value to compact JSON, optionally truncating the text."""
    try:
        text = json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(value)

    if limit is not None and len(text) > limit:
        return text[:limit] + "\n... [context truncated]"
    return text


def _estimate_token_count(text: str) -> int:
    """Estimate token count without external tokenizer dependencies."""
    if not text:
        return 0

    chunks = re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)
    return max(len(chunks), (len(text) + 3) // 4)


class ContextPromptBuilder:
    """Build the system prompt used by Context Aware Mode."""

    def __init__(self, prompt_provider=None):
        self.prompt_provider = prompt_provider or get_prompt_provider()

    def get_template(self) -> str:
        prompt = self.prompt_provider.get_prompt("context")
        return (prompt or DEFAULT_CONTEXT_PROMPT).strip()

    def build(
        self,
        context: ContextExtractionResult,
        user_question: str,
        history: Optional[List[Dict[str, str]]] = None,
        max_tokens: Optional[int] = None,
        include_recent_history: bool = False,
        aggressive: bool = False,
    ) -> str:
        template = self.get_template()
        payload = self._build_prompt_payload(context, user_question, aggressive=aggressive)

        context_json = _compact_json(payload["context"], limit=payload["context_limit"])
        metadata_json = _compact_json(payload["metadata"], limit=payload["metadata_limit"])
        rendered = _render_prompt_template(
            template,
            {
                "context_json": context_json,
                "metadata_json": metadata_json,
                "user_question": user_question or "",
            },
        )

        rendered = self._append_page_guidance(rendered, context, payload)

        if include_recent_history:
            recent_history = self._build_recent_history_block(history)
            if recent_history:
                rendered += "\n\n=== RECENT CONVERSATION ===\n" + recent_history

        if payload["budget_notes"]:
            rendered += "\n\n=== CONTEXT TRIMMING ===\n" + "\n".join(f"- {note}" for note in payload["budget_notes"])

        rendered = self._append_child_table_guidance(rendered, payload["metadata"])
        rendered = append_followup_prompt(rendered)

        if max_tokens is not None:
            estimated = _estimate_token_count(rendered)
            if estimated > max_tokens and not aggressive:
                return self.build(
                    context=context,
                    user_question=user_question,
                    history=history,
                    max_tokens=max_tokens,
                    include_recent_history=include_recent_history,
                    aggressive=True,
                )
            if estimated > max_tokens:
                source_label = context.source_label or payload["metadata"].get("doctype", "")
                raise ContextBudgetExceededError(max_tokens, estimated, source_label)

        return rendered

    def _build_prompt_payload(
        self,
        context: ContextExtractionResult,
        user_question: str,
        aggressive: bool = False,
    ) -> Dict[str, Any]:
        source_type = (context.source_type or context.metadata.get("source_type") or "").lower().strip()
        data = _safe_json_copy(context.data or {})
        metadata = _safe_json_copy(context.metadata or {})
        notes: List[str] = []

        for key in ("frontend_snapshot", "frontend_snapshot_present", "frontend_snapshot_dirty"):
            metadata.pop(key, None)

        if source_type == "form":
            data, metadata, extra_notes = self._build_form_payload(data, metadata, user_question, aggressive=aggressive)
            notes.extend(extra_notes)
        elif source_type == "list":
            data, metadata, extra_notes = self._build_list_payload(data, metadata, user_question, aggressive=aggressive)
            notes.extend(extra_notes)
        elif source_type == "workspace":
            data, metadata, extra_notes = self._build_workspace_payload(data, metadata, aggressive=aggressive)
            notes.extend(extra_notes)
        elif source_type in {"page", "dashboard"}:
            data, metadata, extra_notes = self._build_page_payload(data, metadata, aggressive=aggressive)
            notes.extend(extra_notes)
        else:
            data = self._compact_generic_value(data, aggressive=aggressive)
            metadata = self._compact_generic_value(metadata, aggressive=aggressive)

        return {
            "context": data,
            "metadata": metadata,
            "context_limit": MAX_CONTEXT_JSON_CHARS if not aggressive else max(4000, MAX_CONTEXT_JSON_CHARS // 2),
            "metadata_limit": MAX_METADATA_JSON_CHARS if not aggressive else max(3000, MAX_METADATA_JSON_CHARS // 2),
            "budget_notes": notes,
        }

    def _build_form_payload(
        self,
        data: Dict[str, Any],
        metadata: Dict[str, Any],
        user_question: str,
        aggressive: bool = False,
    ):
        notes: List[str] = []
        fields = metadata.get("fields") or []
        selected_fields = self._select_relevant_fields(fields, data, user_question, limit=12 if aggressive else 16)
        result: Dict[str, Any] = {}

        for fieldname in selected_fields:
            value = data.get(fieldname)
            if isinstance(value, list):
                continue
            result[fieldname] = self._sanitize_prompt_value(value, max_chars=160 if aggressive else 240)

        child_tables = self._select_relevant_child_tables(metadata, user_question, limit=2 if aggressive else 3)
        if not child_tables and metadata.get("child_tables"):
            child_tables = (metadata.get("child_tables") or [])[:1]

        selected_child_names = set()
        for table in child_tables:
            fieldname = table.get("fieldname")
            if not fieldname:
                continue
            selected_child_names.add(fieldname)
            rows = data.get(fieldname)
            if not isinstance(rows, list):
                continue

            child_fields = [item.get("fieldname") for item in (table.get("fields") or []) if item.get("fieldname")]
            if not child_fields and rows:
                child_fields = list(rows[0].keys())

            full_rows = not aggressive and fieldname in selected_child_names
            result[fieldname] = {
                "fieldname": fieldname,
                "label": table.get("label") or fieldname,
                "child_doctype": table.get("child_doctype"),
                "row_count": len(rows),
                "rows": self._trim_rows(rows, child_fields[: (4 if aggressive else 6)], max_rows=len(rows) if full_rows else (2 if aggressive else 4)),
                "row_mode": "full" if full_rows else "sample",
            }

        # Keep only relevant child-table metadata and trim linked doctypes to the selected fields.
        metadata["fields"] = [item for item in fields if item.get("fieldname") in selected_fields][:12 if aggressive else 16]
        metadata["selected_fields"] = selected_fields
        metadata["child_tables"] = child_tables
        metadata["child_tables_count"] = len(child_tables)
        metadata["child_table_index"] = [item for item in (metadata.get("child_table_index") or []) if item.get("fieldname") in selected_child_names][:3 if aggressive else 5]

        selected_link_fields = metadata.get("selected_link_fields") or []
        selected_link_names = {item.get("fieldname") for item in selected_link_fields if item.get("fieldname")}
        if selected_link_names:
            metadata["link_fields"] = [item for item in (metadata.get("link_fields") or []) if item.get("fieldname") in selected_link_names][:4]
            metadata["linked_doctypes"] = [self._summarize_linked_entry(item) for item in (metadata.get("linked_doctypes") or []) if item.get("source_field") in selected_link_names][:4]
        else:
            metadata["link_fields"] = (metadata.get("link_fields") or [])[:2]
            metadata["linked_doctypes"] = [self._summarize_linked_entry(item) for item in (metadata.get("linked_doctypes") or [])[:2]]

        dropped = sorted(set(data.keys()) - set(result.keys()))
        if dropped:
            notes.append("Dropped low-signal fields: " + ", ".join(dropped[:8]))
        if selected_child_names:
            notes.append("Preserved explicitly selected child tables: " + ", ".join(sorted(selected_child_names)))

        return result, metadata, notes

    def _build_list_payload(
        self,
        data: Dict[str, Any],
        metadata: Dict[str, Any],
        user_question: str,
        aggressive: bool = False,
    ):
        notes: List[str] = []
        rows = data.get("rows") or []
        available_fields = metadata.get("visible_fields") or metadata.get("fields") or []
        if available_fields and isinstance(available_fields[0], dict):
            available_fields = [item.get("fieldname") for item in available_fields if item.get("fieldname")]

        selected_fields = self._select_list_fields(available_fields, user_question, limit=8 if aggressive else 12)
        trimmed_rows = self._trim_rows(rows, selected_fields, max_rows=6 if aggressive else 8)

        metadata["selected_fields"] = selected_fields
        metadata["fields"] = selected_fields[:8 if aggressive else 12]
        metadata["link_fields"] = (metadata.get("link_fields") or [])[:4 if aggressive else 6]
        metadata["linked_doctypes"] = [self._summarize_linked_entry(item) for item in (metadata.get("linked_doctypes") or [])[:3 if aggressive else 5]]
        if metadata.get("frontend_visible_fields"):
            metadata["frontend_visible_fields"] = metadata.get("frontend_visible_fields")[:8 if aggressive else 12]

        if len(rows) > len(trimmed_rows):
            notes.append("Trimmed list rows to a compact sample while preserving the visible columns.")

        return {
            "count": data.get("count", len(rows)),
            "showing": len(trimmed_rows),
            "truncated": len(rows) > len(trimmed_rows),
            "rows": trimmed_rows,
        }, metadata, notes

    def _build_workspace_payload(self, data: Dict[str, Any], metadata: Dict[str, Any], aggressive: bool = False):
        notes: List[str] = []
        result = {}
        for key, value in data.items():
            if key in INTERNAL_DOC_KEYS:
                continue
            if isinstance(value, list):
                if value and isinstance(value[0], dict):
                    result[key] = {
                        "row_count": len(value),
                        "sample_rows": self._trim_rows(value, list(value[0].keys())[:6], max_rows=2 if aggressive else 4),
                    }
                else:
                    result[key] = {"row_count": len(value), "sample": value[:3]}
            elif isinstance(value, dict):
                result[key] = self._sanitize_prompt_value(value, max_chars=160 if aggressive else 240)
            else:
                result[key] = self._sanitize_prompt_value(value, max_chars=120 if aggressive else 200)

        metadata["fields"] = (metadata.get("fields") or [])[:8 if aggressive else 12]
        metadata["link_fields"] = (metadata.get("link_fields") or [])[:2]
        metadata["linked_doctypes"] = [self._summarize_linked_entry(item) for item in (metadata.get("linked_doctypes") or [])[:2]]
        if len(result) < len(data):
            notes.append("Trimmed workspace data to summary values.")
        return result, metadata, notes

    def _build_page_payload(self, data: Dict[str, Any], metadata: Dict[str, Any], aggressive: bool = False):
        notes: List[str] = []
        page_kind = (metadata.get("page_kind") or data.get("page_kind") or "page").lower().strip()
        snapshot = data.get("page_snapshot") or data.get("dashboard_snapshot") or {}
        result: Dict[str, Any] = {}

        if page_kind == "dashboard":
            result["page_snapshot"] = self._compact_dashboard_snapshot(snapshot or data, aggressive=aggressive)
            if data.get("dashboard_snapshot") is not None:
                result["dashboard_snapshot"] = self._compact_dashboard_snapshot(data.get("dashboard_snapshot"), aggressive=aggressive)
        elif snapshot:
            result["page_snapshot"] = self._compact_page_snapshot(snapshot, aggressive=aggressive)

        if data.get("page_fields"):
            result["page_fields"] = self._sanitize_prompt_value(data.get("page_fields"), max_chars=160 if aggressive else 240)
        if data.get("page_field_values"):
            result["page_field_values"] = self._compact_generic_value(data.get("page_field_values"), aggressive=aggressive)
        summary_cards = data.get("page_summary_cards") or data.get("summary_cards")
        if summary_cards:
            result["summary_cards"] = self._sanitize_prompt_value(summary_cards, max_chars=160 if aggressive else 260)
        visible_text = data.get("visible_text")
        if not visible_text and isinstance(snapshot, dict):
            visible_text = snapshot.get("visible_text")
        if visible_text:
            result["visible_text"] = self._compact_visible_text(visible_text, aggressive=aggressive)
        if data.get("charts"):
            result["charts"] = self._compact_dashboard_charts(data.get("charts"), aggressive=aggressive)

        # Keep a few plain page values for simple questions and debugging.
        for key in ("page_name", "type", "title", "label", "page_kind", "page_source"):
            if key in data and data.get(key) is not None:
                result[key] = self._sanitize_prompt_value(data.get(key), max_chars=120 if aggressive else 240)

        metadata["page_kind"] = page_kind
        metadata["fields"] = (metadata.get("fields") or [])[:8 if aggressive else 12]
        if len(result) < len(data):
            notes.append("Trimmed page context to the visible dashboard/page snapshot.")

        return result, metadata, notes

    def _compact_page_snapshot(self, snapshot: Any, aggressive: bool = False):
        if not isinstance(snapshot, dict):
            return self._compact_generic_value(snapshot, aggressive=aggressive)

        result: Dict[str, Any] = {}
        for key in ("kind", "source", "page_name", "title", "page_kind", "page_source"):
            if snapshot.get(key) is not None:
                result[key] = self._sanitize_prompt_value(snapshot.get(key), max_chars=120 if aggressive else 200)

        if snapshot.get("filters") is not None:
            result["filters"] = self._sanitize_prompt_value(snapshot.get("filters"), max_chars=120 if aggressive else 200)
        if snapshot.get("controls") is not None:
            result["controls"] = self._sanitize_prompt_value(snapshot.get("controls"), max_chars=140 if aggressive else 220)
        if snapshot.get("visible_text") is not None:
            result["visible_text"] = self._compact_visible_text(snapshot.get("visible_text"), aggressive=aggressive)
        if snapshot.get("charts") is not None:
            result["charts"] = self._compact_dashboard_charts(snapshot.get("charts"), aggressive=aggressive)
        if snapshot.get("summary_cards") is not None:
            result["summary_cards"] = self._sanitize_prompt_value(snapshot.get("summary_cards"), max_chars=160 if aggressive else 260)

        for key in ("kpis", "summary", "metrics", "lastData", "dashboard_data", "data", "page_field_values", "number_cards"):
            if snapshot.get(key) is not None:
                result[key] = self._compact_generic_value(snapshot.get(key), aggressive=aggressive)

        return result

    def _compact_dashboard_snapshot(self, snapshot: Any, aggressive: bool = False):
        if not isinstance(snapshot, dict):
            return self._compact_generic_value(snapshot, aggressive=aggressive)

        result: Dict[str, Any] = {}
        for key in ("kind", "source", "page_name", "title", "page_kind", "page_source"):
            if snapshot.get(key) is not None:
                result[key] = self._sanitize_prompt_value(snapshot.get(key), max_chars=120 if aggressive else 200)

        if snapshot.get("filters") is not None:
            result["filters"] = self._sanitize_prompt_value(snapshot.get("filters"), max_chars=120 if aggressive else 200)
        if snapshot.get("controls") is not None:
            result["controls"] = self._sanitize_prompt_value(snapshot.get("controls"), max_chars=140 if aggressive else 220)
        if snapshot.get("visible_text") is not None:
            result["visible_text"] = self._sanitize_prompt_value(snapshot.get("visible_text"), max_chars=120 if aggressive else 200)
        if snapshot.get("charts") is not None:
            result["charts"] = self._compact_dashboard_charts(snapshot.get("charts"), aggressive=aggressive)
        if snapshot.get("summary_cards") is not None:
            result["summary_cards"] = self._sanitize_prompt_value(snapshot.get("summary_cards"), max_chars=160 if aggressive else 260)

        for key in ("kpis", "summary", "metrics", "lastData", "dashboard_data", "data", "page_field_values", "number_cards"):
            if snapshot.get(key) is not None:
                result[key] = self._compact_generic_value(snapshot.get(key), aggressive=aggressive)

        return result

    def _compact_dashboard_charts(self, charts: Any, aggressive: bool = False):
        if isinstance(charts, dict):
            items = []
            for key, value in charts.items():
                items.append({"name": key, "summary": self._summarize_chart_value(value, key, aggressive=aggressive)})
            return items[:6 if aggressive else 10]

        if isinstance(charts, list):
            items = []
            for idx, value in enumerate(charts[:6 if aggressive else 10]):
                label = value.get("label") if isinstance(value, dict) else f"chart_{idx}"
                items.append({"name": label or f"chart_{idx}", "summary": self._summarize_chart_value(value, label, aggressive=aggressive)})
            return items

        return self._compact_generic_value(charts, aggressive=aggressive)

    def _summarize_chart_value(self, value: Any, label: str = "", aggressive: bool = False):
        if hasattr(value, "getOption") and callable(getattr(value, "getOption", None)):
            try:
                return self._summarize_echarts_option(value.getOption(), label=label, aggressive=aggressive)
            except Exception:
                return {"label": label, "engine": "echarts", "error": "Unable to read chart option"}

        if isinstance(value, dict):
            if isinstance(value.get("data"), dict):
                data = value.get("data") or {}
                summary = {
                    "label": label,
                    "keys": sorted(list(value.keys()))[:10],
                }
                if isinstance(data.get("labels"), list):
                    summary["labels"] = data.get("labels")[:8 if aggressive else 12]
                if isinstance(data.get("datasets"), list):
                    summary["datasets"] = [
                        {
                            "name": ds.get("name") or ds.get("label") or "",
                            "values": (ds.get("values") or [])[:6 if aggressive else 10],
                        }
                        for ds in data.get("datasets")[:4 if aggressive else 6]
                        if isinstance(ds, dict)
                    ]
                return summary

            return self._compact_generic_value(value, aggressive=aggressive)

        if isinstance(value, list):
            return self._sanitize_prompt_value(value[:6 if aggressive else 10], max_chars=120 if aggressive else 200)

        return self._sanitize_prompt_value(value, max_chars=120 if aggressive else 200)

    def _summarize_echarts_option(self, option: Dict[str, Any], label: str = "", aggressive: bool = False):
        if not isinstance(option, dict):
            return {}
        result: Dict[str, Any] = {"label": label, "engine": "echarts"}
        title = option.get("title")
        if isinstance(title, list):
            result["title"] = [item.get("text") for item in title if isinstance(item, dict) and item.get("text")][:3]
        elif isinstance(title, dict):
            if title.get("text"):
                result["title"] = title.get("text")
        if isinstance(option.get("legend"), list):
            result["legend_count"] = len(option.get("legend") or [])
        elif option.get("legend") is not None:
            result["legend"] = True

        series = option.get("series") or []
        if isinstance(series, list):
            result["series"] = []
            for item in series[:4 if aggressive else 6]:
                if not isinstance(item, dict):
                    continue
                data = item.get("data") or []
                summary = {
                    "name": item.get("name") or "",
                    "type": item.get("type") or "",
                    "points": len(data) if isinstance(data, list) else 0,
                }
                if isinstance(data, list):
                    summary["sample"] = [self._sanitize_prompt_value(v, max_chars=80) for v in data[:4 if aggressive else 6]]
                result["series"].append(summary)
        return result

    def _select_relevant_fields(self, fields: List[Dict[str, Any]], source_data: Dict[str, Any], question: str, limit: int = 16) -> List[str]:
        selected: List[str] = []
        seen = set()

        priority = [
            "name", "title", "subject", "status", "docstatus",
            "customer", "customer_name", "supplier", "supplier_name",
            "party_name", "item_code", "item_name", "posting_date",
            "transaction_date", "due_date", "creation", "modified",
            "grand_total", "amount", "outstanding_amount", "qty",
            "rate", "warehouse", "description", "remarks", "comments",
        ]

        def add(fieldname: Optional[str]):
            if not fieldname or fieldname in seen:
                return
            if fieldname in source_data:
                selected.append(fieldname)
                seen.add(fieldname)

        for fieldname in priority:
            add(fieldname)
            if len(selected) >= limit:
                return selected

        for info in fields or []:
            fieldname = info.get("fieldname")
            if not fieldname or fieldname in seen:
                continue
            candidates = [fieldname, info.get("label"), info.get("fieldtype"), info.get("options")]
            if any(_text_matches_question(question, cand) for cand in candidates if cand):
                add(fieldname)
            if len(selected) >= limit:
                return selected

        for info in fields or []:
            fieldname = info.get("fieldname")
            if not fieldname or fieldname in seen:
                continue
            if info.get("fieldtype") in {"Link", "Select", "Date", "Datetime", "Check", "Int", "Float", "Currency"}:
                add(fieldname)
            if len(selected) >= limit:
                return selected

        for info in fields or []:
            fieldname = info.get("fieldname")
            if not fieldname or fieldname in seen:
                continue
            add(fieldname)
            if len(selected) >= limit:
                return selected

        return selected

    def _select_relevant_child_tables(self, metadata: Dict[str, Any], question: str, limit: int = 3) -> List[Dict[str, Any]]:
        child_tables = metadata.get("child_tables") or []
        index = metadata.get("child_table_index") or []
        ranked = []

        for item in index:
            score = 0
            fieldname = item.get("fieldname")
            label = item.get("label")
            child_doctype = item.get("child_doctype")
            row_count = int(item.get("row_count") or 0)

            for candidate in (fieldname, label, child_doctype):
                if candidate and _text_matches_question(question, candidate):
                    score += 100

            if fieldname in {"items", "item", "lines", "details", "rows"}:
                score += 20
            if row_count and row_count <= 5:
                score += 10
            elif row_count > 20:
                score -= 5

            ranked.append((score, fieldname))

        selected_names = [name for _, name in sorted(ranked, key=lambda item: item[0], reverse=True) if name][:limit]
        selected_set = set(selected_names)
        return [item for item in child_tables if item.get("fieldname") in selected_set]

    def _select_list_fields(self, available_fields: List[str], question: str, limit: int = 12) -> List[str]:
        selected: List[str] = []
        seen = set()
        priority = ["name", "title", "subject", "status", "posting_date", "transaction_date", "customer", "supplier", "item_code", "item_name", "grand_total", "amount", "qty", "rate", "warehouse", "company"]

        for fieldname in priority:
            if fieldname in available_fields and fieldname not in seen:
                selected.append(fieldname)
                seen.add(fieldname)

        for fieldname in available_fields:
            if fieldname in seen:
                continue
            if _text_matches_question(question, fieldname):
                selected.append(fieldname)
                seen.add(fieldname)

        for fieldname in available_fields:
            if fieldname in seen:
                continue
            selected.append(fieldname)
            seen.add(fieldname)
            if len(selected) >= limit:
                break

        return selected[:limit]

    def _trim_rows(self, rows: List[Dict[str, Any]], fields: List[str], max_rows: int = 8) -> List[Dict[str, Any]]:
        trimmed = []
        for row in (rows or [])[:max_rows]:
            if not isinstance(row, dict):
                continue
            if fields:
                trimmed.append({field: self._sanitize_prompt_value(row.get(field), max_chars=180) for field in fields if row.get(field) is not None})
            else:
                trimmed.append({key: self._sanitize_prompt_value(value, max_chars=180) for key, value in row.items() if value is not None})
        return trimmed

    def _sanitize_prompt_value(self, value: Any, max_chars: Optional[int] = None) -> Any:
        if isinstance(value, str):
            if max_chars is not None and len(value) > max_chars:
                return value[:max_chars] + "\n... [truncated]"
            return value
        if isinstance(value, dict):
            return {k: self._sanitize_prompt_value(v, max_chars=max_chars) for k, v in value.items() if not str(k).startswith("_")}
        if isinstance(value, list):
            return [self._sanitize_prompt_value(v, max_chars=max_chars) for v in value[:5]]
        return _safe_json_copy(value)

    def _compact_visible_text(self, value: Any, aggressive: bool = False) -> Any:
        if isinstance(value, str):
            return self._sanitize_prompt_value(value, max_chars=None)

        if not isinstance(value, list):
            return self._compact_generic_value(value, aggressive=aggressive)

        def _extract_text(item: Any) -> str:
            if isinstance(item, str):
                return item.strip()
            if isinstance(item, dict):
                for key in ("text", "label", "value", "title", "content", "message", "name", "description", "summary"):
                    candidate = item.get(key)
                    if candidate not in (None, ""):
                        return str(candidate).strip()
                return json.dumps(item, default=str, ensure_ascii=False)
            return str(item).strip()

        def _score_text(text: str) -> int:
            lower = text.lower()
            score = 0
            if not text:
                return score
            if "dead stock" in lower:
                score += 120
            for term in ("kpi", "alert", "recommend", "inventory", "sales", "purchase", "revenue", "summary"):
                if term in lower:
                    score += 12
            if "%" in text:
                score += 40
            if re.search(r"₹|\$|€|£", text):
                score += 35
            if re.search(r"\b\d+(?:\.\d+)?\b", text):
                score += 25
            if "zero" in lower or "no " in lower:
                score += 10
            if len(text) <= 90:
                score += 8
            return score

        ranked = []
        seen = set()
        for idx, item in enumerate(value):
            text = _extract_text(item)
            if not text:
                continue
            normalized = re.sub(r"\s+", " ", text).strip()
            if not normalized:
                continue
            dedupe_key = normalized.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            ranked.append((_score_text(normalized), idx, normalized))

        if not ranked:
            return []

        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = []
        selected_keys = set()

        for score, idx, text in ranked:
            if text.lower() in selected_keys:
                continue
            selected.append(self._sanitize_prompt_value(text, max_chars=None))
            selected_keys.add(text.lower())

        return selected

    @staticmethod
    def _append_page_guidance(rendered: str, context: ContextExtractionResult, payload: Dict[str, Any]) -> str:
        source_type = (context.source_type or payload.get("metadata", {}).get("source_type") or "").lower().strip()
        if source_type not in {"page", "dashboard"}:
            return rendered

        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        page_kind = (metadata or {}).get("page_kind") or (context.metadata or {}).get("page_kind") or ""
        page_kind = str(page_kind).lower().strip()

        lines = [
            "",
            "=== PAGE ANSWER RULES ===",
            "Use the page snapshot as the source of truth for analytics pages.",
            "If a KPI label, percentage, amount, alert, or recommendation is visible anywhere in the page snapshot, answer from that exact text.",
            "Do not ask for more data when the page already shows the metric value.",
            "Prefer visible_text, summary_cards, controls, and page field values over inference.",
        ]

        if page_kind == "report":
            lines.extend(
                [
                    "This is a report page, not a physical database table.",
                    "Do not turn the report title into a SQL table name unless the table can be verified from the context.",
                    "If SQL is needed, prefer the underlying DocType name or an explicitly linked doctype from the context.",
                ]
            )
        return rendered + "\n" + "\n".join(lines)

    def _compact_generic_value(self, value: Any, aggressive: bool = False) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in INTERNAL_DOC_KEYS:
                    continue
                result[key] = self._compact_generic_value(item, aggressive=aggressive)
            return result
        if isinstance(value, list):
            limit = 3 if aggressive else 5
            return [self._compact_generic_value(item, aggressive=aggressive) for item in value[:limit]]
        return self._sanitize_prompt_value(value, max_chars=120 if aggressive else 240)

    def _summarize_linked_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(entry, dict):
            return {}

        record = entry.get("linked_record_data")
        if isinstance(record, dict):
            priority = [
                "name", "title", "subject", "status", "customer_name",
                "item_name", "posting_date", "transaction_date", "grand_total",
                "amount", "qty", "rate", "warehouse", "description", "remarks",
            ]
            summary = {}
            seen = set()
            for key in priority + list(record.keys()):
                if key in seen or key not in record:
                    continue
                seen.add(key)
                summary[key] = self._sanitize_prompt_value(record.get(key), max_chars=120)
                if len(summary) >= 8:
                    break
            entry = dict(entry)
            entry["linked_record_data"] = summary

        meta = entry.get("doctype_meta")
        if isinstance(meta, dict) and isinstance(meta.get("fields"), list):
            entry = dict(entry)
            entry["doctype_meta"] = {**meta, "fields": meta.get("fields", [])[:8]}
        return entry

    def _build_recent_history_block(self, history: Optional[List[Dict[str, str]]] = None) -> str:
        recent = []
        for msg in (history or [])[-3:]:
            role = (msg.get("role") or "user").lower()
            content = strip_followup_block(msg.get("content") or "").strip()
            if not content:
                continue
            recent.append(f"{role}: {content[:500]}")
        return "\n".join(recent)

    @staticmethod
    def _append_child_table_guidance(rendered: str, metadata: Dict[str, Any]) -> str:
        child_tables = metadata.get("child_tables") if isinstance(metadata, dict) else []
        if not child_tables:
            return rendered

        lines = [
            "",
            "=== CHILD TABLE GUIDANCE ===",
            "The context includes only the relevant child-table rows needed for this answer.",
            "Do not answer that rows are missing when the table data is present.",
        ]
        for table in child_tables:
            lines.append(
                f"- {table.get('fieldname')} ({table.get('label') or table.get('fieldname')}) -> child doctype: {table.get('child_doctype') or 'unknown'}, rows: {table.get('row_count', 0)}"
            )
        return rendered + "\n" + "\n".join(lines)



class ContextAwareModeService:
    """Orchestrates context extraction, prompt building, and response generation."""

    def __init__(self):
        self.config_provider = get_config_provider()
        self.prompt_builder = ContextPromptBuilder()
        self.extraction_factory = ContextExtractorFactory()
        self._graph = None

    def _build_llm(self, session_id: str = None):
        settings = self.config_provider.get_model_settings("data_query") or {}
        model = settings.get("model") or "gpt-4o-mini"
        temperature = settings.get("temperature", 0.2)
        timeout = 30

        # Keep context-aware queries in the same accounting bucket as query mode.
        # The prompt itself is still context-aware, but usage should remain visible
        # alongside normal data-query requests.
        llm = get_cached_llm(
            purpose="data_query",
            model=model,
            temperature=temperature,
            timeout=timeout,
            callbacks=[TokenUsageCallbackHandler("data_query", session_id=session_id)],
        )

        if not llm:
            return None, model, temperature

        return llm, model, temperature

    def _get_max_context_tokens(self) -> int:
        config = self.config_provider.get_local_config()
        try:
            value = int(config.get("max_context_tokens") if config else DEFAULT_MAX_CONTEXT_TOKENS)
        except Exception:
            value = DEFAULT_MAX_CONTEXT_TOKENS
        return max(1000, value or DEFAULT_MAX_CONTEXT_TOKENS)

    def process(
        self,
        message: str,
        history: List[Dict[str, str]] = None,
        allowed_doctypes: List[str] = None,
        context_payload: Any = None,
        session_id: str = None,
    ) -> str:
        """Generate a response using the current view context."""
        try:
            graph = self._get_graph()
            history = history or []
            payload = self._normalize_payload(context_payload)

            result = graph.invoke(
                {
                    "message": message,
                    "history": history,
                    "allowed_doctypes": allowed_doctypes or [],
                    "context_payload": payload,
                    "session_id": session_id,
                }
            )

            response_text = result.get("response") if isinstance(result, dict) else ""
            if response_text:
                return response_text
            return self._context_error_message(
                ContextExtractionResult(
                    ok=False,
                    error="I could not generate a response from the current context.",
                )
            )

        except ContextBudgetExceededError as exc:
            return str(exc) + " Please narrow the page context or ask about a specific field or table."
        except Exception as exc:
            traceback_str = frappe.get_traceback()
            frappe.log_error("Context Aware Query Error", traceback_str)
            return f"I encountered an error while reading the current context: {exc}"

    def _get_graph(self):
        if self._graph is not None:
            return self._graph

        workflow = StateGraph(ContextAwareGraphState)
        workflow.add_node("extract_context", self._extract_context_node)
        workflow.add_node("generate_response", self._generate_response_node)
        workflow.add_edge(START, "extract_context")
        workflow.add_conditional_edges(
            "extract_context",
            self._route_after_extraction,
            {
                "generate_response": "generate_response",
                "end": END,
            },
        )
        workflow.add_edge("generate_response", END)
        self._graph = workflow.compile()
        return self._graph

    def _extract_context_node(self, state: "ContextAwareGraphState") -> Dict[str, Any]:
        from ampower_jive.utils.interaction_logger import InteractionLogger

        logger = InteractionLogger("data_query")
        message = state.get("message", "")
        payload = self._normalize_payload(state.get("context_payload"))

        # Context Aware Mode is intentionally not limited by the Jive Config
        # doctype allowlist. Runtime read permissions are enforced inside each
        # extractor before returning any data.
        context = self.extraction_factory.extract(payload, user_question=message)

        state_update: Dict[str, Any] = {
            "context": context.to_dict(),
            "context_ok": context.ok,
            "context_error": context.error,
        }

        if not context.ok:
            state_update["response"] = self._context_error_message(context)
            try:
                logger.log(
                    status="error",
                    error=context.error or "Context extraction failed",
                    request_data={
                        "message": message,
                        "mode": "context",
                        "context_payload": _safe_json_copy(payload),
                        "context": context.to_dict(),
                    },
                    session_id=state.get("session_id"),
                )
            except Exception:
                pass

        return state_update

    def _route_after_extraction(self, state: "ContextAwareGraphState") -> str:
        if not state.get("context_ok"):
            return "end"
        return "generate_response"

    def _generate_response_node(self, state: "ContextAwareGraphState") -> Dict[str, Any]:
        from ampower_jive.utils.interaction_logger import InteractionLogger

        logger = InteractionLogger("data_query")
        message = state.get("message", "")
        history = state.get("history") or []
        context_dict = state.get("context") or {}
        context = ContextExtractionResult(**context_dict)

        prompt = self.prompt_builder.build(context, message, history=history, max_tokens=self._get_max_context_tokens(), include_recent_history=False)

        llm, model, temperature = self._build_llm(session_id=state.get("session_id"))
        if not llm:
            api_key = self.config_provider.get_api_key()
            if not api_key:
                return {
                    "response": "OpenAI API key is not configured. Please set it up in Jive Config or enable Jive Core."
                }
            return {"response": "I could not initialize the model for Context Aware Mode."}

        compressed_history = compress_history(history, max_messages=3, max_chars=1200)
        messages = [SystemMessage(content=prompt)]

        for msg in compressed_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "assistant":
                messages.append(AIMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))

        messages.append(HumanMessage(content=message))

        response = llm.invoke(messages)
        response_text = response.content if response and getattr(response, "content", None) else ""
        if not response_text:
            response_text = "I could not generate a response from the current context."

        try:
            logger.log(
                request_data={
                    "message": message,
                    "mode": "context",
                    "context": context.to_dict(),
                    "prompt": prompt[:5000],
                    "model": model,
                    "temperature": temperature,
                },
                response_data=response_text,
                model=model,
                status="success",
                session_id=state.get("session_id"),
            )
        except Exception:
            pass

        return {
            "response": response_text,
            "prompt": prompt,
            "model": model,
            "temperature": temperature,
        }

    @staticmethod
    def _normalize_payload(context_payload: Any) -> Dict[str, Any]:
        if not context_payload:
            return {}

        if isinstance(context_payload, dict):
            return context_payload

        if isinstance(context_payload, str):
            try:
                parsed = json.loads(context_payload)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}

        return {}

    @staticmethod
    def _context_error_message(context: ContextExtractionResult) -> str:
        if context.error:
            return context.error
        return DEFAULT_CONTEXT_FALLBACK_MESSAGE


def get_context_aware_default_prompt() -> str:
    """Return a production-safe fallback prompt for context aware mode."""
    return DEFAULT_CONTEXT_PROMPT



def build_context_aware_prompt(context_payload: Any, user_question: str = "", history: List[Dict[str, str]] = None) -> str:
    """Build a supplemental current-view context prompt for other modes."""
    service = ContextAwareModeService()
    payload = service._normalize_payload(context_payload)
    if not payload:
        return ""

    context = service.extraction_factory.extract(payload, user_question=user_question)
    if not context.ok:
        return ""

    try:
        return service.prompt_builder.build(
            context,
            user_question,
            history=history or [],
            max_tokens=service._get_max_context_tokens(),
            include_recent_history=True,
        )
    except ContextBudgetExceededError as exc:
        return str(exc)


def process_context_aware_query(
    message: str,
    history: List[Dict[str, str]] = None,
    allowed_doctypes: List[str] = None,
    context_payload: Any = None,
    session_id: str = None,
) -> str:
    """Compatibility wrapper used by the chat API."""
    service = ContextAwareModeService()
    return service.process(
        message=message,
        history=history,
        allowed_doctypes=allowed_doctypes,
        context_payload=context_payload,
        session_id=session_id,
    )


class ContextAwareGraphState(TypedDict, total=False):
    message: str
    history: List[Dict[str, str]]
    allowed_doctypes: List[str]
    context_payload: Any
    session_id: str
    context: Dict[str, Any]
    context_ok: bool
    context_error: str
    response: str
    prompt: str
    model: str
    temperature: float
    max_context_tokens: int
