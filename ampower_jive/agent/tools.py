"""
Native LangChain Tools for Jive Agent
These tools execute directly within Frappe with user session permissions.
"""

import frappe
from frappe import _
from langchain_core.tools import tool
from typing import List, Dict, Any, Optional, Union
import json
import re
from datetime import datetime, timedelta


def sanitize_filters(filters: Union[Dict, List, None], doctype: str = None) -> Union[Dict, List]:
    """Sanitize filters to ensure they're compatible with Frappe ORM."""
    if not filters:
        return {}
    if isinstance(filters, list):
        return _sanitize_filter_sequence(filters)
    if isinstance(filters, dict):
        sanitized_dict, list_filters = _sanitize_filter_mapping(filters)
        if list_filters and not sanitized_dict:
            return list_filters
        if list_filters:
            return list_filters + [[k, "=", v] for k, v in sanitized_dict.items()]
        return sanitized_dict
    return {}

def apply_default_filters(doctype: str, filters: dict = None, order_by: str = None) -> tuple:
    """Apply sensible default filters based on doctype when user doesn't specify."""
    return _build_default_filter_state(doctype, filters, order_by)


def _priority_fieldnames(meta, row: Dict[str, Any], limit: int = 6) -> List[str]:
    """Pick a compact set of fields that best describe a document row."""
    priorities = []

    candidates = [
        getattr(meta, "title_field", None),
        "name",
        "item_code",
        "item_name",
        "customer",
        "customer_name",
        "supplier",
        "supplier_name",
        "party_name",
        "posting_date",
        "transaction_date",
        "qty",
        "uom",
        "stock_uom",
        "rate",
        "amount",
        "grand_total",
        "outstanding_amount",
        "status",
        "warehouse",
        "description",
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

    for field in getattr(meta, "fields", []):
        fieldname = getattr(field, "fieldname", None)
        if not fieldname or fieldname in seen:
            continue
        if fieldname in row and field.fieldtype not in ['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Fold']:
            priorities.append(fieldname)
            if len(priorities) >= limit:
                break

    return priorities


def _summarize_child_table_rows(child_doctype: str, rows: List[Dict[str, Any]], row_limit: int = 5) -> Dict[str, Any]:
    """Return a compact summary for a child table without flooding the prompt."""
    try:
        child_meta = frappe.get_meta(child_doctype)
    except Exception:
        child_meta = None

    summary_rows = []
    for row in rows[:row_limit]:
        if not isinstance(row, dict):
            continue
        fieldnames = _priority_fieldnames(child_meta, row, limit=6) if child_meta else list(row.keys())[:6]
        summary_rows.append({
            field: row.get(field)
            for field in fieldnames
            if row.get(field) is not None
        })

    return {
        "child_doctype": child_doctype,
        "row_count": len(rows),
        "showing": len(summary_rows),
        "rows": summary_rows,
    }


_VALID_FILTER_OPERATORS = {
    "=", "!=", "<", ">", "<=", ">=", "like", "not like",
    "in", "not in", "between", "is", "timespan",
}

_DATE_BASED_DOCTYPES = {
    "Sales Invoice": "posting_date",
    "Purchase Invoice": "posting_date",
    "Sales Order": "transaction_date",
    "Purchase Order": "transaction_date",
    "Delivery Note": "posting_date",
    "Purchase Receipt": "posting_date",
    "Stock Entry": "posting_date",
    "Payment Entry": "posting_date",
    "Journal Entry": "posting_date",
    "Quotation": "transaction_date",
    "Lead": "creation",
    "Opportunity": "creation",
}

_SUBMITTABLE_DOCTYPES = {
    "Sales Invoice", "Purchase Invoice", "Sales Order", "Purchase Order",
    "Delivery Note", "Purchase Receipt", "Stock Entry", "Payment Entry",
    "Journal Entry", "Quotation",
}


def _convert_sql_date_expression(value):
    if not isinstance(value, str):
        return value

    value_upper = value.upper()
    if "DATE_SUB" not in value_upper and "CURDATE" not in value_upper and "NOW()" not in value_upper:
        return value

    interval_match = re.search(r"INTERVAL\s+(\d+)\s+(DAY|MONTH|YEAR)", value_upper)
    if not interval_match:
        return datetime.now().strftime("%Y-%m-%d")

    amount = int(interval_match.group(1))
    unit = interval_match.group(2)
    days = amount * 30 if unit == "MONTH" else amount * 365 if unit == "YEAR" else amount
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def _has_filter_on_field(filters, fieldname: str) -> bool:
    if isinstance(filters, dict):
        return fieldname in filters
    if isinstance(filters, list):
        return any(isinstance(item, list) and len(item) >= 1 and item[0] == fieldname for item in filters)
    return False


def _sanitize_filter_sequence(filters: list) -> list:
    sanitized = []
    for entry in filters:
        if not isinstance(entry, list) or len(entry) < 3:
            continue
        field, op, value = entry[0], entry[1], _convert_sql_date_expression(entry[2])
        if str(op).lower() in _VALID_FILTER_OPERATORS:
            sanitized.append([field, op, value])
    return sanitized


def _sanitize_filter_mapping(filters: dict):
    sanitized_dict = {}
    list_filters = []

    for key, value in filters.items():
        if value is None:
            continue

        if isinstance(value, dict):
            for op, val in value.items():
                op_lower = str(op).lower().strip()
                val = _convert_sql_date_expression(val)
                if op_lower in {"gte", "ge", ">="}:
                    list_filters.append([key, ">=", val])
                elif op_lower in {"lte", "le", "<="}:
                    list_filters.append([key, "<=", val])
                elif op_lower in {"gt", ">"}:
                    list_filters.append([key, ">", val])
                elif op_lower in {"lt", "<"}:
                    list_filters.append([key, "<", val])
                elif op_lower in {"ne", "neq", "!=", "<>"}:
                    list_filters.append([key, "!=", val])
                elif op_lower in {"eq", "=", "=="}:
                    sanitized_dict[key] = val
                elif op_lower in _VALID_FILTER_OPERATORS:
                    list_filters.append([key, op_lower, val])
                else:
                    sanitized_dict[key] = val
            continue

        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str) and value[0].lower() in _VALID_FILTER_OPERATORS:
                filter_val = _convert_sql_date_expression(value[1]) if not isinstance(value[1], list) else value[1]
                list_filters.append([key, value[0], filter_val])
            else:
                list_filters.append([key, "in", value])
            continue

        sanitized_dict[key] = value

    return sanitized_dict, list_filters


