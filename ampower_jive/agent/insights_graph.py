"""
Insights Agent Graph
LangGraph agent for creating charts and dashboards in Frappe Insights.
LLM-FIRST APPROACH - Uses AI to understand all queries properly.
"""

import json
import re
import frappe
import time
from typing import Optional, Dict, List, Any
from ..utils.followup_suggestions import append_followup_prompt
from ..utils.agent_prompt_defaults import build_insights_fallback_prompt
from ..utils.context_aware import build_context_aware_prompt
from ..utils.prompt_provider import get_prompt_provider


# Try to import langchain - will fail gracefully if not installed
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    ChatOpenAI = None
    HumanMessage = AIMessage = SystemMessage = ToolMessage = None

from .insights_tools import (
    INSIGHTS_TOOLS,
    is_insights_installed,
    get_insights_version,
    get_site_data_source,
    get_base_url,
    execute_sql_safely,
    generate_chart_summary,
    generate_prescriptive_analysis,
    format_chart_for_display,
    build_chart_config,
    select_best_chart_type,
    parse_sql_columns
)

from .llm_pool import (
    get_cached_llm,
    compress_history,
    get_llm_pool,
    get_llm_pool,
    prune_langraph_messages
)
from ..utils.tokens import TokenUsageCallbackHandler
from ..utils.interaction_logger import InteractionLogger


# Cache for version info (avoid repeated DB calls)
_version_cache = {"info": None, "timestamp": None}


def _get_cached_version():
    """Get cached version info, refresh if older than 5 minutes."""
    now = time.time()
    if _version_cache["info"] and _version_cache["timestamp"] and (now - _version_cache["timestamp"]) < 300:
        return _version_cache["info"]
    _version_cache["info"] = get_insights_version()
    _version_cache["timestamp"] = now
    return _version_cache["info"]


