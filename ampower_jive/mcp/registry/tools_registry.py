# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import json, frappe
from ampower_jive.mcp.tools import (
    helpdesk_tools,
    multi_doctype_query_tool,
    list_count_of_documents_tool,
)
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from ampower_jive.mcp.config.clients import mcp


@mcp.tool(
    name="helpdesk_tool",
    description="""
    Run Helpdesk with web scraping over forums, help manuals, and documentation.

    Args:
        user_prompt (str): The user query to process.

    Returns:
        dict: The AI's processed response with helpdesk results.
    """,
)
def run_helpdesk_tool(user_prompt: str) -> dict:
    try:
        frappe.log_error("MCP Query - helpdesk_tool", f"Input: {user_prompt}")

        result = helpdesk_tools.run_helpdesk(user_prompt)

        frappe.log_error(
            "MCP Response - helpdesk_tool",
            f"Output: {json.dumps(result, indent=2, default=str)}",
        )

        return result

    except Exception as e:
        error_msg = str(e)
        error_trace = frappe.get_traceback()
        frappe.log_error(
            "MCP Error - helpdesk_tool", f"Error: {error_msg}\n\nTrace:\n{error_trace}"
        )

        return {
            "success": False,
            "error": error_msg,
            "suggestion": "Check MCP server logs and Frappe connection status",
        }


# Keep the schema definitions for structure validation
class ChildTableConfig(BaseModel):
    """Configuration for querying a child table"""

    child_doctype: str = Field(
        ...,
        description="Name of the child doctype (e.g., 'Purchase Order Item', 'Sales Order Item')",
    )
    fields: Optional[List[str]] = Field(
        default=None,
        description="List of fields to fetch from child table. Use ['*'] for all fields or ['item_code', 'item_name', 'qty']",
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None, description="Filters to apply on child table fields as dict"
    )


class MultiDoctypeQuery(BaseModel):
    """Schema for querying parent doctypes and their child tables"""

    doctype: str = Field(
        ...,
        description="Parent doctype name (e.g., 'Sales Order', 'Purchase Order', 'Sales Invoice')",
    )
    document_name: Optional[str] = Field(
        default=None,
        description="Specific document name/ID to fetch (e.g., 'PUR-ORD-2025-00009'). If provided, other filters are ignored.",
    )
    parent_filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Filters for parent doctype as dict. Example: {'status': 'Draft', 'customer': 'ABC Corp'}",
    )
    parent_fields: Optional[List[str]] = Field(
        default=["name"],
        description="Parent fields to return. Default: ['name']. Use ['*'] for all or specify: ['name', 'supplier', 'transaction_date']",
    )
    child_tables: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="List of child table configurations to fetch"
    )
    limit: Optional[int] = Field(
        default=100,
        description="Maximum number of parent documents to return (default: 100, max: 1000)",
    )
    order_by: Optional[str] = Field(
        default="modified desc",
        description="Sort order for results (e.g., 'creation desc', 'transaction_date desc')",
    )