def _build_default_filter_state(doctype: str, filters=None, order_by: str = None):
    filters = filters or {}
    if doctype in _DATE_BASED_DOCTYPES and not _has_filter_on_field(filters, _DATE_BASED_DOCTYPES[doctype]):
        date_from = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if isinstance(filters, dict):
            filters[_DATE_BASED_DOCTYPES[doctype]] = [">=", date_from]
        elif isinstance(filters, list):
            filters.append([_DATE_BASED_DOCTYPES[doctype], ">=", date_from])
        else:
            filters = {_DATE_BASED_DOCTYPES[doctype]: [">=", date_from]}

    if doctype in _SUBMITTABLE_DOCTYPES and not _has_filter_on_field(filters, "docstatus"):
        if isinstance(filters, dict):
            filters["docstatus"] = 1
        elif isinstance(filters, list):
            filters.append(["docstatus", "=", 1])
        else:
            filters = {"docstatus": 1}

    if not order_by:
        order_by = f"{_DATE_BASED_DOCTYPES[doctype]} desc" if doctype in _DATE_BASED_DOCTYPES else "creation desc"

    return filters, order_by


def _default_fields_for_doctype(doctype: str) -> List[str]:
    default_fields = {
        "Sales Invoice": ["name", "customer", "posting_date", "grand_total", "status"],
        "Sales Order": ["name", "customer", "transaction_date", "grand_total", "status"],
        "Customer": ["name", "customer_name", "customer_group", "territory"],
        "Item": ["name", "item_name", "item_group", "stock_uom"],
        "Quotation": ["name", "party_name", "transaction_date", "grand_total", "status"],
        "Error Log": ["name", "method", "error", "creation"],
    }
    return default_fields.get(doctype, ["name"])


def _ensure_name_field(fields: List[str]) -> List[str]:
    if not fields:
        return ["name"]
    if "name" in fields:
        return fields
    return ["name"] + fields


