"""
Schema Cache for Jive Agent
Pre-loads and caches doctype schemas for faster agent responses.
Refreshes only when data sources are added/removed.
"""

import frappe
import json
import time
from typing import Dict, List, Optional, Any

# Global cache
_schema_cache: Dict[str, Any] = {
    "schemas": {},
    "allowed_doctypes": [],
    "last_refresh": 0,
    "config_hash": None
}

# Cache TTL (5 minutes - but will also refresh on config change)
CACHE_TTL = 300


def _get_config_hash() -> str:
    """Get hash of current data sources configuration."""
    try:
        config = frappe.get_single("Jive Config")
        doctypes = []
        if hasattr(config, 'included_doctypes') and config.included_doctypes:
            for source in config.included_doctypes:
                doctypes.append(source.doctype_name)
        return ",".join(sorted(doctypes))
    except Exception:
        return ""


def _load_doctype_schema(doctype: str) -> Dict:
    """Load schema for a single doctype."""
    try:
        meta = frappe.get_meta(doctype)
        
        # Get key fields
        fields = []
        for field in meta.fields:
            if field.fieldtype in ['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button']:
                continue
            
            field_info = {
                "fieldname": field.fieldname,
                "label": field.label or field.fieldname,
                "fieldtype": field.fieldtype,
                "required": bool(field.reqd),
                "options": field.options if field.fieldtype in ['Link', 'Select', 'Table'] else None
            }
            fields.append(field_info)
        
        # Get commonly queried fields (non-internal)
        queryable_fields = [f["fieldname"] for f in fields if f["fieldname"] not in [
            'idx', 'docstatus', 'owner', 'modified_by', '_user_tags', '_comments', '_assign', '_liked_by'
        ]][:20]  # Limit to 20 for prompt size
        
        # Determine date field
        date_field = None
        for f in fields:
            if f["fieldname"] in ['posting_date', 'transaction_date', 'creation']:
                date_field = f["fieldname"]
                break
        
        # Check if submittable
        is_submittable = bool(meta.is_submittable)
        
        # Check if child table
        is_child = bool(meta.istable)
        parent_field = "parent" if is_child else None
        
        return {
            "doctype": doctype,
            "fields": fields,
            "queryable_fields": queryable_fields,
            "date_field": date_field,
            "is_submittable": is_submittable,
            "is_child_table": is_child,
            "parent_field": parent_field,
            "table_name": f"tab{doctype}",
            "description": meta.description or f"{doctype} records"
        }
    except Exception as e:
        frappe.log_error(
            message=f"Failed to load schema for {doctype}: {e}",
            title="Jive Schema Cache"
        )
        return {
            "doctype": doctype,
            "error": str(e),
            "fields": [],
            "queryable_fields": ["name"],
            "is_submittable": False,
            "is_child_table": False
        }


def refresh_schema_cache(force: bool = False) -> Dict:
    """
    Refresh the schema cache.
    Only reloads if config has changed or cache is stale.
    """
    global _schema_cache
    
    now = time.time()
    current_hash = _get_config_hash()
    
    # Check if refresh is needed
    cache_age = now - _schema_cache.get("last_refresh", 0)
    config_changed = current_hash != _schema_cache.get("config_hash")
    
    if not force and not config_changed and cache_age < CACHE_TTL:
        # Cache is still valid
        return _schema_cache
    
    try:
        # Load allowed doctypes from config
        config = frappe.get_single("Jive Config")
        allowed_doctypes = []
        if hasattr(config, 'included_doctypes') and config.included_doctypes:
            for source in config.included_doctypes:
                if source.doctype_name:
                    allowed_doctypes.append(source.doctype_name)
        
        # Load schemas for all allowed doctypes
        schemas = {}
        for doctype in allowed_doctypes:
            schemas[doctype] = _load_doctype_schema(doctype)
        
        # Update cache
        _schema_cache = {
            "schemas": schemas,
            "allowed_doctypes": allowed_doctypes,
            "last_refresh": now,
            "config_hash": current_hash
        }
        
        # Also store in Redis for cross-process sharing
        cache_key = "jive_schema_cache"
        frappe.cache().set_value(cache_key, json.dumps(_schema_cache), expires_in_sec=CACHE_TTL * 2)
        
        return _schema_cache
        
    except Exception as e:
        frappe.log_error(
            message=f"Failed to refresh schema cache: {e}\n\n{frappe.get_traceback()}",
            title="Jive Schema Cache"
        )
        return _schema_cache


def get_schema_cache() -> Dict:
    """Get the current schema cache, refreshing if needed."""
    global _schema_cache
    
    # Try to load from Redis if local cache is empty
    if not _schema_cache.get("schemas"):
        try:
            cache_key = "jive_schema_cache"
            cached = frappe.cache().get_value(cache_key)
            if cached:
                _schema_cache = json.loads(cached)
        except Exception:
            pass
    
    # Check if refresh needed
    now = time.time()
    current_hash = _get_config_hash()
    cache_age = now - _schema_cache.get("last_refresh", 0)
    config_changed = current_hash != _schema_cache.get("config_hash")
    
    if config_changed or cache_age > CACHE_TTL or not _schema_cache.get("schemas"):
        return refresh_schema_cache()
    
    return _schema_cache


def get_allowed_doctypes() -> List[str]:
    """Get list of allowed doctypes from cache."""
    cache = get_schema_cache()
    return cache.get("allowed_doctypes", [])


def get_doctype_schema(doctype: str) -> Optional[Dict]:
    """Get schema for a specific doctype."""
    cache = get_schema_cache()
    return cache.get("schemas", {}).get(doctype)


def get_schema_summary_for_llm() -> str:
    """
    Get a compact schema summary suitable for LLM prompts.
    This gives the LLM knowledge of available doctypes and their key fields.
    """
    cache = get_schema_cache()
    schemas = cache.get("schemas", {})
    
    if not schemas:
        return "No data sources configured."
    
    lines = ["AVAILABLE DATA SOURCES AND FIELDS:"]
    
    for doctype, schema in schemas.items():
        if schema.get("error"):
            continue
        
        # Get key queryable fields
        fields = schema.get("queryable_fields", [])[:10]
        field_str = ", ".join(fields) if fields else "name"
        
        # Add doctype info
        doctype_line = f"- **{doctype}** (`tab{doctype}`): {field_str}"
        
        # Add notes for special cases
        notes = []
        if schema.get("is_submittable"):
            notes.append("submittable (use docstatus=1)")
        if schema.get("is_child_table"):
            notes.append("child table (join via parent)")
        if schema.get("date_field"):
            notes.append(f"date: {schema['date_field']}")
        
        if notes:
            doctype_line += f" [{', '.join(notes)}]"
        
        lines.append(doctype_line)
    
    return "\n".join(lines)


def invalidate_cache(doc=None, method=None):
    """Force invalidate the cache (called when config changes via hook)."""
    global _schema_cache
    _schema_cache = {
        "schemas": {},
        "allowed_doctypes": [],
        "last_refresh": 0,
        "config_hash": None
    }
    
    # Clear Redis cache too
    try:
        frappe.cache().delete_value("jive_schema_cache")
    except Exception:
        pass
