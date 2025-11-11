import json
import frappe
from frappe import _
from ..utils.core_utils import (
    _convert_dates_to_strings,
    _open_fresh_session,
    _teardown_session,
)


def run_multi_doctype_query(filters):
    """
    Query parent doctype with optional child tables.
    Returns parent documents with nested child table data.
    Opens a fresh DB session per call to always read latest committed rows.
    All queries enforce permission checking.
    Returns errors as empty results with error metadata instead of throwing.
    """
    if isinstance(filters, str):
        filters = json.loads(filters)

    parent_doctype = filters.get("doctype")
    document_name = filters.get("document_name")
    parent_filters = filters.get("parent_filters", {})
    parent_fields = filters.get("parent_fields", ["name"])
    child_tables = filters.get("child_tables", [])
    limit = min(int(filters.get("limit", 100)), 1000)
    order_by = filters.get("order_by", "modified desc")

    if not parent_doctype:
        _teardown_session()
        return {"error": True, "message": "Parent doctype not specified", "data": []}

    _open_fresh_session()
    frappe.log_error("session User", frappe.session.user)
    try:
        # Always clear per-doctype caches (cheap) to avoid stale meta
        frappe.clear_cache(doctype=parent_doctype)
        frappe.clear_document_cache(parent_doctype)

        if document_name:
            try:
                frappe.clear_document_cache(parent_doctype, document_name)
                parent_doc = frappe.get_doc(parent_doctype, document_name)
                parent_doc.check_permission("read")  # Enforce read permission
                parent_results = [parent_doc.as_dict()]
                if (
                    parent_fields
                    and parent_fields != ["name"]
                    and "*" not in parent_fields
                ):
                    parent_results = [
                        {
                            k: v
                            for k, v in parent_results[0].items()
                            if k in parent_fields or k == "name"
                        }
                    ]
            except frappe.DoesNotExistError:
                _teardown_session()
                return {
                    "error": True,
                    "message": f"Document {document_name} does not exist",
                    "data": [],
                }
            except frappe.PermissionError:
                _teardown_session()
                return {
                    "error": True,
                    "message": "Permission Error: You do not have permission to access this document",
                    "data": [],
                }
        else:
            if (
                parent_fields
                and "name" not in parent_fields
                and "*" not in parent_fields
            ):
                parent_fields = ["name"] + parent_fields

            try:
                # Always use frappe.get_list (permission-aware)
                parent_results = frappe.get_list(
                    parent_doctype,
                    filters=parent_filters,
                    fields=parent_fields,
                    limit_page_length=limit,
                    order_by=order_by,
                    ignore_permissions=False,  # Explicitly enforce permissions
                )
            except frappe.PermissionError:
                _teardown_session()
                return {
                    "error": True,
                    "message": f"Permission Error: You do not have permission to read {parent_doctype}",
                    "data": [],
                }

        if not parent_results:
            _teardown_session()
            return {
                "error": False,
                "message": "No documents found matching the criteria",
                "data": [],
            }

        parent_names = [doc.get("name") for doc in parent_results]

        for child_config in child_tables:
            child_doctype = child_config.get("child_doctype")
            child_fields = child_config.get("fields", ["*"])
            child_filters = child_config.get("filters", {}) or {}

            if not child_doctype:
                continue

            frappe.clear_cache(doctype=child_doctype)
            frappe.clear_document_cache(child_doctype)

            if (
                child_fields
                and "parent" not in child_fields
                and "*" not in child_fields
            ):
                child_fields = ["parent"] + child_fields

            child_filters["parent"] = ["in", parent_names]
            child_filters["parenttype"] = parent_doctype

            try:
                # Always use frappe.get_list with parent_doctype for child table permissions
                child_results = frappe.get_list(
                    child_doctype,
                    filters=child_filters,
                    fields=child_fields,
                    order_by="idx asc",
                    limit_page_length=0,
                    parent_doctype=parent_doctype,  # Provide parent context for permission checks
                    ignore_permissions=False,  # Explicitly enforce permissions
                )
            except frappe.PermissionError:
                _teardown_session()
                return {
                    "error": True,
                    "message": f"Permission Error: You do not have permission to read child table {child_doctype}",
                    "data": [],
                }

            child_by_parent = {}
            for child in child_results:
                p = child.get("parent")
                child_by_parent.setdefault(p, []).append(child)

            parent_meta = frappe.get_meta(parent_doctype)
            child_fieldname = None
            for field in parent_meta.fields:
                if field.fieldtype == "Table" and field.options == child_doctype:
                    child_fieldname = field.fieldname
                    break
            if not child_fieldname:
                child_fieldname = frappe.scrub(child_doctype)

            for parent_doc in parent_results:
                name = parent_doc.get("name")
                parent_doc[child_fieldname] = child_by_parent.get(name, [])

        result = _convert_dates_to_strings(parent_results)
        frappe.log_error(
            "Query Results Count", f"{parent_doctype}: {len(result)} documents"
        )
        _teardown_session()
        return {"error": False, "message": "Success", "data": result}
    except Exception as e:
        frappe.log_error("Multi Doctype Query Error", str(e))
        _teardown_session()
        return {"error": True, "message": f"Unexpected error: {str(e)}", "data": []}
    finally:
        # Critical: release the snapshot so the next call sees new commits
        _teardown_session()