def _doc_field_info(field) -> Optional[Dict[str, Any]]:
    if field.fieldtype in {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold"}:
        return None
    if not field.fieldname:
        return None
    return {
        "fieldname": field.fieldname,
        "label": field.label or field.fieldname,
        "fieldtype": field.fieldtype,
        "required": bool(field.reqd),
        "read_only": bool(field.read_only),
        "options": field.options if field.fieldtype in {"Link", "Select", "Table", "Dynamic Link"} else None,
    }


def _child_table_summary(child_table, index: int = 8) -> Dict[str, Any]:
    child_doctype = child_table.get("child_doctype")
    if not child_doctype:
        return {**child_table, "is_child_table": True, "queryable_fields": ["name"], "fields": []}

    try:
        child_meta = frappe.get_meta(child_doctype)
        child_fields = []
        for cfield in child_meta.fields:
            info = _doc_field_info(cfield)
            if not info:
                continue
            child_fields.append(info)
        return {
            **child_table,
            "is_child_table": True,
            "queryable_fields": [item["fieldname"] for item in child_fields if item["fieldname"] not in {"parent", "parenttype", "parentfield", "idx"}][:12],
            "fields": child_fields[:12],
        }
    except Exception:
        return {**child_table, "is_child_table": True, "queryable_fields": ["name"], "fields": []}


def _build_doctype_summary(meta, fields: List[Dict[str, Any]], link_fields: List[Dict[str, Any]], child_tables: List[Dict[str, Any]], doctype: str) -> Dict[str, Any]:
    return json.dumps({
        "success": True,
        "doctype": doctype,
        "label": getattr(meta, "label", None) or doctype,
        "is_submittable": bool(meta.is_submittable),
        "is_child_table": bool(meta.istable),
        "title_field": getattr(meta, "title_field", None),
        "queryable_fields": [item["fieldname"] for item in fields if item["fieldname"] not in {"idx", "docstatus", "owner", "modified_by", "_user_tags", "_comments", "_assign", "_liked_by"}][:20],
        "fields": fields[:20],
        "link_fields": link_fields[:10],
        "child_tables": child_tables,
    }, default=str, indent=2)


def _build_aggregate_sql(table: str, agg_upper: str, agg_field: str, where_sql: str, group_by: str = None, limit: int = 20) -> str:
    if group_by:
        group_expr = group_by if ("(" in group_by and ")" in group_by) else f"`{group_by}`"
        return f"""
                SELECT {group_expr} as group_key, {agg_upper}({agg_field}) as result
                FROM `{table}`
                WHERE {where_sql}
                GROUP BY {group_expr}
                ORDER BY result DESC
                LIMIT {min(limit, 50)}
            """
    return f"""
                SELECT {agg_upper}({agg_field}) as result
                FROM `{table}`
                WHERE {where_sql}
            """


def _build_where_clauses(safe_filters) -> tuple[list, list]:
    where_clauses = ["1=1"]
    values = []

    if isinstance(safe_filters, dict):
        for k, v in safe_filters.items():
            if isinstance(v, list) and len(v) == 2:
                where_clauses.append(f"`{k}` {v[0]} %s")
                values.append(v[1])
            else:
                where_clauses.append(f"`{k}` = %s")
                values.append(v)
    elif isinstance(safe_filters, list):
        for f in safe_filters:
            if len(f) >= 3:
                where_clauses.append(f"`{f[0]}` {f[1]} %s")
                values.append(f[2])

    return where_clauses, values


def _build_query_response(doctype: str, results: list, limit: int) -> str:
    total_count = len(results)
    display_results = results[:limit] if len(results) > limit else results
    response = {
        "success": True,
        "doctype": doctype,
        "count": total_count,
        "showing": len(display_results),
        "data": display_results,
    }
    if total_count > limit:
        response["note"] = f"Showing top {limit} of {total_count} results. Use filters for specific records."
    elif total_count == 0:
        response["note"] = "No records found with the applied filters. Try a broader search."
    return json.dumps(response, default=str, indent=2)


def _build_aggregate_response(doctype: str, agg_upper: str, field: str, group_by: str, result: list, safe_filters):
    if group_by:
        data = [
            {
                group_by: row.get("group_key"),
                f"{agg_upper.lower()}_{field}": row.get("result") or 0,
            }
            for row in result
        ]
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "aggregation": agg_upper,
            "field": field,
            "group_by": group_by,
            "count": len(data),
            "data": data,
        }, default=str)

    value = result[0].get("result") if result else 0
    return json.dumps({
        "success": True,
        "doctype": doctype,
        "aggregation": agg_upper,
        "field": field,
        "result": value or 0,
        "filters_applied": safe_filters,
    }, default=str)


