import json
import frappe
from frappe import _
from datetime import datetime, date


@frappe.whitelist()
def run_multi_doctype_query(filters):
    """
    Query parent doctype with optional child tables.
    Returns parent documents with nested child table data.
    """
    if isinstance(filters, str):
        filters = json.loads(filters)

    parent_doctype = filters.get("doctype")
    document_name = filters.get("document_name")  # NEW: Direct document name
    parent_filters = filters.get("parent_filters", {})
    parent_fields = filters.get("parent_fields", ["name"])
    child_tables = filters.get("child_tables", [])
    limit = min(int(filters.get("limit", 100)), 1000)
    order_by = filters.get("order_by", "modified desc")

    if not parent_doctype:
        frappe.throw(_("Parent doctype not specified"))

    # Priority 1: If document_name is provided, fetch that specific document
    if document_name:
        try:
            parent_doc = frappe.get_doc(parent_doctype, document_name)
            parent_results = [parent_doc.as_dict()]
            
            # Filter parent_fields if specified
            if parent_fields and parent_fields != ["name"] and "*" not in parent_fields:
                parent_results = [{k: v for k, v in parent_results[0].items() if k in parent_fields or k == "name"}]
        except frappe.DoesNotExistError:
            return []
    else:
        # Priority 2: Query with filters
        # Ensure 'name' is always included for child table linking
        if parent_fields and "name" not in parent_fields and "*" not in parent_fields:
            parent_fields = ["name"] + parent_fields

        parent_results = frappe.get_all(
            parent_doctype,
            filters=parent_filters,
            fields=parent_fields,
            limit=limit,
            order_by=order_by
        )

    if not parent_results:
        return []

    # Extract parent names for child table queries
    parent_names = [doc.get("name") for doc in parent_results]

    # Fetch child table data if requested
    for child_config in child_tables:
        child_doctype = child_config.get("child_doctype")
        child_fields = child_config.get("fields", ["*"])
        child_filters = child_config.get("filters", {})

        if not child_doctype:
            continue

        # Always include 'parent' field to link child records to parents
        if child_fields and "parent" not in child_fields and "*" not in child_fields:
            child_fields = ["parent"] + child_fields

        # Add parent filter to restrict child records to these parents
        child_filters["parent"] = ["in", parent_names]
        child_filters["parenttype"] = parent_doctype

        # Query child table
        child_results = frappe.get_all(
            child_doctype,
            filters=child_filters,
            fields=child_fields,
            order_by="idx asc"  # Preserve row order
        )

        # Group child records by parent
        child_by_parent = {}
        for child in child_results:
            parent_name = child.get("parent")
            if parent_name not in child_by_parent:
                child_by_parent[parent_name] = []
            child_by_parent[parent_name].append(child)

        # Get the child table fieldname from parent doctype meta
        parent_meta = frappe.get_meta(parent_doctype)
        child_fieldname = None
        for field in parent_meta.fields:
            if field.fieldtype == "Table" and field.options == child_doctype:
                child_fieldname = field.fieldname
                break

        # Use child_doctype as fallback if fieldname not found
        if not child_fieldname:
            child_fieldname = frappe.scrub(child_doctype)

        # Attach child records to parent documents
        for parent_doc in parent_results:
            parent_name = parent_doc.get("name")
            parent_doc[child_fieldname] = child_by_parent.get(parent_name, [])

    frappe.log_error("Query Results Count", f"{parent_doctype}: {len(parent_results)} documents")
    return parent_results