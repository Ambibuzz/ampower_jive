# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _


def run_multi_document_query_count_only(filters):
    """
    Perform a query on multiple doctypes and their child tables with filters,
    but return only the count of matching parent documents.
    """

    if isinstance(filters, str):
        filters = json.loads(filters)

    parent_doctype = filters.get("doctype")
    parent_filters = filters.get("parent_filters", {})
    child_tables = filters.get("child_tables", [])
    parent_fields = filters.get("fields", ["name"])

    if not parent_doctype:
        frappe.throw(_("Parent doctype not specified"))

    # Step 1: Query each child table filters to get parents satisfying child filters
    parent_names_sets = []
    for child in child_tables:
        child_doctype = child.get("child_doctype")
        child_filter = child.get("filters", {})
        if not child_doctype or not child_filter:
            continue

        # Get parent documents from child table matching filter
        child_results = frappe.get_all(
            child_doctype, filters=child_filter, fields=["parent"]
        )
        parents_from_child = {d.parent for d in child_results}
        parent_names_sets.append(parents_from_child)

    # Step 2: Combine child table parent filters (intersection)
    if parent_names_sets:
        allowed_parents = set.intersection(*parent_names_sets)
        if not allowed_parents:
            return 0  # no matching docs, return count = 0

        # Add parent name filter to parent_filters to restrict parents from children
        parent_filters["name"] = ["in", list(allowed_parents)]

    frappe.log_error("Before Parent Results", f"{parent_doctype}, {parent_filters}")

    # Step 3: Query parent doctype count with combined parent filters
    parent_results = frappe.get_all(
        parent_doctype, filters=parent_filters, fields=["name"]
    )
    if parent_results is None:
        parent_results = []

    count = len(parent_results)
    frappe.log_error("Count of Parent Results", f"{count}")
    return count