def _extract_referenced_doctypes(sql: str) -> List[str]:
    referenced_doctypes = []
    for match in re.findall(r"`tab([^`]+)`", sql, flags=re.IGNORECASE):
        doctype = match.strip()
        if doctype and doctype not in referenced_doctypes:
            referenced_doctypes.append(doctype)
    return referenced_doctypes


def _validate_select_sql(sql: str) -> Optional[str]:
    if not sql:
        return "SQL query is required"
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        return "Only SELECT queries are allowed"
    for keyword in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE"]:
        if keyword in sql_upper:
            return f"Query contains forbidden keyword: {keyword}"
    return None


@tool
def describe_doctype(doctype: str) -> str:
    """
    Return a compact schema summary for a DocType.

    Use this when you need to inspect link fields, child tables, or field names
    before asking for a narrower follow-up fetch.
    """
    try:
        if not doctype:
            return json.dumps({"error": "DocType is required"})

        if not frappe.has_permission(doctype, "read"):
            return json.dumps({"error": f"You don't have permission to read {doctype}"})

        meta = frappe.get_meta(doctype)
        fields = []
        link_fields = []
        child_tables = []

        for field in meta.fields:
            field_info = _doc_field_info(field)
            if not field_info:
                continue
            fields.append(field_info)

            if field.fieldtype in {"Link", "Dynamic Link"}:
                link_fields.append({
                    "fieldname": field.fieldname,
                    "label": field.label or field.fieldname,
                    "fieldtype": field.fieldtype,
                    "options": field.options,
                })
            elif field.fieldtype == "Table":
                child_tables.append({
                    "fieldname": field.fieldname,
                    "label": field.label or field.fieldname,
                    "child_doctype": field.options,
                })

        child_table_details = [_child_table_summary(child) for child in child_tables[:8]]
        return _build_doctype_summary(meta, fields, link_fields, child_table_details, doctype)
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": frappe.get_traceback()})


@tool
def multi_doctype_query(
    doctype: str,
    fields: List[str] = None,
    filters: Dict[str, Any] = None,
    limit: int = 10,
    order_by: str = None
) -> str:
    """
    Query records from a Frappe DocType.
    Automatically applies sensible defaults (last 12 months for date-based docs, docstatus=1 for submitted docs).
    
    Args:
        doctype: The DocType to query (e.g., "Sales Order", "Customer", "Item")
        fields: List of fields to return. Defaults to ["name"] if not provided.
        filters: Dictionary of filters. Use simple format: {"status": "Draft", "customer": "ABC"}
                 For date ranges, use: {"posting_date": [">=", "2025-01-01"]}
        limit: Maximum number of records to return (default 10, max 100)
        order_by: Field to order by (e.g., "creation desc", "posting_date desc")
    
    Returns:
        JSON string with query results or error message.
    """
    try:
        if not doctype:
            return json.dumps({"error": "DocType is required"})
        
        # Check permissions
        if not frappe.has_permission(doctype, "read"):
            return json.dumps({"error": f"You don't have permission to read {doctype}"})
        
        # Set defaults - ensure 'name' is always included
        if not fields:
            fields = _default_fields_for_doctype(doctype)
        fields = _ensure_name_field(fields)
        limit = min(limit or 10, 100)

        filters_with_defaults, order_by = apply_default_filters(doctype, filters, order_by)
        safe_filters = sanitize_filters(filters_with_defaults, doctype)
        results = frappe.get_list(
            doctype,
            fields=fields,
            filters=safe_filters,
            limit_page_length=limit,
            order_by=order_by,
        )

        return _build_query_response(doctype, results, 10)
        
    except Exception as e:
        frappe.log_error(
            message=f"Query error for {doctype}: {e}\n\n{frappe.get_traceback()}",
            title="Jive Tool Error"
        )
        return json.dumps({"error": str(e), "traceback": frappe.get_traceback()})


@tool
def get_document_count(doctype: str, filters: Dict[str, Any] = None) -> str:
    """
    Get the count of records for a DocType.
    
    Args:
        doctype: The DocType to count (e.g., "Sales Order", "Customer")
        filters: Optional filters. Use simple format: {"status": "Draft"}
    
    Returns:
        JSON string with count or error message.
    """
    try:
        if not doctype:
            return json.dumps({"error": "DocType is required"})
        
        if not frappe.has_permission(doctype, "read"):
            return json.dumps({"error": f"You don't have permission to read {doctype}"})
        
        safe_filters = sanitize_filters(filters, doctype)
        count = frappe.db.count(doctype, filters=safe_filters)
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "count": count,
            "filters": safe_filters
        })
        
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": frappe.get_traceback()})


