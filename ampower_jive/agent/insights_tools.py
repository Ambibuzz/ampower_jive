"""
Insights Agent Tools
Tools for creating charts, queries, and dashboards in Frappe Insights.
Optimized for reliable chart creation with data preview and summary.
"""

import json
import re
from typing import Any, Dict, List, Optional

import frappe

# Try to import langchain tools, provide fallback if not installed
try:
    from langchain_core.tools import tool
except ImportError:
    # Create a no-op decorator if langchain is not installed
    def tool(func):
        func.name = func.__name__
        return func


def is_insights_installed() -> bool:
    """Check if Frappe Insights app is installed."""
    try:
        installed_apps = frappe.get_installed_apps()
        return "insights" in installed_apps
    except Exception:
        return False


def get_insights_version() -> dict:
    """
    Check Insights installation and version.
    Returns dict with version info and which doctypes are available.
    """
    try:
        if not is_insights_installed():
            return {"installed": False, "error": "Insights app is not installed"}
        
        # Check which version of Insights is installed by checking available doctypes
        has_v3 = frappe.db.exists("DocType", "Insights Query v3")
        has_v2 = frappe.db.exists("DocType", "Insights Query")
        has_workbook = frappe.db.exists("DocType", "Insights Workbook")
        has_chart_v3 = frappe.db.exists("DocType", "Insights Chart v3")
        has_data_source_v3 = frappe.db.exists("DocType", "Insights Data Source v3")
        
        if has_v3 and has_workbook and has_chart_v3:
            return {
                "installed": True,
                "version": "v3",
                "has_query_v3": True,
                "has_workbook": True,
                "has_chart_v3": True,
                "supported": True
            }
        elif has_v2:
            return {
                "installed": True,
                "version": "v2",
                "has_query_v3": False,
                "supported": False,
                "error": "Insights v2 detected. Jive requires Insights v3 (with Workbooks). Please upgrade Insights."
            }
        else:
            return {
                "installed": True,
                "version": "unknown",
                "supported": False,
                "error": "Insights is installed but required DocTypes (Insights Query v3, Insights Workbook) are missing. Please run 'bench migrate' or reinstall Insights."
            }
    except Exception as e:
        return {"installed": False, "error": str(e), "traceback": frappe.get_traceback()}


def get_site_data_source() -> str:
    """Get the site database data source name."""
    try:
        ds = frappe.db.get_value(
            "Insights Data Source v3",
            {"is_site_db": 1, "status": "Active"},
            "name"
        )
        return ds
    except Exception:
        return None


def get_base_url() -> str:
    """Get the site base URL."""
    return frappe.utils.get_url()


def _normalize_sql_context_hint(context_hint: Any) -> Dict[str, Any]:
    """Extract a compact set of SQL-relevant hints from the active context."""
    if not context_hint:
        return {}

    if isinstance(context_hint, str):
        try:
            context_hint = json.loads(context_hint)
        except Exception:
            return {}

    if not isinstance(context_hint, dict):
        return {}

    hint: Dict[str, Any] = {}
    candidate_keys = (
        "doctype",
        "label",
        "title",
        "name",
        "page_name",
        "page_title",
        "report_name",
        "report_title",
        "workspace_name",
        "source_label",
        "page_kind",
        "source_type",
        "page_source",
    )

    def _add_values(source: Dict[str, Any]) -> None:
        for key in candidate_keys:
            value = source.get(key)
            if value not in (None, "", [], {}):
                hint.setdefault(key, value)

    _add_values(context_hint)

    for nested_key in ("metadata", "page_snapshot", "dashboard_snapshot", "current_doc"):
        nested = context_hint.get(nested_key)
        if isinstance(nested, dict):
            _add_values(nested)

    return hint