# Fast path patterns for common chart requests (no LLM needed)
# Order matters - more specific patterns first
INSIGHTS_FAST_PATTERNS = [
    # Pareto patterns (most specific first)
    (r'pareto.*item|item.*pareto|80.?20.*item', {
        'title': 'Item Pareto Analysis',
        'sql': """SELECT si.item_code AS item, SUM(si.amount) AS sales 
FROM `tabSales Invoice Item` si JOIN `tabSales Invoice` s ON si.parent=s.name 
WHERE s.docstatus=1 AND s.posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY si.item_code ORDER BY sales DESC LIMIT 15""",
        'chart_type': 'Bar'
    }),
    (r'pareto.*customer|customer.*pareto|80.?20.*customer|pareto\s+analysis', {
        'title': 'Customer Pareto Analysis', 
        'sql': """SELECT customer, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY customer ORDER BY revenue DESC LIMIT 15""",
        'chart_type': 'Bar'
    }),
    # Trend patterns
    (r'monthly\s+(sales|revenue)\s*(trend|chart)?|sales.*month.*trend', {
        'title': 'Monthly Sales Trend',
        'sql': """SELECT DATE_FORMAT(posting_date, '%%Y-%%m') AS month, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY month ORDER BY month""",
        'chart_type': 'Line'
    }),
    (r'purchase.*month|monthly.*purchase', {
        'title': 'Monthly Purchase Trend',
        'sql': """SELECT DATE_FORMAT(posting_date, '%%Y-%%m') AS month, SUM(grand_total) AS amount 
FROM `tabPurchase Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY month ORDER BY month""",
        'chart_type': 'Line'
    }),
    (r'daily\s+(sales|revenue)', {
        'title': 'Daily Sales',
        'sql': """SELECT posting_date AS date, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) 
GROUP BY posting_date ORDER BY posting_date""",
        'chart_type': 'Line'
    }),
    # Top N patterns
    (r'top\s+(sell|best\s*sell).*item|best.*items|top.*items\s*by\s*(sale|revenue)', {
        'title': 'Top Selling Items',
        'sql': """SELECT si.item_code AS item, SUM(si.amount) AS sales 
FROM `tabSales Invoice Item` si JOIN `tabSales Invoice` s ON si.parent=s.name 
WHERE s.docstatus=1 AND s.posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY si.item_code ORDER BY sales DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
    (r'top\s*customer|best.*customer|biggest.*customer|customer.*revenue|show.*customer', {
        'title': 'Top Customers by Revenue',
        'sql': """SELECT customer, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY customer ORDER BY revenue DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
    (r'top\s+supplier|best.*supplier|biggest.*supplier', {
        'title': 'Top Suppliers by Purchase',
        'sql': """SELECT supplier, SUM(grand_total) AS amount 
FROM `tabPurchase Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY supplier ORDER BY amount DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
    # Sales breakdown patterns
    (r'sales\s+by\s+customer|customer.*sales|revenue.*customer', {
        'title': 'Sales by Customer',
        'sql': """SELECT customer, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY customer ORDER BY revenue DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
    (r'sales\s+by\s+(item|product)|item.*sales|product.*revenue', {
        'title': 'Sales by Item',
        'sql': """SELECT si.item_code AS item, SUM(si.amount) AS sales 
FROM `tabSales Invoice Item` si JOIN `tabSales Invoice` s ON si.parent=s.name 
WHERE s.docstatus=1 AND s.posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY si.item_code ORDER BY sales DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
    (r'sales\s+by\s+territory|territory.*sales', {
        'title': 'Sales by Territory',
        'sql': """SELECT territory, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY territory ORDER BY revenue DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
    # Inventory patterns
    (r'(stock|inventory)\s+(value|by\s+warehouse)|warehouse.*stock', {
        'title': 'Stock Value by Warehouse',
        'sql': """SELECT warehouse, SUM(stock_value) AS value 
FROM `tabBin` WHERE actual_qty > 0 
GROUP BY warehouse ORDER BY value DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
    (r'stock\s+by\s+item|item.*stock|inventory.*item', {
        'title': 'Stock by Item',
        'sql': """SELECT item_code, SUM(actual_qty) AS qty, SUM(stock_value) AS value 
FROM `tabBin` WHERE actual_qty > 0 
GROUP BY item_code ORDER BY value DESC LIMIT 15""",
        'chart_type': 'Bar'
    }),
    # Order patterns
    (r'pending.*order|open.*order|outstanding.*order', {
        'title': 'Pending Sales Orders',
        'sql': """SELECT customer, COUNT(*) AS order_count, SUM(grand_total) AS total 
FROM `tabSales Order` WHERE docstatus=1 AND status NOT IN ('Completed', 'Closed', 'Cancelled') 
GROUP BY customer ORDER BY total DESC LIMIT 10""",
        'chart_type': 'Bar'
    }),
]


def _match_insights_fast_pattern(message: str) -> Optional[Dict]:
    """Check if message matches a fast pattern for instant chart creation."""
    msg_lower = message.lower()
    
    # Skip fast path for complex/custom queries that need LLM
    # Use word boundaries to avoid false matches (e.g., 'custom' matching 'customer')
    skip_patterns = [
        r'\bcompare\b', r'\bvs\b', r'\bversus\b', r'\bbetween\b',
        r'\bcustom\s+query', r'\bspecific\b', r'\bparticular\b',
        r'\bthis year\b', r'\blast year\b', r'\bthis month\b',
        r'\bfrom\s+\d', r'\bsince\s+\d', r'\buntil\s+\d',
    ]
    for skip_pattern in skip_patterns:
        if re.search(skip_pattern, msg_lower):
            return None
    
    for pattern, config in INSIGHTS_FAST_PATTERNS:
        if re.search(pattern, msg_lower):
            return config
    return None


def _create_chart_direct(title: str, sql: str, chart_type: str) -> dict:
    """Create chart directly - fastest path. Always creates new workbook."""
    try:
        data_source = get_site_data_source()
        if not data_source:
            return {"error": "No active data source", "success": False}
        
        base_url = get_base_url()
        
        # Execute SQL to validate
        data_result = execute_sql_safely(sql, limit=30)
        if data_result.get("error"):
            return {"error": data_result["error"], "success": False}
        
        if not data_result.get("rows"):
            return {"error": "No data returned", "success": False}
        
        # Parse columns
        columns = parse_sql_columns(sql)
        if not columns and data_result.get("columns"):
            columns = [
                {"name": col, "is_measure": i > 0, "data_type": "Integer" if i > 0 else "String"}
                for i, col in enumerate(data_result["columns"])
            ]
        
        config = build_chart_config(chart_type, columns)
        
        # ALWAYS create new workbook, query, and chart
        workbook = frappe.get_doc({"doctype": "Insights Workbook", "title": title})
        workbook.insert(ignore_permissions=True)
        
        operations = [{"type": "sql", "data_source": data_source, "raw_sql": sql.strip()}]
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
        
        # Generate response data
        summary = generate_chart_summary(data_result, chart_type, title)
        analysis = generate_prescriptive_analysis(data_result, chart_type, title)
        chart_display_data = format_chart_for_display(chart_type, data_result.get("columns", []), data_result.get("rows", []), title)
        
        return {
            "success": True,
            "title": title,
            "chart_type": chart_type,
            "workbook_id": workbook.name,
            "chart_id": chart.name,
            "query_id": query.name,
            "url": f"{base_url}/insights/workbook/{workbook.name}/chart/{chart.name}",
            "workbook_url": f"{base_url}/insights/workbook/{workbook.name}",
            "summary": summary,
            "analysis": analysis,
            "chart_render_data": chart_display_data
        }
        
    except Exception as e:
        frappe.log_error(
            message=f"Direct chart creation error: {e}\n\n{frappe.get_traceback()}",
            title="Insights Agent"
        )
        return {"error": str(e), "success": False}


def _build_fast_response(result: dict) -> str:
    """Build formatted response from chart result."""
    if not result.get("success"):
        return f"❌ Could not create chart: {result.get('error', 'Unknown error')}"
    
    workbook_id = result.get("workbook_id")
    title = result.get('title', 'Chart')
    
    # Show workbook ID prominently to confirm new creation
    response = f"📊 **{title}**\n"
    response += f"*(New workbook: `{workbook_id}`)*\n\n"
    
    if result.get("summary"):
        response += result["summary"] + "\n\n"
    
    if result.get("analysis"):
        response += result["analysis"] + "\n\n"
    
    response += f"📈 [View in Insights]({result.get('url')})"
    
    # Add delete option
    if workbook_id:
        response += f"\n\n---\n🗑️ *Don't need this? Say \"delete workbook {workbook_id}\" to remove it.*"
    
    return response


class InsightsAgent:
    """Agent for creating visualizations in Frappe Insights. LLM-FIRST approach."""
    
    def __init__(self):
        self.tools = INSIGHTS_TOOLS
        self.langchain_available = LANGCHAIN_AVAILABLE
        self._prompt_provider = get_prompt_provider()
    
    def _get_llm(self):
        """Get LLM from pool (lazy, cached)."""
        # Note: We don't pass callbacks here because they are attached at invoke time
        # to ensure the handler has the correct user context.
        return get_cached_llm(
            purpose="insights",
            temperature=0.1,
            timeout=30,  # Reduced timeout for faster responses
            add_token_callback=False
        )
    
    def _build_system_prompt(self, context_prompt: str = "") -> str:
        """Comprehensive system prompt for understanding any query."""
        prompt = self._prompt_provider.get_prompt("insights") or build_insights_fallback_prompt()
        base_prompt = append_followup_prompt(prompt)

        if context_prompt:
            base_prompt = append_followup_prompt(f"{base_prompt}\n\nCONTEXT AWARE NOTES:\n{context_prompt}")
        return base_prompt

        prompt = self._prompt_provider.get_prompt("insights")

        if prompt:
            base_prompt = append_followup_prompt(prompt)
        else:
            base_prompt = append_followup_prompt("""You are a chart creator for ERPNext. When the user asks for data visualization, IMMEDIATELY call `create_quick_chart` with the appropriate SQL.

## CRITICAL: ALWAYS call `create_quick_chart` directly. Do NOT call check_insights_status or any other tool first.

## YOUR TASK
1. UNDERSTAND what the user is asking for (what entity, what metric, what time period)
2. Generate the correct SQL query
3. IMMEDIATELY call `create_quick_chart` with: title, sql, chart_type

## ERPNEXT SCHEMA - IMPORTANT!

### Sales Analysis
- **Sales Invoice** (`tabSales Invoice`): Header with customer, grand_total, posting_date, docstatus
- **Sales Invoice Item** (`tabSales Invoice Item`): Line items with item_code, qty, amount, rate. JOIN via parent=name
- To analyze ITEMS: Query `tabSales Invoice Item` joined with `tabSales Invoice`
- To analyze CUSTOMERS: Query `tabSales Invoice` directly

### Purchase Analysis  
- **Purchase Invoice** (`tabPurchase Invoice`): Header with supplier, grand_total, posting_date
- **Purchase Invoice Item** (`tabPurchase Invoice Item`): Line items with item_code, qty, amount

### Stock/Inventory
- **Bin** (`tabBin`): Current stock with item_code, warehouse, actual_qty, stock_value
- **Stock Ledger Entry** (`tabStock Ledger Entry`): Stock movements

### Other Common Tables
- **Customer** (`tabCustomer`): Customer master
- **Supplier** (`tabSupplier`): Supplier master
- **Item** (`tabItem`): Item master with item_code, item_name, item_group
- **Sales Order** (`tabSales Order`): Sales orders
- **Purchase Order** (`tabPurchase Order`): Purchase orders
- **Employee** (`tabEmployee`): Employee data

## SQL RULES
1. Use backticks for table names: `tabSales Invoice`
2. ALWAYS add WHERE docstatus=1 for transactional documents (invoices, orders)
3. Use column aliases with AS: SELECT customer AS customer_name
4. Default time range: Last 12 months using DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
5. LIMIT 10-20 for grouped results
6. ORDER BY the metric DESC for "top" queries, ASC for "bottom/least"

## UNDERSTANDING USER INTENT

### Pareto/80-20 Analysis
- "Pareto of items" or "item pareto" → Analyze ITEMS by sales amount
- "Pareto of customers" or "customer pareto" → Analyze CUSTOMERS by revenue
- Just "pareto analysis" → ASK which entity they want to analyze

### Top/Best Analysis
- "Top selling items" → Items by quantity sold
- "Top items by revenue" → Items by sales amount
- "Top customers" → Customers by total revenue

### Trends
- "Monthly sales trend" → Group by month, Line chart
- "Daily sales" → Group by date, Line chart

### Comparisons
- "Sales by customer" → Group by customer, Bar chart
- "Sales by item" → Group by item_code, Bar chart

## EXAMPLE QUERIES

1. **Item Pareto (Top items by sales)**:
```sql
SELECT si.item_code AS item, SUM(si.amount) AS sales 
FROM `tabSales Invoice Item` si 
JOIN `tabSales Invoice` s ON si.parent=s.name 
WHERE s.docstatus=1 AND s.posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY si.item_code 
ORDER BY sales DESC 
LIMIT 10
```

2. **Customer Pareto (Top customers by revenue)**:
```sql
SELECT customer AS customer, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` 
WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY customer 
ORDER BY revenue DESC 
LIMIT 10
```

3. **Monthly Sales Trend**:
```sql
SELECT DATE_FORMAT(posting_date, '%Y-%m') AS month, SUM(grand_total) AS revenue 
FROM `tabSales Invoice` 
WHERE docstatus=1 AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY month 
ORDER BY month
```

4. **Top Selling Items by Quantity**:
```sql
SELECT si.item_code AS item, SUM(si.qty) AS quantity_sold 
FROM `tabSales Invoice Item` si 
JOIN `tabSales Invoice` s ON si.parent=s.name 
WHERE s.docstatus=1 AND s.posting_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH) 
GROUP BY si.item_code 
ORDER BY quantity_sold DESC 
LIMIT 10
```""")

        if context_prompt:
            return base_prompt + "\n\n=== CURRENT PAGE CONTEXT ===\n" + context_prompt
        return base_prompt

    def _handle_delete_workbook(self, message: str) -> dict:
        """Handle delete workbook commands."""
        msg_lower = message.lower().strip()
        
        # Patterns for delete commands
        delete_patterns = [
            r"delete\s+workbook\s+([a-zA-Z0-9_-]+)",
            r"remove\s+workbook\s+([a-zA-Z0-9_-]+)",
            r"delete\s+([a-zA-Z0-9_-]+)\s+workbook",
        ]
        
        workbook_id = None
        for pattern in delete_patterns:
            match = re.search(pattern, msg_lower)
            if match:
                workbook_id = match.group(1)
                break
        
        if not workbook_id:
            return None
        
        # Try to find workbook
        actual_workbook = frappe.db.get_value(
            "Insights Workbook", 
            {"name": ["like", workbook_id]}, 
            "name"
        )
        
        if not actual_workbook:
            if frappe.db.exists("Insights Workbook", workbook_id):
                actual_workbook = workbook_id
        
        if not actual_workbook:
            return {
                "response": f"❌ Workbook '{workbook_id}' not found.",
                "error": True,
                "insights_installed": True
            }
        
        try:
            workbook_title = frappe.db.get_value("Insights Workbook", actual_workbook, "title") or actual_workbook
            
            # Get and delete associated resources
            charts = frappe.get_all("Insights Chart v3", filters={"workbook": actual_workbook}, pluck="name")
            queries = frappe.get_all("Insights Query v3", filters={"workbook": actual_workbook}, pluck="name")
            dashboards = frappe.get_all("Insights Dashboard v3", filters={"workbook": actual_workbook}, pluck="name")
            
            for chart in charts:
                frappe.delete_doc("Insights Chart v3", chart, ignore_permissions=True, force=True)
            for dashboard in dashboards:
                frappe.delete_doc("Insights Dashboard v3", dashboard, ignore_permissions=True, force=True)
            for query in queries:
                frappe.delete_doc("Insights Query v3", query, ignore_permissions=True, force=True)
            
            frappe.delete_doc("Insights Workbook", actual_workbook, ignore_permissions=True, force=True)
            frappe.db.commit()
            
            return {
                "response": f"✅ **Workbook Deleted**\n\nDeleted: **{workbook_title}** (`{actual_workbook}`)\n- Charts: {len(charts)}\n- Queries: {len(queries)}",
                "error": False,
                "insights_installed": True
            }
            
        except Exception as e:
            frappe.log_error(f"Delete Workbook Error: {e}", "Insights Agent")
            return {
                "response": f"❌ Error deleting workbook: {str(e)}",
                "error": True,
                "insights_installed": True
            }

    def process(
        self, message: str, history: list = None, session_id: str = None, context_payload: Any = None, context_aware: bool = False) -> dict:
        """Process request using fast path or LLM."""
        
        start_time = time.time()
        interaction_logger = InteractionLogger("insights")
        frappe.local.jive_insights_context = {
            "message": message,
            "context_aware": context_aware,
            "context_payload": context_payload or {},
        }

        try:
            # Check version
            version_info = _get_cached_version()
            
            if not version_info.get("installed"):
                return {
                    "response": "**Frappe Insights is not installed**\n\nPlease install it with:\n```bash\nbench get-app insights\nbench --site your-site install-app insights\n```",
                    "error": True,
                    "insights_installed": False
                }
            
            if not version_info.get("supported"):
                v = version_info.get("version", "unknown")
                return {
                    "response": f"**Insights v3 required** (found: {v})\n\nPlease upgrade.",
                    "error": True,
                    "insights_installed": True
                }
            
            # Check for delete command first
            delete_result = self._handle_delete_workbook(message)
            if delete_result:
                return delete_result
            
            # FAST PATH: Check for pattern match (no LLM needed)
            fast_match = _match_insights_fast_pattern(message)
            if fast_match and not history:  # Only use fast path for standalone queries
                result = _create_chart_direct(
                    title=fast_match['title'],
                    sql=fast_match['sql'],
                    chart_type=fast_match['chart_type']
                )
                
                if result.get("success"):
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    response_text = _build_fast_response(result)
                    
                    interaction_logger.log(
                        request_data={"message": message, "fast_path": True, "tool": "create_quick_chart_direct"},
                        response_data=response_text[:5000],
                        model="insights_model_fast",
                        status="success",
                        processing_time_ms=processing_time_ms,
                        session_id=session_id,
                    )
                    
                    return {
                        "response": response_text,
                        "created_urls": [{"url": result.get("url"), "title": result.get("title"), "workbook_id": result.get("workbook_id")}],
                        "chart_render_data": [result.get("chart_render_data")] if result.get("chart_render_data") else [],
                        "workbook_id": result.get("workbook_id"),
                        "insights_installed": True,
                        "response_time_ms": processing_time_ms
                    }
                else:
                    # Log error for fast path
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    interaction_logger.log(
                        request_data={"message": message, "fast_path": True, "tool": "create_quick_chart_direct"},
                        model="insights_model_fast",
                        status="error",
                        error=Exception(result.get("error", "Unknown error")),
                        error_traceback=result.get("traceback", ""),
                        processing_time_ms=processing_time_ms,
                        session_id=session_id,
                    )
                # If fast path failed, fall through to LLM
            
            # STANDARD PATH: Use LLM to understand and process the query
            llm = self._get_llm()
            
            if not llm:
                return {
                    "response": "**OpenAI API key not configured.**\n\nPlease configure your API key in Jive Config to use the Insights agent.",
                    "error": True,
                    "insights_installed": True
                }
            
            # Only bind create_quick_chart tool - keep it simple and focused
            from .insights_tools import create_quick_chart
            llm_with_tools = llm.bind_tools([create_quick_chart])
            
            # Compress history
            compressed_history = compress_history(history or [], max_messages=3, max_chars=600)
            
            context_prompt = ""
            if context_aware and context_payload:
                try:
                    context_prompt = build_context_aware_prompt(context_payload, message, history=compressed_history)
                except Exception:
                    context_prompt = ""
            
            # Build messages
            system_prompt = (self._build_system_prompt(context_prompt) or "").strip()
            messages = [SystemMessage(content=system_prompt)]
            
            # Add history context
            if compressed_history:
                for m in compressed_history[-3:]:
                    role = m.get('role', 'user')
                    content = m.get('content') or ''
                    if role == 'user':
                        messages.append(HumanMessage(content=content))
                    elif role == 'assistant':
                        messages.append(AIMessage(content=content))
            
            messages.append(HumanMessage(content=message))
            
            try:
                # Create callback handler for this specific request to capture current user
                callbacks = [TokenUsageCallbackHandler("insights")]
                llm_start = time.time()
                response = llm_with_tools.invoke(messages, config={"callbacks": callbacks})
            except Exception as e:
                processing_time_ms = int((time.time() - start_time) * 1000)
                error_str = str(e).lower()

                # Log error interaction
                log_messages = [{"role": "user", "content": message}]
                interaction_logger.log(
                    request_data={"messages": log_messages, "model": "insights_model"},
                    model="insights_model",
                    status="timeout" if 'timeout' in error_str else "error",
                    error=e,
                    error_traceback=frappe.get_traceback(),
                    processing_time_ms=processing_time_ms,
                    session_id=session_id,
                )

                if 'timeout' in error_str:
                    return {
                        "response": "⏱️ Request timed out. Please try again.",
                        "error": True,
                        "insights_installed": True
                    }
                return {
                    "response": f"❌ Error: {str(e)[:100]}",
                    "error": True,
                    "insights_installed": True
                }
            
            # Log messages for interaction logging
            log_messages = [{"role": "user", "content": message}]
            processing_time_ms = int((time.time() - llm_start) * 1000)

            # No tool calls - return LLM response (might be a clarifying question)
            if not response.tool_calls:
                response_content = response.content or "I couldn't understand your query. Could you please rephrase it?"
                interaction_logger.log(
                    request_data={"messages": log_messages, "model": "insights_model"},
                    response_data=response_content,
                    model="insights_model",
                    status="success",
                    processing_time_ms=processing_time_ms,
                    session_id=session_id,
                )
                return {
                    "response": response_content,
                    "insights_installed": True,
                    "response_time_ms": int((time.time() - start_time) * 1000)
                }
            
            # Execute tool call
            tool_call = response.tool_calls[0]
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args", {})
            
            result = self._execute_tool(tool_name, tool_args)
            
            if isinstance(result, dict) and result.get("success"):
                url = result.get("chart_url") or result.get("url")
                title = result.get("chart_title") or result.get("title", "Chart")
                workbook_id = result.get("workbook_id")
                
                final_response = _build_fast_response({
                    "success": True,
                    "title": title,
                    "url": url,
                    "workbook_id": workbook_id,
                    "summary": result.get("summary"),
                    "analysis": result.get("analysis")
                })
                
                interaction_logger.log(
                    request_data={"messages": log_messages, "model": "insights_model", "tool": tool_name},
                    response_data=final_response[:5000],
                    model="insights_model",
                    status="success",
                    processing_time_ms=processing_time_ms,
                    session_id=session_id,
                )
                
                return {
                    "response": final_response,
                    "created_urls": [{"url": url, "title": title, "workbook_id": workbook_id}],
                    "chart_render_data": [result.get("chart_render_data")] if result.get("chart_render_data") else [],
                    "workbook_id": workbook_id,
                    "insights_installed": True,
                    "response_time_ms": int((time.time() - start_time) * 1000)
                }
            else:
                error = result.get("error", "Chart creation failed") if isinstance(result, dict) else str(result)
                traceback_str = result.get("traceback", "") if isinstance(result, dict) else ""

                # Log error interaction
                interaction_logger.log(
                    request_data={"messages": log_messages, "model": "insights_model"},
                    model="insights_model",
                    status="error",
                    error=Exception(error),
                    error_traceback=traceback_str,
                    processing_time_ms=processing_time_ms,
                    session_id=session_id,
                )

                return {
                    "response": f"❌ {error}\n\nPlease try rephrasing your query.",
                    "error": True,
                    "insights_installed": True
                }
            
        except Exception as e:
            frappe.log_error(
                message=f"InsightsAgent error: {e}\n\n{frappe.get_traceback()}",
                title="Insights Agent"
            )

            # Log error interaction
            processing_time_ms = int((time.time() - start_time) * 1000)
            interaction_logger.log(
                request_data={"message": message},
                model="insights_model",
                status="error",
                error=e,
                error_traceback=frappe.get_traceback(),
                processing_time_ms=processing_time_ms,
                session_id=session_id,
            )

            return {
                "response": f"Error: {str(e)}",
                "error": True,
                "insights_installed": True
            }
    
    def _execute_tool(self, tool_name: str, tool_args: dict):
        """Execute a tool by name."""
        from .insights_tools import create_quick_chart
        
        if tool_name == "create_quick_chart":
            try:
                return create_quick_chart.invoke(tool_args)
            except Exception as e:
                frappe.log_error(
                    message=f"Tool execution error: {e}\n\n{frappe.get_traceback()}",
                    title="Insights Agent"
                )
                return {"error": str(e), "success": False, "traceback": frappe.get_traceback()}
        
        # Fallback to checking all tools
        for tool in self.tools:
            if tool.name == tool_name:
                try:
                    return tool.invoke(tool_args)
                except Exception as e:
                    return {"error": str(e), "success": False, "traceback": frappe.get_traceback()}
        return {"error": f"Tool '{tool_name}' not found", "success": False}


# Singleton instance
_insights_agent = None


def get_insights_agent():
    """Factory function to get an InsightsAgent instance (singleton)."""
    global _insights_agent
    if _insights_agent is None:
        _insights_agent = InsightsAgent()
    return _insights_agent