@tool
def get_document(doctype: str, name: str, fields: List[str] = None) -> str:
    """
    Get a specific document by name.
    
    Args:
        doctype: The DocType (e.g., "Sales Order")
        name: The document name/ID
        fields: Optional list of fields to return
    
    Returns:
        JSON string with document data or error.
    """
    try:
        if not doctype or not name:
            return json.dumps({"error": "Both doctype and name are required"})
        
        if not frappe.has_permission(doctype, "read"):
            return json.dumps({"error": f"You don't have permission to read {doctype}"})
        
        doc = frappe.get_doc(doctype, name)
        if fields:
            data = {f: doc.get(f) for f in fields if doc.get(f) is not None}
        else:
            data = doc.as_dict()
            for key in ['_user_tags', '_comments', '_assign', '_liked_by', 'docstatus']:
                data.pop(key, None)

        summarized_tables = []
        for key, value in list(data.items()):
            if not isinstance(value, list) or not value:
                continue

            field = doc.meta.get_field(key) if hasattr(doc, "meta") else None
            if not field or field.fieldtype != "Table" or not field.options:
                continue

            child_doctype = field.options
            summary = _summarize_child_table_rows(child_doctype, value, row_limit=5)
            summarized_tables.append({
                "fieldname": key,
                "label": field.label or key,
                **summary,
            })
            data[key] = summary
        response = {"success": True, "doctype": doctype, "name": name, "data": data}
        if summarized_tables:
            response["summarized_tables"] = summarized_tables
        return json.dumps(response, default=str, indent=2)
        
    except frappe.DoesNotExistError:
        return json.dumps({"error": f"{doctype} '{name}' not found"})
    except Exception as e:
        return json.dumps({"error": str(e), "traceback": frappe.get_traceback()})


@tool
def aggregate_query(
    doctype: str,
    aggregation: str,
    field: str,
    filters: Dict[str, Any] = None,
    group_by: str = None,
    limit: int = 20
) -> str:
    """
    Perform aggregate calculations (SUM, AVG, COUNT, MIN, MAX) on a DocType.
    Use this for questions like "total revenue", "average order value", "sum of quantities".
    
    Args:
        doctype: The DocType to query (e.g., "Sales Invoice", "Sales Order")
        aggregation: The aggregate function - one of: SUM, AVG, COUNT, MIN, MAX
        field: The field to aggregate (e.g., "grand_total", "qty", "amount")
        filters: Optional filters. Use simple format: {"status": "Draft"}
        group_by: Optional field to group results by (e.g., "customer", "item_code")
        limit: Max groups to return when using group_by (default 20)
    
    Returns:
        JSON string with aggregated result.
    
    Examples:
        - Sum of all sales: aggregate_query("Sales Invoice", "SUM", "grand_total")
        - Average order value: aggregate_query("Sales Order", "AVG", "grand_total")
        - Revenue by customer: aggregate_query("Sales Invoice", "SUM", "grand_total", group_by="customer")
    """
    try:
        if not doctype:
            return json.dumps({"error": "DocType is required"})
        
        if not frappe.has_permission(doctype, "read"):
            return json.dumps({"error": f"You don't have permission to read {doctype}"})
        
        # Validate aggregation
        agg_upper = (aggregation or "SUM").upper()
        if agg_upper not in ['SUM', 'AVG', 'COUNT', 'MIN', 'MAX']:
            return json.dumps({"error": f"Invalid aggregation '{aggregation}'. Use SUM, AVG, COUNT, MIN, or MAX."})
        table = f"tab{doctype}"
        safe_filters = sanitize_filters(filters, doctype)
        where_clauses, values = _build_where_clauses(safe_filters)
        if doctype in _SUBMITTABLE_DOCTYPES and not filters:
            where_clauses.append("docstatus = 1")
        where_sql = " AND ".join(where_clauses)
        if agg_upper == "COUNT":
            agg_field = "*" if not field or field == "*" else f"`{field}`"
        else:
            agg_field = f"`{field}`" if field else "`name`"
        sql = _build_aggregate_sql(table, agg_upper, agg_field, where_sql, group_by=group_by, limit=limit)
        if sql.count('%') > len(values or []):
            sql = re.sub(r'%(?!s)', '%%', sql)
        result = frappe.db.sql(sql, tuple(values) if values else (), as_dict=True)
        return _build_aggregate_response(doctype, agg_upper, field, group_by, result, safe_filters)
    except Exception as e:
        frappe.log_error(
            message=f"Aggregate query error for {doctype}: {e}\n\n{frappe.get_traceback()}",
            title="Jive Tool Error"
        )
        return json.dumps({"error": str(e), "traceback": frappe.get_traceback()})