def _table_name_variants(value: Any) -> List[str]:
    """Return likely table/doctypes names derived from a user-facing label."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return []

    variants: List[str] = []
    seen = set()

    def add(candidate: str) -> None:
        candidate = str(candidate or "").strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        variants.append(candidate)

    add(raw_value)
    add(re.sub(r"\s*-\s*", "-", raw_value))
    add(re.sub(r"\s*-\s*", " - ", raw_value))
    add(re.sub(r"\s+", " ", raw_value))
    add(re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", raw_value)))

    if raw_value.startswith("tab"):
        add(raw_value[3:])

    return variants


def _resolve_doctype_from_hint(value: Any, context_hint: Any = None) -> Optional[str]:
    """Resolve a DocType name from a table-like hint."""
    candidates = []
    if value not in (None, "", [], {}):
        candidates.extend(_table_name_variants(value))

    normalized_context = _normalize_sql_context_hint(context_hint)
    for key in ("doctype", "label", "title", "name", "page_name", "page_title", "report_name", "report_title", "source_label"):
        if normalized_context.get(key) not in (None, "", [], {}):
            candidates.extend(_table_name_variants(normalized_context.get(key)))

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.startswith("tab"):
            candidate = candidate[3:]
        if candidate and frappe.db.exists("DocType", candidate):
            return candidate

    return None


def _replace_sql_table_reference(sql: str, source_name: str, target_name: str) -> str:
    """Rewrite a table reference in FROM/JOIN clauses while preserving aliases."""
    if not sql or not source_name or not target_name:
        return sql

    pattern = re.compile(
        rf"(?P<clause>\b(?:FROM|JOIN|UPDATE|INTO)\s+)(?P<table>`?{re.escape(source_name)}`?)(?P<alias>\s+(?:AS\s+)?[A-Za-z_][A-Za-z0-9_]*)?",
        re.IGNORECASE,
    )

    def _repl(match: re.Match) -> str:
        alias = match.group("alias") or ""
        return f"{match.group('clause')}`{target_name}`{alias}"

    return pattern.sub(_repl, sql)


def _collect_sql_table_candidates(context_hint: Any = None) -> List[str]:
    """Build a list of table-like identifiers from the current request context."""
    normalized = _normalize_sql_context_hint(context_hint)
    candidates: List[str] = []
    seen = set()

    def add(value: Any) -> None:
        for variant in _table_name_variants(value):
            if variant in seen:
                continue
            seen.add(variant)
            candidates.append(variant)

    for key in ("doctype", "label", "title", "name", "page_name", "page_title", "report_name", "report_title", "workspace_name", "source_label", "page_source"):
        add(normalized.get(key))

    return candidates


def normalize_insights_sql(sql: str, context_hint: Any = None) -> str:
    """Normalize common report/page labels into real `tab...` table names."""
    if not sql:
        return sql

    rewritten = sql
    candidates = _collect_sql_table_candidates(context_hint)

    for candidate in sorted(candidates, key=len, reverse=True):
        doctype_name = _resolve_doctype_from_hint(candidate, context_hint=context_hint)
        if not doctype_name:
            continue
        rewritten = _replace_sql_table_reference(rewritten, candidate, f"tab{doctype_name}")

    return rewritten


def _extract_missing_table_name(error_message: str) -> str:
    """Pull the missing table identifier out of a SQL error message."""
    if not error_message:
        return ""

    match = re.search(r"Table '([^']+)' doesn't exist", error_message)
    if not match:
        return ""

    table_name = match.group(1).split(".")[-1].strip("`")
    return table_name


def generate_prescriptive_analysis(data: dict, chart_type: str, title: str) -> str:
    """
    Generate prescriptive analysis, recommendations, and follow-up suggestions.
    """
    rows = data.get("rows", [])
    columns = data.get("columns", [])
    
    if not rows or len(columns) < 2:
        return ""
    
    insights = []
    label_col = columns[0]
    value_col = columns[1]
    
    # Extract values - find the numeric column dynamically
    values = []
    labels = []
    
    # Try to detect which column is numeric
    for row in rows:
        # Try value_col first
        val = row.get(value_col, 0)
        label = row.get(label_col, "")
        
        # If value_col is not numeric, try to find a numeric column
        try:
            if val is not None and str(val).replace('.', '').replace('-', '').isdigit():
                values.append(float(val))
                labels.append(str(label))
            elif isinstance(val, (int, float)):
                values.append(float(val))
                labels.append(str(label))
            else:
                # Try swapping - maybe label_col is actually numeric
                try:
                    values.append(float(label) if label else 0)
                    labels.append(str(val))
                except (ValueError, TypeError):
                    # Try to find any numeric value in the row
                    found_numeric = False
                    for col in columns:
                        col_val = row.get(col)
                        try:
                            if col_val is not None and col != label_col:
                                float_val = float(col_val)
                                values.append(float_val)
                                labels.append(str(row.get(label_col, "")))
                                found_numeric = True
                                break
                        except (ValueError, TypeError):
                            continue
                    if not found_numeric:
                        values.append(0)
                        labels.append(str(label))
        except (ValueError, TypeError):
            values.append(0)
            labels.append(str(label))
    
    if not values:
        return ""
    
    total = sum(values)
    avg = total / len(values) if values else 0
    max_val = max(values) if values else 0
    min_val = min(values) if values else 0
    max_idx = values.index(max_val) if max_val in values else 0
    min_idx = values.index(min_val) if min_val in values else 0
    
    # Generate insights based on data patterns
    insights.append("💡 **Quick Insights:**")
    
    # Top performer insight
    if max_val > 0 and labels:
        top_pct = (max_val / total * 100) if total > 0 else 0
        insights.append(f"• **{labels[max_idx]}** leads with {top_pct:.1f}% of the total")
    
    # Concentration analysis
    if len(values) >= 3 and total > 0:
        top_3_sum = sum(sorted(values, reverse=True)[:3])
        top_3_pct = (top_3_sum / total * 100)
        if top_3_pct > 70:
            insights.append(f"• Top 3 account for {top_3_pct:.0f}% - consider diversification")
        elif top_3_pct < 40:
            insights.append(f"• Well-distributed across {len(values)} items ({top_3_pct:.0f}% in top 3)")
    
    # Gap analysis
    if max_val > 0 and min_val > 0 and len(values) > 1:
        gap_ratio = max_val / min_val if min_val > 0 else 0
        if gap_ratio > 10:
            insights.append(f"• Large gap between top ({labels[max_idx]}) and bottom ({labels[min_idx]})")
    
    # Trend suggestion for time-based data
    title_lower = title.lower()
    if any(word in title_lower for word in ['monthly', 'daily', 'weekly', 'trend', 'time']):
        if len(values) >= 3:
            recent_avg = sum(values[-3:]) / 3
            older_avg = sum(values[:3]) / 3 if len(values) >= 6 else avg
            if recent_avg > older_avg * 1.1:
                insights.append("• 📈 Upward trend detected - momentum is positive")
            elif recent_avg < older_avg * 0.9:
                insights.append("• 📉 Downward trend - investigate recent changes")
            else:
                insights.append("• ➡️ Stable performance over the period")
    
    # Recommendation
    if len(insights) > 1:
        insights.append("")
        if "sales" in title_lower or "revenue" in title_lower:
            insights.append("**Recommendation:** Focus on replicating success factors from top performers to boost overall revenue.")
        elif "customer" in title_lower:
            insights.append("**Recommendation:** Strengthen relationships with top customers while developing growth strategies for mid-tier accounts.")
        elif "item" in title_lower or "product" in title_lower:
            insights.append("**Recommendation:** Analyze top-performing products for expansion opportunities and review underperformers.")
        else:
            insights.append("**Recommendation:** Use these insights to prioritize actions on high-impact areas.")
        
    return "\n".join(insights) if len(insights) > 1 else ""


def execute_sql_safely(sql: str, limit: int = 100) -> dict:
    """
    Execute SQL query safely and return results.
    Returns dict with columns, rows, and error if any.
    """
    try:
        # Ensure we have LIMIT to prevent huge results
        sql_upper = sql.upper().strip()
        if "LIMIT" not in sql_upper:
            sql = f"{sql.rstrip().rstrip(';')} LIMIT {limit}"
        
        # Execute the query
        results = frappe.db.sql(sql, as_dict=True)
        
        if not results:
            return {"columns": [], "rows": [], "row_count": 0}
        
        # Get column names from first row
        columns = list(results[0].keys()) if results else []
        
        return {
            "columns": columns,
            "rows": results[:limit],
            "row_count": len(results)
        }
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "row_count": 0, "traceback": frappe.get_traceback()}


def generate_chart_summary(data: dict, chart_type: str, title: str) -> str:
    """Generate a human-readable summary of the chart data."""
    rows = data.get("rows", [])
    columns = data.get("columns", [])
    
    if not rows:
        return "No data available for this chart."
    
    summary_parts = []
    
    # Add title
    summary_parts.append(f"**{title}**")
    
    # Add data count
    row_count = len(rows)
    summary_parts.append(f"Showing {row_count} data points")
    
    # For Number charts, just show the values
    if chart_type == "Number" and rows:
        values = []
        for col in columns:
            val = rows[0].get(col)
            if val is not None:
                # Format large numbers
                if isinstance(val, (int, float)):
                    if val >= 1000000:
                        formatted = f"{val/1000000:.2f}M"
                    elif val >= 1000:
                        formatted = f"{val/1000:.1f}K"
                    else:
                        formatted = f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"
                    values.append(f"{col}: {formatted}")
                else:
                    values.append(f"{col}: {val}")
        if values:
            summary_parts.append(" | ".join(values))
        return "\n".join(summary_parts)
    
    # For other charts, show top entries
    if len(columns) >= 2 and rows:
        label_col = columns[0]
        value_col = columns[1]
        
        top_entries = []
        for row in rows[:5]:
            label = row.get(label_col, "N/A")
            value = row.get(value_col, 0)
            
            # Format the value
            if isinstance(value, (int, float)):
                if value >= 1000000:
                    formatted_val = f"{value/1000000:.2f}M"
                elif value >= 1000:
                    formatted_val = f"{value/1000:.1f}K"
                else:
                    formatted_val = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
            else:
                formatted_val = str(value)
            
            top_entries.append(f"  • {label}: {formatted_val}")
        
        if top_entries:
            summary_parts.append("Top entries:")
            summary_parts.extend(top_entries)
            
            if row_count > 5:
                summary_parts.append(f"  ... and {row_count - 5} more")
    
    return "\n".join(summary_parts)


def format_chart_for_display(chart_type: str, columns: list, rows: list, title: str) -> dict:
    """
    Format chart data for frontend inline rendering.
    Returns a structure that can be used by the frontend to render a mini chart.
    """
    if not rows:
        return None
    
    # Prepare data for rendering
    chart_data = {
        "type": chart_type.lower(),
        "title": title,
        "columns": columns,
        "labels": [],
        "values": [],
        "datasets": []
    }
    
    if len(columns) >= 2:
        label_col = columns[0]
        value_col = columns[1]
        
        chart_data["labels"] = [str(row.get(label_col, "")) for row in rows[:20]]
        chart_data["values"] = [row.get(value_col, 0) for row in rows[:20]]
        
        # For multi-series charts
        if len(columns) > 2:
            for col in columns[1:]:
                chart_data["datasets"].append({
                    "label": col,
                    "data": [row.get(col, 0) for row in rows[:20]]
                })
        else:
            chart_data["datasets"].append({
                "label": value_col,
                "data": chart_data["values"]
            })
    
    return chart_data


def parse_sql_columns(sql: str) -> list:
    """
    Parse SQL SELECT statement to extract column names/aliases.
    Returns list of column info dicts with name and whether it's likely a measure.
    """
    columns = []
    sql_upper = sql.upper()
    
    # Extract the SELECT ... FROM portion
    select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
    if not select_match:
        return columns
    
    select_part = select_match.group(1)
    
    # Split by comma, but handle nested functions
    depth = 0
    current_col = ""
    for char in select_part + ",":
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            col = current_col.strip()
            if col:
                columns.append(col)
            current_col = ""
            continue
        current_col += char
    
    result = []
    for col in columns:
        col = col.strip()
        col_upper = col.upper()
        
        # Check for alias (AS keyword or just space-separated)
        alias_match = re.search(r'\s+AS\s+[`"\']?(\w+)[`"\']?\s*$', col, re.IGNORECASE)
        if alias_match:
            name = alias_match.group(1)
        else:
            # Check for space-separated alias
            space_match = re.search(r'\)\s+[`"\']?(\w+)[`"\']?\s*$', col)
            if space_match:
                name = space_match.group(1)
            else:
                # Just take the column name
                name_match = re.search(r'[`"\']?(\w+)[`"\']?\s*$', col)
                name = name_match.group(1) if name_match else col
        
        # Check if it's an aggregate (likely a measure)
        is_measure = bool(re.search(r'\b(SUM|COUNT|AVG|MIN|MAX)\s*\(', col_upper))
        
        # Check data type hint from function
        data_type = "Integer" if is_measure else "String"
        if "DATE" in col_upper or "MONTH" in col_upper or "YEAR" in col_upper:
            data_type = "Date"
        
        result.append({
            "name": name,
            "is_measure": is_measure,
            "data_type": data_type
        })
    
    return result


def build_chart_config(chart_type: str, columns: list) -> dict:
    """
    Build the proper chart config based on chart type and available columns.
    
    Args:
        chart_type: The chart type (Bar, Line, Donut, Number, Table, etc.)
        columns: List of column dicts from parse_sql_columns
    """
    if not columns:
        return {}
    
    # Separate dimensions and measures
    dimensions = [c for c in columns if not c.get("is_measure")]
    measures = [c for c in columns if c.get("is_measure")]
    
    # If no explicit measures, treat numeric-looking columns as measures
    if not measures and len(columns) > 1:
        measures = columns[1:]
        dimensions = columns[:1]
    
    # Ensure we have at least one of each
    if not dimensions and columns:
        dimensions = [columns[0]]
    if not measures and len(columns) > 1:
        measures = [columns[-1]]
    elif not measures and columns:
        measures = [{"name": columns[0]["name"], "is_measure": True, "data_type": "Integer"}]
    
    # Build dimension object
    def make_dimension(col):
        return {
            "column_name": col["name"],
            "dimension_name": col["name"],
            "data_type": col.get("data_type", "String")
        }
    
    # Build measure object
    def make_measure(col):
        return {
            "column_name": col["name"],
            "measure_name": col["name"],
            "data_type": col.get("data_type", "Integer"),
            "aggregation": "sum"
        }
    
    # Build config based on chart type
    if chart_type in ["Donut", "Pie"]:
        return {
            "label_column": make_dimension(dimensions[0]) if dimensions else None,
            "value_column": make_measure(measures[0]) if measures else None,
            "legend_position": "bottom",
            "max_slices": 10,
            "show_inline_labels": True
        }
    
    elif chart_type == "Funnel":
        return {
            "label_column": make_dimension(dimensions[0]) if dimensions else None,
            "value_column": make_measure(measures[0]) if measures else None,
            "label_position": "right"
        }
    
    elif chart_type in ["Bar", "Line", "Row"]:
        series = []
        for m in measures[:5]:  # Max 5 series
            series.append({
                "measure": make_measure(m)
            })
        
        return {
            "x_axis": {
                "dimension": make_dimension(dimensions[0]) if dimensions else None
            },
            "y_axis": {
                "series": series,
                "show_data_labels": True
            }
        }
    
    elif chart_type == "Number":
        number_cols = []
        for m in measures[:3]:  # Max 3 numbers
            number_cols.append(make_measure(m))
        
        return {
            "number_columns": number_cols,
            "number_column_options": [{"shorten_numbers": True} for _ in number_cols],
            "comparison": False,
            "sparkline": False,
            "shorten_numbers": True
        }
    
    elif chart_type == "Table":
        rows = [make_dimension(d) for d in dimensions[:5]]
        values = [make_measure(m) for m in measures[:5]]
        
        return {
            "rows": rows,
            "columns": [],
            "values": values,
            "show_row_totals": True,
            "show_column_totals": True
        }
    
    else:
        # Default fallback
        return {
            "label_column": make_dimension(dimensions[0]) if dimensions else None,
            "value_column": make_measure(measures[0]) if measures else None
        }


def select_best_chart_type(sql: str, columns: list) -> str:
    """
    Intelligently select the best chart type based on the SQL query and columns.
    """
    sql_upper = sql.upper()
    
    num_dimensions = len([c for c in columns if not c.get("is_measure")])
    num_measures = len([c for c in columns if c.get("is_measure")])
    
    # Check for time-series data
    has_date = any(c.get("data_type") == "Date" for c in columns)
    has_group_by = "GROUP BY" in sql_upper
    has_order_by = "ORDER BY" in sql_upper
    has_limit = "LIMIT" in sql_upper
    
    # Single aggregate value -> Number
    if num_dimensions == 0 and num_measures >= 1:
        return "Number"
    
    # Time series -> Line
    if has_date and has_group_by:
        return "Line"
    
    # Few categories with values -> Donut (for comparison)
    if has_limit and num_dimensions == 1 and num_measures == 1:
        # Check limit value
        limit_match = re.search(r'LIMIT\s+(\d+)', sql_upper)
        if limit_match and int(limit_match.group(1)) <= 10:
            return "Donut"
    
    # Default to Bar for grouped data
    if has_group_by:
        return "Bar"
    
    # Table for complex data
    if num_dimensions > 2 or num_measures > 2:
        return "Table"
    
    return "Bar"


@tool
def check_insights_status() -> dict:
    """
    Check if Frappe Insights is installed and configured.
    Returns installation status, version info, and available data sources.
    Always call this first before creating any visualizations.
    """
    try:
        # First check version compatibility
        version_info = get_insights_version()
        
        if not version_info.get("installed"):
            return {
                "installed": False,
                "supported": False,
                "message": "Frappe Insights is not installed. Please install it first:\n```\nbench get-app insights\nbench --site your-site install-app insights\n```"
            }
        
        if not version_info.get("supported"):
            return {
                "installed": True,
                "supported": False,
                "version": version_info.get("version", "unknown"),
                "message": version_info.get("error", "Unsupported Insights version")
            }
        
        # Get data sources
        try:
            data_sources = frappe.get_all(
                "Insights Data Source v3",
                filters={"status": "Active"},
                fields=["name", "title", "database_type", "is_site_db"]
            )
        except Exception:
            data_sources = []
        
        site_ds = get_site_data_source()
        
        # Get workbooks
        try:
            workbooks = frappe.get_all(
                "Insights Workbook",
                fields=["name", "title"],
                order_by="creation desc",
                limit=10
            )
        except Exception:
            workbooks = []
        
        if not site_ds:
            return {
                "installed": True,
                "supported": True,
                "version": "v3",
                "site_data_source": None,
                "message": "Insights is installed but no active data source found. Please configure a data source in Insights settings."
            }
        
        return {
            "installed": True,
            "supported": True,
            "version": "v3",
            "site_data_source": site_ds,
            "data_sources": data_sources,
            "workbooks": workbooks,
            "message": "Insights v3 is ready. Use site_data_source for queries."
        }
    except Exception as e:
        return {"installed": False, "supported": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def list_available_tables() -> dict:
    """
    List available ERPNext tables that can be queried.
    Returns common DocType tables that exist in the database.
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed"}
        
        data_source = get_site_data_source()
        if not data_source:
            return {"error": "No active data source found"}
        
        # Get tables from Insights
        tables = frappe.get_all(
            "Insights Table v3",
            filters={"data_source": data_source},
            fields=["table", "label"],
            limit=100
        )
        
        # Common ERPNext tables for reference
        common_tables = [
            "tabSales Invoice", "tabSales Invoice Item",
            "tabPurchase Invoice", "tabPurchase Invoice Item", 
            "tabSales Order", "tabSales Order Item",
            "tabPurchase Order", "tabPurchase Order Item",
            "tabCustomer", "tabSupplier", "tabItem",
            "tabStock Entry", "tabStock Ledger Entry",
            "tabJournal Entry", "tabPayment Entry",
            "tabEmployee", "tabSalary Slip",
            "tabLead", "tabOpportunity", "tabQuotation"
        ]
        
        return {
            "data_source": data_source,
            "total_tables": len(tables),
            "common_tables": common_tables,
            "all_tables": [t.get("table") for t in tables[:50]]
        }
    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@tool
