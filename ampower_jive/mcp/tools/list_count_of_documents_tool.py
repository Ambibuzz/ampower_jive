# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from ampower_jive.mcp.config.setup import logger
from ..utils.core_utils import _open_fresh_session, _teardown_session

try:

    def run_multi_document_query_count_only(filters):
        """
        Perform a query on multiple doctypes and their child tables with filters,
        but return only the count of matching parent documents.
        Uses frappe.get_list to ensure permission checking.
        Returns errors in consistent format instead of throwing.
        """

        _open_fresh_session()
        if isinstance(filters, str):
            filters = json.loads(filters)

        parent_doctype = filters.get("doctype")
        parent_filters = filters.get("parent_filters", {})
        child_tables = filters.get("child_tables", [])
        parent_fields = filters.get("fields", ["name"])

        if not parent_doctype:
            _teardown_session()
            return {
                "error": True,
                "message": "Parent doctype not specified",
                "count": 0,
            }

        try:
            # Step 1: Query each child table filters to get parents satisfying child filters
            parent_names_sets = []
            for child in child_tables:
                child_doctype = child.get("child_doctype")
                child_filter = child.get("filters", {})
                if not child_doctype or not child_filter:
                    continue

                try:
                    # Use frappe.get_list with parent_doctype context for permission checking
                    # Child tables inherit permissions from their parent doctype
                    child_results = frappe.get_list(
                        child_doctype,
                        filters=child_filter,
                        fields=["parent"],
                        parent_doctype=parent_doctype,  # Provide parent context for permission checks
                        ignore_permissions=False,  # Explicitly enforce permissions
                    )
                    parents_from_child = {d.parent for d in child_results}
                    parent_names_sets.append(parents_from_child)
                except frappe.PermissionError:
                    _teardown_session()
                    return {
                        "error": True,
                        "message": f"Permission Error: You do not have permission to read child table {child_doctype}",
                        "count": 0,
                    }

            # Step 2: Combine child table parent filters (intersection)
            if parent_names_sets:
                allowed_parents = set.intersection(*parent_names_sets)
                if not allowed_parents:
                    _teardown_session()
                    return {
                        "error": False,
                        "message": "No matching documents found",
                        "count": 0,
                    }

                # Add parent name filter to parent_filters to restrict parents from children
                parent_filters["name"] = ["in", list(allowed_parents)]

            frappe.log_error(
                "Before Parent Results", f"{parent_doctype}, {parent_filters}"
            )

            # Step 3: Query parent doctype count with combined parent filters
            # Use frappe.get_list instead of frappe.get_all to enforce permissions
            try:
                parent_results = frappe.get_list(
                    parent_doctype,
                    filters=parent_filters,
                    fields=["name"],
                    ignore_permissions=False,  # Explicitly enforce permissions
                )
            except frappe.PermissionError:
                _teardown_session()
                return {
                    "error": True,
                    "message": f"Permission Error: You do not have permission to read {parent_doctype}",
                    "count": 0,
                }

            if parent_results is None:
                parent_results = []

            count = len(parent_results)
            logger.info("Count of Parent Results", f"{count}")
            frappe.log_error("Count of Parent Results", f"{count}")
            _teardown_session()
            return {"error": False, "message": "Success", "count": count}

        except Exception as e:
            frappe.log_error("Multi Document Query Count Error", str(e))
            _teardown_session()
            return {"error": True, "message": f"Unexpected error: {str(e)}", "count": 0}

except Exception as e:
    logger.error(f"Error in list_count_of_documents_tool: {e}")
    _teardown_session()