@tool
def complex_query(
    sql: str,
    description: str = None
) -> str:
    """
    Execute complex SQL queries with JOINs, subqueries, and advanced aggregations.
    Use this for questions that require combining data from multiple tables.
    
    IMPORTANT RULES:
    - Only SELECT queries allowed (no INSERT, UPDATE, DELETE)
    - Table names must use backticks: `tabSales Invoice`
    - Always include LIMIT (max 50)
    - For submitted docs, filter: docstatus = 1
    
    Common table names:
    - `tabSales Invoice` (SI), `tabSales Invoice Item` (SII)
    - `tabSales Order` (SO), `tabSales Order Item` (SOI)  
    - `tabCustomer`, `tabItem`, `tabQuotation`
    
    Example queries:
    1. Top customers by order count:
       SELECT customer, COUNT(*) as order_count, SUM(grand_total) as total
       FROM `tabSales Invoice` WHERE docstatus=1 GROUP BY customer ORDER BY order_count DESC LIMIT 10
    
    2. Items sold with customer details:
       SELECT SI.customer, SII.item_code, SII.item_name, SUM(SII.qty) as total_qty
       FROM `tabSales Invoice Item` SII
       JOIN `tabSales Invoice` SI ON SII.parent = SI.name
       WHERE SI.docstatus = 1
       GROUP BY SI.customer, SII.item_code ORDER BY total_qty DESC LIMIT 20
    
    3. Customer purchase frequency:
       SELECT customer, COUNT(*) as invoice_count, 
              MIN(posting_date) as first_order, MAX(posting_date) as last_order
       FROM `tabSales Invoice` WHERE docstatus=1 
       GROUP BY customer ORDER BY invoice_count DESC LIMIT 15
    
    Args:
        sql: The SQL SELECT query to execute
        description: Brief description of what this query does
    
    Returns:
        JSON string with query results.
    """
    try:
        validation_error = _validate_select_sql(sql)
        if validation_error:
            return json.dumps({"error": validation_error})

        for doctype in _extract_referenced_doctypes(sql):
            try:
                if not frappe.has_permission(doctype, "read"):
                    return json.dumps({"error": f"You don't have permission to read {doctype}"})
            except Exception:
                pass

        sql_upper = sql.upper().strip()
        if "LIMIT" not in sql_upper:
            sql = sql.rstrip(';') + ' LIMIT 50'
        results = frappe.db.sql(sql, values=(), as_dict=True)
        total_count = len(results)
        display_results = results[:30] if len(results) > 30 else results
        response = {
            "success": True,
            "query_type": "complex",
            "description": description or "Complex query result",
            "count": total_count,
            "showing": len(display_results),
            "data": display_results,
        }
        if total_count > 30:
            response["note"] = f"Showing 30 of {total_count} results"
        return json.dumps(response, default=str, indent=2)
        
    except Exception as e:
        frappe.log_error(
            message=f"Complex query error: {e}\n\nSQL: {sql}\n\n{frappe.get_traceback()}",
            title="Jive Complex Query Error"
        )
        return json.dumps({"error": f"Query failed: {str(e)}", "traceback": frappe.get_traceback()})


@tool
def helpdesk_query(question: str) -> str:
    """
    Answer how-to questions about ERPNext and Frappe.
    This tool provides guidance on using the system.
    
    Args:
        question: The user's question about ERPNext/Frappe
    
    Returns:
        A helpful response about how to use the system.
    """
    # This is a placeholder - the actual helpdesk logic is handled
    # in the process_helpdesk_query function with full LLM support
    return json.dumps({
        "success": True,
        "message": "Use process_helpdesk_query for full helpdesk support"
    })


def get_available_tools():
    """Returns a list of all available tools for the agent."""
    return [
        describe_doctype,
        multi_doctype_query,
        get_document_count,
        get_document,
        aggregate_query,
        complex_query,
        helpdesk_query
    ]