def get_table_columns(table_name: str) -> dict:
    """
    Get columns of a specific table for building queries.
    
    Args:
        table_name: Table name like 'tabSales Invoice' or DocType name like 'Sales Invoice'
    """
    try:
        # Normalize table name
        if not table_name.startswith("tab"):
            table_name = f"tab{table_name}"
        
        # Get columns from database schema
        columns = frappe.db.sql("""
            SELECT COLUMN_NAME as name, DATA_TYPE as type
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = %s 
            AND TABLE_SCHEMA = DATABASE()
            ORDER BY ORDINAL_POSITION
        """, (table_name,), as_dict=True)
        
        if not columns:
            # Try without 'tab' prefix
            doctype_name = table_name.replace("tab", "")
            if frappe.db.exists("DocType", doctype_name):
                meta = frappe.get_meta(doctype_name)
                columns = [
                    {"name": f.fieldname, "type": f.fieldtype, "label": f.label}
                    for f in meta.fields
                    if f.fieldtype not in ["Section Break", "Column Break", "Tab Break", "HTML", "Button"]
                ]
        
        return {
            "table": table_name,
            "columns": columns[:50] if columns else [],
            "message": f"Found {len(columns)} columns" if columns else "Table not found"
        }
    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@tool
def create_workbook(title: str) -> dict:
    """
    Create a new Insights workbook. Workbooks contain queries and charts.
    
    Args:
        title: Title for the workbook (e.g., "Sales Analysis")
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed"}
        
        workbook = frappe.get_doc({
            "doctype": "Insights Workbook",
            "title": title
        })
        workbook.insert(ignore_permissions=True)
        frappe.db.commit()
        
        base_url = get_base_url()
        
        return {
            "success": True,
            "workbook_id": workbook.name,
            "title": workbook.title,
            "url": f"{base_url}/insights/workbook/{workbook.name}"
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def create_sql_query(
    workbook_id: str,
    title: str,
    sql: str
) -> dict:
    """
    Create a SQL query in Insights.
    
    Args:
        workbook_id: The workbook ID to add query to
        title: Title for the query (e.g., "Monthly Sales")
        sql: SQL SELECT query (e.g., "SELECT customer, SUM(grand_total) as total FROM `tabSales Invoice` WHERE docstatus=1 GROUP BY customer ORDER BY total DESC LIMIT 10")
    
    Example SQL queries:
    - Sales by customer: SELECT customer, SUM(grand_total) as total FROM `tabSales Invoice` WHERE docstatus=1 GROUP BY customer
    - Monthly revenue: SELECT DATE_FORMAT(posting_date, '%Y-%m') as month, SUM(grand_total) as revenue FROM `tabSales Invoice` WHERE docstatus=1 GROUP BY month ORDER BY month
    - Top items: SELECT item_code, SUM(qty) as qty_sold FROM `tabSales Invoice Item` GROUP BY item_code ORDER BY qty_sold DESC LIMIT 10
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed"}
        
        if not frappe.db.exists("Insights Workbook", workbook_id):
            return {"error": f"Workbook '{workbook_id}' not found"}
        
        data_source = get_site_data_source()
        if not data_source:
            return {"error": "No active data source found"}
        
        # Build operations JSON for native SQL query
        operations = [
            {
                "type": "sql",
                "data_source": data_source,
                "raw_sql": sql.strip()
            }
        ]
        
        # Create query
        query = frappe.get_doc({
            "doctype": "Insights Query v3",
            "title": title,
            "workbook": workbook_id,
            "operations": json.dumps(operations),
            "is_native_query": 1,
            "use_live_connection": 1
        })
        query.insert(ignore_permissions=True)
        frappe.db.commit()
        
        base_url = get_base_url()
        
        return {
            "success": True,
            "query_id": query.name,
            "title": query.title,
            "workbook_id": workbook_id,
            "url": f"{base_url}/insights/workbook/{workbook_id}",
            "message": "Query created. Now create a chart using this query_id."
        }
    except Exception as e:
        frappe.log_error(
            message=f"Create Query Error: {e}\n\n{frappe.get_traceback()}",
            title="Insights Agent"
        )
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def create_chart(
    workbook_id: str,
    query_id: str,
    title: str,
    chart_type: str,
    label_column: str = None,
    value_column: str = None
) -> dict:
    """
    Create a chart from a query with proper label and value configuration.
    Returns data preview and summary for inline display.
    
    Args:
        workbook_id: The workbook ID
        query_id: The query ID to visualize
        title: Title for the chart
        chart_type: One of: 'Bar', 'Line', 'Donut', 'Number', 'Table', 'Row', 'Funnel'
        label_column: The column name to use for labels/x-axis (e.g., 'customer', 'month')
        value_column: The column name to use for values/y-axis (e.g., 'total', 'revenue')
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed", "success": False}
        
        if not frappe.db.exists("Insights Workbook", workbook_id):
            return {"error": f"Workbook '{workbook_id}' not found", "success": False}
        
        if not frappe.db.exists("Insights Query v3", query_id):
            return {"error": f"Query '{query_id}' not found", "success": False}
        
        # Try to get SQL from query to parse columns and execute for data preview
        query_doc = frappe.get_doc("Insights Query v3", query_id)
        columns = []
        sql = None
        data_result = {"columns": [], "rows": [], "row_count": 0}
        
        if query_doc.operations:
            try:
                ops = json.loads(query_doc.operations)
                for op in ops:
                    if op.get("type") == "sql" and op.get("raw_sql"):
                        sql = op["raw_sql"]
                        columns = parse_sql_columns(sql)
                        # Execute to get data preview
                        data_result = execute_sql_safely(sql, limit=50)
                        break
            except Exception:
                pass
        
        # If label/value provided, use them; otherwise use parsed columns
        if label_column and value_column:
            columns = [
                {"name": label_column, "is_measure": False, "data_type": "String"},
                {"name": value_column, "is_measure": True, "data_type": "Integer"}
            ]
        
        # Build chart config
        config = build_chart_config(chart_type, columns)
        
        # Create chart
        chart = frappe.get_doc({
            "doctype": "Insights Chart v3",
            "title": title,
            "workbook": workbook_id,
            "query": query_id,
            "chart_type": chart_type,
            "config": json.dumps(config)
        })
        chart.insert(ignore_permissions=True)
        frappe.db.commit()
        
        base_url = get_base_url()
        
        # Generate summary and display data
        summary = generate_chart_summary(data_result, chart_type, title)
        chart_display_data = format_chart_for_display(
            chart_type,
            data_result.get("columns", []),
            data_result.get("rows", []),
            title
        )
        
        workbook_url = f"{base_url}/insights/workbook/{workbook_id}"
        chart_url = f"{base_url}/insights/workbook/{workbook_id}/chart/{chart.name}"
        
        return {
            "success": True,
            "chart_id": chart.name,
            "title": chart.title,
            "chart_type": chart_type,
            "workbook_id": workbook_id,
            "config": config,
            "workbook_url": workbook_url,
            "chart_url": chart_url,
            "url": chart_url,
            # Data for summary and display
            "summary": summary,
            "data_preview": {
                "columns": data_result.get("columns", []),
                "rows": data_result.get("rows", [])[:10],
                "total_rows": data_result.get("row_count", 0)
            },
            "chart_render_data": chart_display_data,
            "message": f"Chart '{title}' created successfully."
        }
    except Exception as e:
        frappe.log_error(f"Create Chart Error: {e}", "Insights Agent")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def create_dashboard(
    workbook_id: str,
    title: str,
    chart_ids: list = None
) -> dict:
    """
    Create a dashboard to display charts.
    
    Args:
        workbook_id: The workbook ID
        title: Title for the dashboard
        chart_ids: Optional list of chart IDs to include
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed"}
        
        if not frappe.db.exists("Insights Workbook", workbook_id):
            return {"error": f"Workbook '{workbook_id}' not found"}
        
        # Build items from charts
        items = []
        if chart_ids:
            for i, chart_id in enumerate(chart_ids):
                if frappe.db.exists("Insights Chart v3", chart_id):
                    items.append({
                        "type": "chart",
                        "chart": chart_id,
                        "x": (i % 2) * 6,  # 2 columns
                        "y": (i // 2) * 6,
                        "w": 6,
                        "h": 6
                    })
        
        # Create dashboard
        dashboard = frappe.get_doc({
            "doctype": "Insights Dashboard v3",
            "title": title,
            "workbook": workbook_id,
            "items": json.dumps(items) if items else "[]"
        })
        dashboard.insert(ignore_permissions=True)
        frappe.db.commit()
        
        base_url = get_base_url()
        
        return {
            "success": True,
            "dashboard_id": dashboard.name,
            "title": dashboard.title,
            "workbook_id": workbook_id,
            "dashboard_url": f"{base_url}/insights/workbook/{workbook_id}/dashboard/{dashboard.name}",
            "url": f"{base_url}/insights/workbook/{workbook_id}/dashboard/{dashboard.name}",
            "message": f"Dashboard '{title}' created."
        }
    except Exception as e:
        frappe.log_error(
            message=f"Create Dashboard Error: {e}\n\n{frappe.get_traceback()}",
            title="Insights Agent"
        )
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def create_quick_chart(
    title: str,
    sql: str,
    chart_type: str = None,
    label_column: str = None,
    value_column: str = None
) -> dict:
    """
    Quick way to create a chart. ALWAYS creates a new workbook, query, and chart.
    Returns data preview, summary, and prescriptive analysis.
    
    Args:
        title: Title for the chart
        sql: SQL SELECT query (first column = label, second = value)
        chart_type: 'Bar', 'Line', 'Donut', 'Number', 'Table', 'Row' (auto-selects if not specified)
        label_column: Optional label column override
        value_column: Optional value column override
    """
    try:
        request_context = getattr(frappe.local, "jive_insights_context", None)

        # Skip version check here - already done by InsightsAgent
        data_source = get_site_data_source()
        if not data_source:
            return {"error": "No active data source found. Please configure a data source in Insights settings.", "success": False}
        
        base_url = get_base_url()
        
        # ALWAYS create new workbook, query, and chart
        # Execute SQL to validate and get data
        normalized_sql = normalize_insights_sql(sql, request_context)
        data_result = execute_sql_safely(normalized_sql, limit=30)

        if data_result.get("error"):
            missing_table_name = _extract_missing_table_name(data_result.get("error", ""))
            if missing_table_name:
                retry_context = dict(request_context or {})
                retry_context.setdefault("doctype", missing_table_name)
                retry_context.setdefault("label", missing_table_name)
                retry_sql = normalize_insights_sql(sql, retry_context)
                if retry_sql != normalized_sql:
                    data_result = execute_sql_safely(retry_sql, limit=30)
                    if not data_result.get("error"):
                        normalized_sql = retry_sql

        if data_result.get("error"):
            return {"success": False, "error": f"SQL Error: {data_result['error']}", "sql": normalized_sql}
        
        if not data_result.get("rows"):
            return {"success": False, "error": "Query returned no data.", "sql": normalized_sql}
        
        # Parse columns
        columns = parse_sql_columns(normalized_sql)
        if not columns and data_result.get("columns"):
            columns = [
                {"name": col, "is_measure": i > 0, "data_type": "Integer" if i > 0 else "String"}
                for i, col in enumerate(data_result["columns"])
            ]
        
        if label_column and value_column:
            columns = [
                {"name": label_column, "is_measure": False, "data_type": "String"},
                {"name": value_column, "is_measure": True, "data_type": "Integer"}
            ]
        
        # Auto-select chart type
        if not chart_type:
            chart_type = select_best_chart_type(normalized_sql, columns)
        
        # Build chart config
        config = build_chart_config(chart_type, columns)
        
        # Create workbook, query, and chart in one go
        workbook = frappe.get_doc({"doctype": "Insights Workbook", "title": f"{title}"})
        workbook.insert(ignore_permissions=True)
        
        operations = [{"type": "sql", "data_source": data_source, "raw_sql": normalized_sql.strip()}]
        query = frappe.get_doc({
            "doctype": "Insights Query v3",
            "title": title,
            "workbook": workbook.name,
            "operations": json.dumps(operations),
            "is_native_query": 1,
            "use_live_connection": 1
        })
        query.insert(ignore_permissions=True)
        
        chart = frappe.get_doc({
            "doctype": "Insights Chart v3",
            "title": title,
            "workbook": workbook.name,
            "query": query.name,
            "chart_type": chart_type,
            "config": json.dumps(config)
        })
        chart.insert(ignore_permissions=True)
        frappe.db.commit()
        
        # Generate summary and prescriptive analysis
        summary = generate_chart_summary(data_result, chart_type, title)
        analysis = generate_prescriptive_analysis(data_result, chart_type, title)
        chart_display_data = format_chart_for_display(
            chart_type, data_result.get("columns", []), data_result.get("rows", []), title
        )
        
        chart_url = f"{base_url}/insights/workbook/{workbook.name}/chart/{chart.name}"
        
        return {
            "success": True,
            "workbook_id": workbook.name,
            "query_id": query.name,
            "chart_id": chart.name,
            "chart_title": title,
            "chart_type": chart_type,
            "columns_detected": [c["name"] for c in columns],
            "workbook_url": f"{base_url}/insights/workbook/{workbook.name}",
            "chart_url": chart_url,
            "url": chart_url,
            "summary": summary,
            "analysis": analysis,
            "data_preview": {
                "columns": data_result.get("columns", []),
                "rows": data_result.get("rows", [])[:10],
                "total_rows": data_result.get("row_count", 0)
            },
            "chart_render_data": chart_display_data,
            "message": f"Chart '{title}' created successfully with {chart_type} type."
        }
    except Exception as e:
        frappe.log_error(
            message=f"Quick Chart Error: {e}\n\n{frappe.get_traceback()}",
            title="Insights Agent"
        )
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def list_existing_workbooks() -> dict:
    """
    List existing workbooks in Insights.
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed"}
        
        workbooks = frappe.get_all(
            "Insights Workbook",
            fields=["name", "title", "creation", "modified"],
            order_by="modified desc",
            limit=20
        )
        
        base_url = get_base_url()
        for wb in workbooks:
            wb["url"] = f"{base_url}/insights/workbook/{wb['name']}"
        
        return {
            "workbooks": workbooks,
            "total": len(workbooks)
        }
    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@tool
def delete_workbook(workbook_id: str) -> dict:
    """
    Delete an Insights workbook and all its associated charts and queries.
    
    Args:
        workbook_id: The workbook ID/name to delete
    
    Returns:
        Success or error message
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed", "success": False}
        
        if not workbook_id:
            return {"error": "Workbook ID is required", "success": False}
        
        if not frappe.db.exists("Insights Workbook", workbook_id):
            return {"error": f"Workbook '{workbook_id}' not found", "success": False}
        
        # Get associated charts and queries before deleting
        charts = frappe.get_all("Insights Chart v3", filters={"workbook": workbook_id}, pluck="name")
        queries = frappe.get_all("Insights Query v3", filters={"workbook": workbook_id}, pluck="name")
        dashboards = frappe.get_all("Insights Dashboard v3", filters={"workbook": workbook_id}, pluck="name")
        
        # Delete charts first
        for chart in charts:
            frappe.delete_doc("Insights Chart v3", chart, ignore_permissions=True, force=True)
        
        # Delete dashboards
        for dashboard in dashboards:
            frappe.delete_doc("Insights Dashboard v3", dashboard, ignore_permissions=True, force=True)
        
        # Delete queries
        for query in queries:
            frappe.delete_doc("Insights Query v3", query, ignore_permissions=True, force=True)
        
        # Delete workbook
        frappe.delete_doc("Insights Workbook", workbook_id, ignore_permissions=True, force=True)
        frappe.db.commit()
        
        return {
            "success": True,
            "message": f"Workbook '{workbook_id}' deleted successfully",
            "deleted": {
                "workbook": workbook_id,
                "charts": len(charts),
                "queries": len(queries),
                "dashboards": len(dashboards)
            }
        }
        
    except Exception as e:
        frappe.log_error(
            message=f"Delete Workbook Error: {e}\n\n{frappe.get_traceback()}",
            title="Insights Agent"
        )
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def preview_query_data(sql: str) -> dict:
    """
    Preview the results of a SQL query WITHOUT creating any chart.
    Use this to verify your query works and returns expected data before creating a chart.
    
    Args:
        sql: SQL SELECT query to preview
    
    Returns:
        Preview of data including columns, sample rows, and row count.
        Also returns any SQL errors if the query is invalid.
    """
    try:
        if not is_insights_installed():
            return {"error": "Insights is not installed", "success": False}
        
        # Execute the query
        result = execute_sql_safely(sql, limit=20)
        
        if result.get("error"):
            return {
                "success": False,
                "error": f"SQL Error: {result['error']}",
                "suggestion": "Check table names (use `tabDocType` format), column names, and SQL syntax."
            }
        
        if not result.get("rows"):
            return {
                "success": True,
                "warning": "Query returned no data. Check your WHERE conditions or if data exists.",
                "columns": result.get("columns", []),
                "rows": [],
                "row_count": 0
            }
        
        # Format data nicely
        columns = result.get("columns", [])
        rows = result.get("rows", [])
        
        return {
            "success": True,
            "columns": columns,
            "rows": rows[:10],  # Return up to 10 sample rows
            "row_count": len(rows),
            "data_summary": f"Query returned {len(rows)} rows with columns: {', '.join(columns)}"
        }
        
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def get_sample_data(table_name: str, limit: int = 5) -> dict:
    """
    Get sample data from a table to understand its structure and content.
    Use this to see what data exists before writing queries.
    
    Args:
        table_name: Table name like 'tabSales Invoice' or DocType name like 'Sales Invoice'
        limit: Number of sample rows to return (default 5)
    """
    try:
        # Normalize table name
        if not table_name.startswith("tab"):
            table_name = f"tab{table_name}"
        
        # Get sample data
        sql = f"SELECT * FROM `{table_name}` WHERE docstatus = 1 ORDER BY creation DESC LIMIT {min(limit, 10)}"
        result = execute_sql_safely(sql, limit=min(limit, 10))
        
        if result.get("error"):
            # Try without docstatus filter
            sql = f"SELECT * FROM `{table_name}` ORDER BY creation DESC LIMIT {min(limit, 10)}"
            result = execute_sql_safely(sql, limit=min(limit, 10))
        
        if result.get("error"):
            return {
                "success": False,
                "error": f"Could not get sample data: {result['error']}",
                "table": table_name
            }
        
        # Filter out internal columns for cleaner display
        internal_cols = ["_user_tags", "_comments", "_assign", "_liked_by", "_seen"]
        columns = [c for c in result.get("columns", []) if c not in internal_cols]
        
        # Filter rows to only include filtered columns
        filtered_rows = []
        for row in result.get("rows", []):
            filtered_rows.append({k: v for k, v in row.items() if k in columns})
        
        return {
            "success": True,
            "table": table_name,
            "columns": columns[:20],  # Limit to 20 columns for readability
            "sample_rows": filtered_rows[:limit],
            "row_count": len(result.get("rows", [])),
            "message": f"Found {len(result.get('rows', []))} rows. Showing {min(limit, len(result.get('rows', [])))} samples."
        }
        
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


@tool
def check_data_exists(
    table_name: str,
    conditions: str = None
) -> dict:
    """
    Check if data exists in a table with optional conditions.
    Use this to verify data exists before creating charts.
    
    Args:
        table_name: Table name like 'tabSales Invoice' or 'Sales Invoice'
        conditions: Optional WHERE conditions (without WHERE keyword), e.g. "docstatus=1 AND posting_date >= '2024-01-01'"
    """
    try:
        # Normalize table name
        if not table_name.startswith("tab"):
            table_name = f"tab{table_name}"
        
        # Build count query
        sql = f"SELECT COUNT(*) as count FROM `{table_name}`"
        if conditions:
            sql += f" WHERE {conditions}"
        
        result = execute_sql_safely(sql, limit=1)
        
        if result.get("error"):
            return {
                "success": False,
                "error": f"Could not check data: {result['error']}",
                "table": table_name
            }
        
        count = result.get("rows", [{}])[0].get("count", 0)
        
        return {
            "success": True,
            "table": table_name,
            "conditions": conditions,
            "count": count,
            "has_data": count > 0,
            "message": f"Found {count} records in {table_name}" + (f" with conditions: {conditions}" if conditions else "")
        }
        
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


# Tool registry for the Insights agent
INSIGHTS_TOOLS = [
    check_insights_status,
    list_available_tables,
    get_table_columns,
    get_sample_data,       # New: Get sample data from tables
    check_data_exists,     # New: Verify data exists
    preview_query_data,    # New: Preview query results
    create_workbook,
    create_sql_query,
    create_chart,
    create_dashboard,
    create_quick_chart,
    list_existing_workbooks,
    delete_workbook        # Delete workbook and associated resources
]