@mcp.tool(
    name="multi_doctype_query",
    description="""Query parent doctypes and their child tables. 

REQUIRED PARAMETERS:
- doctype: Parent doctype name (e.g., "Purchase Order", "Sales Order")

OPTIONAL PARAMETERS:
- document_name: Specific document ID (e.g., "PUR-ORD-2025-00009")
- parent_fields: List of fields to return (default: ["name"])
- child_tables: List of child table configs [{"child_doctype": "Purchase Order Item", "fields": ["item_code", "item_name", "qty"]}]
- parent_filters: Dict of filters (e.g., {"status": "Draft"})
- limit: Max records (default: 100)
- order_by: Sort order (default: "modified desc")

Example for "items on PUR-ORD-2025-00009":
{"doctype": "Purchase Order", "document_name": "PUR-ORD-2025-00009", "child_tables": [{"child_doctype": "Purchase Order Item", "fields": ["item_code", "item_name", "qty", "rate"]}]}
""",
)
def multi_doctype_query(
    doctype: str,
    document_name: Optional[str] = None,
    parent_fields: Optional[List[str]] = None,
    child_tables: Optional[List[Dict[str, Any]]] = None,
    parent_filters: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 100,
    order_by: Optional[str] = "modified desc",
) -> str:
    """
    Execute multi-doctype query with parent and child table support.
    Uses direct parameters instead of nested object to avoid N8N schema validation issues.
    """
    try:
        # Build the query dict from individual parameters
        agent_query = {
            "doctype": doctype,
            "document_name": document_name,
            "parent_filters": parent_filters or {},
            "parent_fields": parent_fields or ["name"],
            "child_tables": child_tables or [],
            "limit": min(limit or 100, 1000),
            "order_by": order_by or "modified desc",
        }

        # Remove None values
        agent_query = {k: v for k, v in agent_query.items() if v is not None}

        frappe.log_error(
            "MCP Query - multi_doctype_query",
            f"Input:\n{json.dumps(agent_query, indent=2)}",
        )

        results = multi_doctype_query_tool.run_multi_doctype_query(agent_query)

        response = {
            "success": True,
            "results": results,
            "count": len(results),
            "message": f"Found {len(results)} document(s)",
        }

        frappe.log_error(
            "MCP Response - multi_doctype_query",
            f"Output:\n{json.dumps(response, indent=2, default=str)}",
        )

        return json.dumps(response, indent=2, default=str)

    except Exception as e:
        error_msg = str(e)
        error_trace = frappe.get_traceback()
        frappe.log_error(
            "MCP Error - multi_doctype_query",
            f"Error: {error_msg}\n\nQuery: {agent_query}\n\nTrace:\n{error_trace}",
        )

        return json.dumps(
            {
                "success": False,
                "error": error_msg,
                "suggestion": "Check if the doctype name and document_name are correct. Common doctypes: 'Sales Order', 'Purchase Order', 'Sales Invoice', 'Purchase Invoice'",
            },
            indent=2,
        )


# For count tool - also use direct parameters
@mcp.tool(
    name="get_count_of_documents",
    description="""Get count of documents matching filters. Returns only the number, not actual records.

REQUIRED PARAMETERS:
- doctype: Parent doctype name (e.g., "Sales Order", "Purchase Order")

OPTIONAL PARAMETERS:
- parent_filters: Dict of filters (e.g., {"status": "Draft", "customer": "ABC Corp"})
- child_tables: List of child table filters to restrict count [{"child_doctype": "Sales Order Item", "filters": {"item_code": "ITEM-001"}}]

Example: {"doctype": "Sales Order", "parent_filters": {"status": "To Deliver"}}
""",
)
def get_count_of_documents(
    doctype: str,
    parent_filters: Optional[Dict[str, Any]] = None,
    child_tables: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Get count of documents matching the query filters."""
    try:
        agent_query = {
            "doctype": doctype,
            "parent_filters": parent_filters or {},
            "child_tables": child_tables or [],
        }

        agent_query = {k: v for k, v in agent_query.items() if v is not None}

        frappe.log_error(
            "MCP Query - get_count", f"Input:\n{json.dumps(agent_query, indent=2)}"
        )

        count = list_count_of_documents_tool.run_multi_document_query_count_only(
            agent_query
        )

        response = {
            "success": True,
            "count": count,
            "message": f"Found {count} document(s) matching filters",
        }

        frappe.log_error(
            "MCP Response - get_count", f"Output:\n{json.dumps(response, indent=2)}"
        )

        return json.dumps(response, indent=2)

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(
            "MCP Error - get_count",
            f"Error: {error_msg}\n\nQuery: {agent_query}\n\n{frappe.get_traceback()}",
        )

        return json.dumps({"success": False, "error": error_msg}, indent=2)
