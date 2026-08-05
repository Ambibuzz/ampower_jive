"""
Jive Agent Graph
FAST data query agent - optimized for speed with direct tool execution.
"""

import frappe
from typing import List, Dict, Any, Optional
import json
import time
import re
from datetime import datetime, timedelta

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from .tools import describe_doctype, multi_doctype_query, get_document_count, get_document, aggregate_query, complex_query
from .llm_pool import get_cached_llm
from .schema_cache import get_schema_cache, get_schema_summary_for_llm, get_allowed_doctypes, get_doctype_schema, _load_doctype_schema
from ..utils.followup_suggestions import append_followup_prompt
from ..utils.agent_prompt_defaults import build_query_fallback_prompt
from ..utils.prompt_provider import get_prompt_provider
from ..utils.tokens import TokenUsageCallbackHandler


# Fast-path patterns for common queries (bypass LLM)
# IMPORTANT: Order matters! Use a list of tuples to maintain specific order
# Aggregate patterns come FIRST (more specific), then list patterns
FAST_PATTERNS = [
    # ===== AGGREGATION PATTERNS (check first - most specific) =====
    
    # Revenue/sales BY customer/item (group by)
    (r'(revenue|sales|total).*(by|per|breakdown|wise)\s*(customer|client)', {
        'tool': 'aggregate_query',
        'args': {'doctype': 'Sales Invoice', 'aggregation': 'SUM', 'field': 'grand_total', 'group_by': 'customer'}
    }),
    (r'(top|best)\s*(customer|client).*(revenue|sales)', {
        'tool': 'aggregate_query',
        'args': {'doctype': 'Sales Invoice', 'aggregation': 'SUM', 'field': 'grand_total', 'group_by': 'customer'}
    }),
    (r'customer.*(wise|breakdown|revenue|sales)', {
        'tool': 'aggregate_query',
        'args': {'doctype': 'Sales Invoice', 'aggregation': 'SUM', 'field': 'grand_total', 'group_by': 'customer'}
    }),
    (r'(revenue|sales).*(by|per)\s*(item|product)', {
        'tool': 'aggregate_query',
        'args': {'doctype': 'Sales Invoice Item', 'aggregation': 'SUM', 'field': 'amount', 'group_by': 'item_code'}
    }),
    
    # SUM queries
    (r'(total|sum).*(revenue|sales|amount|value|invoice)', {
        'tool': 'aggregate_query',
        'args': {'doctype': 'Sales Invoice', 'aggregation': 'SUM', 'field': 'grand_total'}
    }),
    (r'sum.*(invoice|order|sales|record)', {
        'tool': 'aggregate_query',
        'args': {'doctype': 'Sales Invoice', 'aggregation': 'SUM', 'field': 'grand_total'}
    }),
    
    # AVG queries
    (r'(average|avg).*(invoice|order|value|sales)', {
        'tool': 'aggregate_query',
        'args': {'doctype': 'Sales Invoice', 'aggregation': 'AVG', 'field': 'grand_total'}
    }),
    
    # ===== LIST PATTERNS =====
    
    # Sales Invoice patterns
    (r'list\s+\d+\s+(sales\s+)?invoice', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Sales Invoice', 'fields': ['name', 'customer', 'posting_date', 'grand_total', 'status'], 'limit': 10}
    }),
    (r'(show|list|get).*(recent|latest|all)?.*(sales invoice|invoice)s?(?!\s+item)', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Sales Invoice', 'fields': ['name', 'customer', 'posting_date', 'grand_total', 'status'], 'limit': 10}
    }),
    
    # Customer patterns (after aggregation patterns!)
    (r'(show|list|get).*(recent|latest|all)?.*(customer)s?', {
        'tool': 'multi_doctype_query', 
        'args': {'doctype': 'Customer', 'fields': ['name', 'customer_name', 'customer_group', 'territory'], 'limit': 10}
    }),
    
    # Item patterns
    (r'(show|list|get).*(recent|latest|all)?.*(item)s?(?!\s+code)', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Item', 'fields': ['name', 'item_name', 'item_group', 'stock_uom'], 'limit': 10}
    }),
    
    # Count patterns
    (r'(count|how many).*(sales invoice|invoice)', {
        'tool': 'get_document_count',
        'args': {'doctype': 'Sales Invoice'}
    }),
    (r'(count|how many).*(customer)', {
        'tool': 'get_document_count',
        'args': {'doctype': 'Customer'}
    }),
    (r'(count|how many).*(item)', {
        'tool': 'get_document_count',
        'args': {'doctype': 'Item'}
    }),
    
    # Sales Order patterns
    (r'pending.*(order|sales order)', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Sales Order', 'fields': ['name', 'customer', 'transaction_date', 'grand_total', 'status'], 
                 'filters': {'status': ['in', ['To Deliver', 'To Deliver and Bill', 'Draft']]}, 'limit': 10}
    }),
    (r'(show|list|get).*(sales order|order)s?', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Sales Order', 'fields': ['name', 'customer', 'transaction_date', 'grand_total', 'status'], 'limit': 10}
    }),
    
    # Outstanding/Unpaid invoices
    (r'(unpaid|outstanding).*(invoice)', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Sales Invoice', 'fields': ['name', 'customer', 'posting_date', 'grand_total', 'outstanding_amount'],
                 'filters': {'outstanding_amount': ['>', 0], 'docstatus': 1}, 'limit': 10}
    }),
    
    # Top selling items
    (r'(top|best).*(sell|sold|selling).*(item|product)', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Sales Invoice Item', 'fields': ['item_code', 'item_name', 'qty', 'amount'],
                 'limit': 10, 'order_by': 'amount desc'}
    }),
    
    # Error logs
    (r'(error|errors)\s*(log|logs)', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Error Log', 'fields': ['name', 'method', 'error', 'creation'], 
                 'limit': 10, 'order_by': 'creation desc'}
    }),
    (r'(last|recent)\s*\d*\s*(error|errors)', {
        'tool': 'multi_doctype_query',
        'args': {'doctype': 'Error Log', 'fields': ['name', 'method', 'error', 'creation'], 
                 'limit': 10, 'order_by': 'creation desc'}
    }),
]


class JiveAgent:
    """
    FAST data query agent - uses pattern matching + LLM fallback.
    Optimized for quick responses.
    """
    
    def __init__(self):
        self._llm = None
        self._llm_with_tools = None
        self._last_init = 0
        self._init_ttl = 300  # 5 minutes cache
        self._prompt_provider = get_prompt_provider()
        self._tools = [describe_doctype, multi_doctype_query, get_document_count, get_document, aggregate_query, complex_query]
    
    def _get_llm(self, with_tools: bool = True, fast: bool = False):
        """Get LLM with or without tools bound."""
        now = time.time()
        
        # Check if cached LLM is still valid
        if self._llm and (now - self._last_init) < self._init_ttl:
            return self._llm_with_tools if with_tools else self._llm
        
        # Always use gpt-4o-mini for data queries (faster)
        try:
            # Use config provider for API key (supports Jive Core mode)
            from ..utils.config_provider import get_config_provider
            
            provider = get_config_provider()
            api_key = provider.get_api_key()
            
            if not api_key:
                raise ValueError("OpenAI API key not configured")
            
            # Force gpt-4o-mini for speed in data queries
            model = "gpt-4o-mini"
            
            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                temperature=0.1,
                timeout=25,  # Tight timeout
                max_retries=1,
                callbacks=[TokenUsageCallbackHandler("data_query")]
            )
        except Exception as e:
            frappe.log_error(
                message=f"Jive Agent LLM error: {e}\n\n{frappe.get_traceback()}",
                title="Jive Agent Error"
            )
            raise
        
        self._llm = llm
        self._llm_with_tools = llm.bind_tools(self._tools)
        self._last_init = now
        
        return self._llm_with_tools if with_tools else self._llm
    
    def _match_fast_pattern(self, message: str) -> Optional[Dict]:
        """Check if message matches a fast pattern."""
        msg_lower = message.lower()
        
        # SKIP fast path for complex queries that need LLM understanding
        complex_indicators = [
            # JOINs and multi-table
            'join', 'combine', 'with their', 'and their', 'along with',
            'per customer', 'per item', 'each customer', 'each item',
            'which items', 'what items', 'items bought', 'items purchased',
            'purchase frequency', 'order frequency', 'how many times',
            'ranking', 'ranked by', 'correlat', 'relationship',
            'first purchase', 'last purchase', 'first order', 'last order',
            'cross', 'multi-table', 'multiple tables',
            # Analytical/Pareto
            'how many customers', 'how many items', 'contribute', 'pareto',
            '80 percent', '80%', '20 percent', '20%', 'top contributors',
            'cumulative', 'percentage of', 'percent of total', 'share of',
            'breakdown', 'distribution', 'concentration',
            # Comparisons
            'compare', ' vs ', 'versus', 'difference between', 'between',
            # Filters with values (need LLM to parse)
            'over ', 'under ', 'more than', 'less than', 'greater than',
            'above ', 'below ', 'at least', 'at most', 'between',
            'from last', 'in the last', 'past ', 'this month', 'last month',
            'this year', 'last year', 'this week', 'last week',
            # Specific searches
            'find all', 'search for', 'look for', 'filter by',
            'where ', 'with status', 'having',
            # Trends
            'trend', 'over time', 'monthly', 'weekly', 'daily', 'yearly',
            'growth', 'decline', 'change'
        ]
        
        for indicator in complex_indicators:
            if indicator in msg_lower:
                return None  # Let LLM handle with complex_query
        
        # Check for document detail request (e.g., "details of SINV-26-00049")
        detail_match = re.search(r'(detail|info|show|get)\s+(of\s+)?([A-Z]+-\d+-\d+|[A-Z]+-\d+)', message, re.IGNORECASE)
        if detail_match:
            doc_name = detail_match.group(3).upper()
            # Determine doctype from prefix
            doctype = 'Sales Invoice'  # Default
            if doc_name.startswith('SO-') or doc_name.startswith('SAL-ORD'):
                doctype = 'Sales Order'
            elif doc_name.startswith('PO-') or doc_name.startswith('PUR-ORD'):
                doctype = 'Purchase Order'
            elif doc_name.startswith('SINV-') or doc_name.startswith('ACC-SINV'):
                doctype = 'Sales Invoice'
            elif doc_name.startswith('PINV-') or doc_name.startswith('ACC-PINV'):
                doctype = 'Purchase Invoice'
            elif doc_name.startswith('DN-') or doc_name.startswith('MAT-DN'):
                doctype = 'Delivery Note'
            elif doc_name.startswith('CUST-'):
                doctype = 'Customer'
            elif doc_name.startswith('ITEM-'):
                doctype = 'Item'
            
            return {
                'tool': 'get_document',
                'args': {'doctype': doctype, 'name': doc_name}
            }
        
        # Check standard patterns (list of tuples for ordered matching)
        for pattern, config in FAST_PATTERNS:
            if re.search(pattern, msg_lower):
                return config
        
        return None
    
    def _execute_tool(self, tool_name: str, args: Dict) -> str:
        """Execute a tool directly."""
        try:
            if tool_name == 'multi_doctype_query':
                return multi_doctype_query.invoke(args)
            elif tool_name == 'get_document_count':
                return get_document_count.invoke(args)
            elif tool_name == 'get_document':
                return get_document.invoke(args)
            elif tool_name == 'aggregate_query':
                return aggregate_query.invoke(args)
            elif tool_name == 'complex_query':
                return complex_query.invoke(args)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    def _generate_insights(self, data: Dict, doctype: str) -> List[str]:
        """Generate quick data insights without LLM calls."""
        insights = []
        
        try:
            # For grouped aggregate data
            if "group_by" in data and "data" in data:
                records = data.get("data", [])
                if not records:
                    return insights
                
                field = data.get("field", "grand_total")
                agg_key = f"{data.get('aggregation', 'sum').lower()}_{field}"
                values = [r.get(agg_key, 0) or 0 for r in records]
                group_by = data.get("group_by", "group")
                
                if values:
                    total = sum(values)
                    
                    # Top contributor analysis
                    if len(values) >= 3 and total > 0:
                        top_3_sum = sum(sorted(values, reverse=True)[:3])
                        top_3_pct = (top_3_sum / total) * 100
                        insights.append(f"💡 Top 3 {group_by}s contribute **{top_3_pct:.0f}%** of total")
                    
                    # Concentration - if top 1 is dominant
                    if len(values) >= 2 and total > 0:
                        top_val = max(values)
                        top_pct = (top_val / total) * 100
                        if top_pct > 30:
                            top_name = records[values.index(top_val)].get(group_by, 'Top')
                            insights.append(f"📈 **{top_name}** leads with {top_pct:.0f}% share")
                    
                    # Gap analysis
                    if len(values) >= 2:
                        sorted_vals = sorted(values, reverse=True)
                        if sorted_vals[0] > 0 and sorted_vals[-1] > 0:
                            gap_ratio = sorted_vals[0] / sorted_vals[-1]
                            if gap_ratio > 5:
                                insights.append(f"⚠️ Large gap: highest is **{gap_ratio:.1f}x** the lowest")
                
                return insights[:3]
            
            # For list data
            if "data" in data and isinstance(data.get("data"), list):
                records = data.get("data", [])
                if not records or len(records) < 2:
                    return insights
                
                # Find numeric fields to analyze
                numeric_fields = ['grand_total', 'outstanding_amount', 'amount', 'qty', 'rate']
                
                for field in numeric_fields:
                    values = [r.get(field) for r in records if r.get(field) is not None]
                    values = [v for v in values if isinstance(v, (int, float))]
                    
                    if len(values) >= 3:
                        total = sum(values)
                        avg = total / len(values)
                        min_val = min(values)
                        max_val = max(values)
                        
                        # Quick stats
                        if field == 'grand_total':
                            insights.append(f"💰 Total: ₹{total:,.0f} | Avg: ₹{avg:,.0f} | Range: ₹{min_val:,.0f} - ₹{max_val:,.0f}")
                        
                        # Outlier detection
                        if max_val > avg * 3:
                            insights.append(f"📊 Highest value (₹{max_val:,.0f}) is **{max_val/avg:.1f}x** above average")
                        
                        # Outstanding amount warning
                        if field == 'outstanding_amount' and total > 0:
                            insights.append(f"⚠️ Outstanding: ₹{total:,.0f} pending collection")
                        
                        break  # Only analyze first numeric field found
                
                # Status distribution for invoices/orders
                if doctype in ["Sales Invoice", "Sales Order"]:
                    statuses = [r.get('status') for r in records if r.get('status')]
                    if statuses:
                        status_counts = {}
                        for s in statuses:
                            status_counts[s] = status_counts.get(s, 0) + 1
                        
                        # Find dominant status
                        if status_counts:
                            top_status = max(status_counts, key=status_counts.get)
                            top_count = status_counts[top_status]
                            pct = (top_count / len(statuses)) * 100
                            if pct > 50:
                                insights.append(f"📋 {pct:.0f}% are **{top_status}**")
                
                return insights[:3]
            
        except Exception:
            pass  # Fail silently - insights are optional
        
        return insights
    
    def _format_results(self, tool_result: str, query: str) -> str:
        """Format tool results into a human-readable response with insights and suggestions."""
        try:
            data = json.loads(tool_result)
            
            if data.get("error"):
                return f"❌ Error: {data['error']}"
            
            doctype = data.get("doctype", "records")
            
            # Check if this is an AGGREGATE result
            if "aggregation" in data and "result" in data:
                agg = data.get("aggregation", "SUM").upper()
                field = data.get("field", "value")
                result = data.get("result", 0)
                
                # Format based on aggregation type
                if agg == "SUM":
                    lines = [f"📊 **Total {field.replace('_', ' ').title()}**: ₹{result:,.2f}"]
                elif agg == "AVG":
                    lines = [f"📊 **Average {field.replace('_', ' ').title()}**: ₹{result:,.2f}"]
                elif agg == "COUNT":
                    lines = [f"📊 **Count**: {result:,}"]
                elif agg in ["MIN", "MAX"]:
                    lines = [f"📊 **{agg} {field.replace('_', ' ').title()}**: ₹{result:,.2f}"]
                else:
                    lines = [f"📊 **Result**: {result:,.2f}"]
                
                lines.append(f"_Doctype: {doctype}_")
                
                return "\n".join(lines)
            
            # Check if this is a GROUPED aggregate result
            if "aggregation" in data and "group_by" in data and "data" in data:
                agg = data.get("aggregation", "SUM").upper()
                field = data.get("field", "value")
                group_by = data.get("group_by", "group")
                records = data.get("data", [])
                
                lines = [f"📊 **{agg} of {field.replace('_', ' ').title()} by {group_by.replace('_', ' ').title()}**:\n"]
                
                # Determine if field is monetary or count
                is_monetary = field.lower() in ['grand_total', 'amount', 'revenue', 'total', 'outstanding_amount', 'rate']
                
                for rec in records[:15]:
                    group_val = rec.get(group_by, 'N/A')
                    agg_val = rec.get(f"{agg.lower()}_{field}", 0)
                    if is_monetary:
                        lines.append(f"• {group_val}: ₹{agg_val:,.2f}")
                    else:
                        lines.append(f"• {group_val}: {agg_val:,.0f}")
                
                if len(records) > 15:
                    lines.append(f"... and {len(records) - 15} more groups")
                
                # Generate insights for grouped data
                insights = self._generate_insights(data, doctype)
                if insights:
                    lines.append("\n**Key Insights:**")
                    for insight in insights:
                        lines.append(insight)
                
                return "\n".join(lines)
            
            # Check if this is a COMPLEX QUERY result
            if data.get("query_type") == "complex" and "data" in data:
                records = data.get("data", [])
                description = data.get("description", "Query results")
                count = data.get("count", len(records))
                
                if not records:
                    return "No results found for this query."
                
                lines = [f"📊 **{description}** ({count} results):\n"]
                
                # Auto-detect columns from first record
                if records:
                    columns = list(records[0].keys())
                    
                    # Format each record
                    for rec in records[:20]:
                        parts = []
                        for col in columns[:5]:  # Show max 5 columns
                            val = rec.get(col)
                            if val is not None:
                                # Format based on value type
                                if isinstance(val, (int, float)) and col in ['revenue', 'total', 'amount', 'grand_total', 'sum_grand_total']:
                                    parts.append(f"₹{val:,.0f}")
                                elif isinstance(val, (int, float)) and col in ['orders', 'count', 'purchases', 'qty', 'order_count', 'invoice_count']:
                                    parts.append(f"{val:,.0f}")
                                else:
                                    parts.append(str(val))
                        lines.append(f"• {' — '.join(parts)}")
                    
                    if count > 20:
                        lines.append(f"... and {count - 20} more")
                
                # Generate insights for complex query
                insights = self._generate_complex_insights(records)
                if insights:
                    lines.append("\n**Key Insights:**")
                    for insight in insights:
                        lines.append(insight)
                
                return "\n".join(lines)
            
            # Check if this is a count-only response (from get_document_count)
            if "count" in data and "data" not in data:
                count = data.get("count", 0)
                result = f"📊 Found **{count:,}** {doctype} records."
                
                return result
            
            if "data" in data:
                records = data.get("data", [])
                
                # Handle single document result (dict) vs list of records
                if isinstance(records, dict):
                    # Single document - format as details
                    doc = records
                    lines = [f"📄 **{doctype}: {data.get('name', doc.get('name', 'N/A'))}**"]
                    
                    # Key fields to show
                    key_fields = ['customer', 'customer_name', 'posting_date', 'transaction_date', 
                                  'grand_total', 'outstanding_amount', 'status', 'docstatus',
                                  'item_name', 'item_group', 'territory', 'company']
                    
                    for field in key_fields:
                        if field in doc and doc[field] is not None:
                            value = doc[field]
                            if isinstance(value, (int, float)) and field in ['grand_total', 'outstanding_amount']:
                                lines.append(f"• **{field.replace('_', ' ').title()}**: ₹{value:,.2f}")
                            else:
                                lines.append(f"• **{field.replace('_', ' ').title()}**: {value}")
                    
                    # Show items if present (for invoices/orders)
                    if 'items' in doc and isinstance(doc['items'], list):
                        lines.append(f"\n**Items** ({len(doc['items'])} line items):")
                        for item in doc['items'][:5]:
                            if isinstance(item, dict):
                                item_name = item.get('item_name', item.get('item_code', 'N/A'))
                                qty = item.get('qty', 0)
                                amount = item.get('amount', 0)
                                lines.append(f"  • {item_name} — Qty: {qty} — ₹{amount:,.2f}")
                        if len(doc['items']) > 5:
                            lines.append(f"  ... and {len(doc['items']) - 5} more items")
                    
                    return "\n".join(lines)
                
                # List of records
                count = data.get("count", len(records) if isinstance(records, list) else 1)
                
                if not records:
                    result = f"No {doctype} records found with the applied filters."
                    suggestions = [
                        f"Try a broader date range for {doctype}",
                        f"How many {doctype}s are there in total?",
                        f"List all {doctype}s without filters"
                    ]
                    result += "\n\n**Try:**"
                    for s in suggestions[:3]:
                        result += f"\n• {s}"
                    return result
                
                # Format records list
                lines = [f"📋 **{doctype}** ({count} records):"]
                for rec in list(records)[:10]:
                    if not isinstance(rec, dict):
                        continue
                    if doctype == "Sales Invoice":
                        customer = rec.get('customer') or rec.get('customer_name') or 'N/A'
                        total = rec.get('grand_total') or 0
                        status = rec.get('status') or ''
                        lines.append(f"• {rec.get('name')} — {customer} — ₹{total:,.2f} ({status})")
                    elif doctype == "Customer":
                        lines.append(f"• {rec.get('name')} — {rec.get('customer_name', '')} ({rec.get('customer_group', '')})")
                    elif doctype == "Item":
                        lines.append(f"• {rec.get('name')} — {rec.get('item_name', '')} ({rec.get('item_group', '')})")
                    elif doctype == "Sales Order":
                        customer = rec.get('customer') or 'N/A'
                        total = rec.get('grand_total') or 0
                        status = rec.get('status') or ''
                        lines.append(f"• {rec.get('name')} — {customer} — ₹{total:,.2f} ({status})")
                    elif doctype == "Sales Invoice Item":
                        qty = rec.get('qty') or 0
                        amount = rec.get('amount') or 0
                        lines.append(f"• {rec.get('item_code', 'N/A')} — {rec.get('item_name', '')} — Qty: {qty:,.0f} — ₹{amount:,.2f}")
                    elif doctype == "Error Log":
                        method = rec.get('method', 'N/A')
                        error = rec.get('error', '')[:80] + "..." if rec.get('error') and len(rec.get('error', '')) > 80 else rec.get('error', 'N/A')
                        creation = rec.get('creation', '')
                        lines.append(f"• **{rec.get('name')}** — {method}\n  {error}\n  _{creation}_")
                    else:
                        # Generic format
                        vals = [str(v) for k, v in rec.items() if v and k != 'name'][:3]
                        name = rec.get('name', 'N/A')
                        lines.append(f"• {name} — {' — '.join(vals)}" if vals else f"• {name}")
                
                if count > 10:
                    lines.append(f"... and {count - 10} more")
                
                # Generate insights for list data
                insights = self._generate_insights(data, doctype)
                if insights:
                    lines.append("\n**Key Insights:**")
                    for insight in insights:
                        lines.append(insight)
                
                return "\n".join(lines)
            
            return f"Query completed. Results: {str(data)[:500]}"
            
        except Exception as e:
            return f"Query completed but couldn't format results: {str(e)[:100]}"
    
    def _generate_complex_insights(self, records: List[Dict]) -> List[str]:
        """Generate insights for complex query results."""
        insights = []
        
        try:
            if not records or len(records) < 2:
                return insights
            
            # Find numeric columns
            numeric_cols = []
            for col, val in records[0].items():
                if isinstance(val, (int, float)) and val is not None:
                    numeric_cols.append(col)
            
            # Analyze primary numeric column
            for col in ['revenue', 'total', 'amount', 'grand_total', 'sum_grand_total', 'orders', 'count', 'qty']:
                if col in numeric_cols:
                    values = [r.get(col, 0) or 0 for r in records]
                    if values:
                        total = sum(values)
                        avg = total / len(values)
                        max_val = max(values)
                        
                        # Top contributor
                        if total > 0:
                            top_pct = (max_val / total) * 100
                            if top_pct > 20:
                                insights.append(f"📈 Top performer contributes **{top_pct:.0f}%** of total")
                        
                        # Concentration
                        if len(values) >= 3 and total > 0:
                            top_3 = sum(sorted(values, reverse=True)[:3])
                            top_3_pct = (top_3 / total) * 100
                            insights.append(f"💡 Top 3 account for **{top_3_pct:.0f}%** of total {col}")
                        
                        # Variance
                        if max_val > avg * 3:
                            insights.append(f"📊 High variance: max is **{max_val/avg:.1f}x** the average")
                        
                        break  # Only analyze first matching column
            
            # Count-based insights
            if 'orders' in [r.keys() for r in records][0] or 'count' in [r.keys() for r in records][0]:
                count_col = 'orders' if 'orders' in records[0] else 'count' if 'count' in records[0] else None
                if count_col:
                    counts = [r.get(count_col, 0) or 0 for r in records]
                    total_orders = sum(counts)
                    insights.append(f"📋 Total: **{total_orders:,}** across {len(records)} groups")
            
        except Exception:
            pass
        
        return insights[:3]
    
    def _get_aggregate_suggestions(self, doctype: str, agg: str, field: str) -> List[str]:
        """Get follow-up suggestions for aggregate queries."""
        suggestions = []
        
        if doctype == "Sales Invoice":
            if agg == "SUM":
                suggestions = [
                    "Break this down by customer",
                    "What's the average invoice value?",
                    "Show me monthly revenue trend"
                ]
            elif agg == "AVG":
                suggestions = [
                    "What's the total revenue?",
                    "Show me invoices above average",
                    "Revenue by customer"
                ]
        elif doctype == "Sales Order":
            suggestions = [
                "How many orders are pending?",
                "Show me recent sales orders",
                "Order value by customer"
            ]
        else:
            suggestions = [
                f"List recent {doctype}s",
                f"Break down by category",
                f"Show top 10"
            ]
        
        return suggestions
    
    def _get_list_suggestions(self, doctype: str, count: int) -> List[str]:
        """Get follow-up suggestions for list queries."""
        if doctype == "Sales Invoice":
            return [
                "What's the total revenue from these?",
                "Show me outstanding invoices",
                "Revenue breakdown by customer"
            ]
        elif doctype == "Sales Order":
            return [
                "Sum of order values",
                "How many are pending delivery?",
                "Orders by customer"
            ]
        elif doctype == "Customer":
            return [
                "Show me invoices for a specific customer",
                "Top customers by revenue",
                "Customer count by territory"
            ]
        elif doctype == "Item":
            return [
                "Top selling items",
                "Items by item group",
                "Low stock items"
            ]
        elif doctype == "Error Log":
            return [
                "Show errors from today only",
                "Filter by specific method",
                "Count of errors by type"
            ]
        else:
            return [
                f"Sum of values in {doctype}",
                f"Count of {doctype} by category",
                f"Details of a specific record"
            ]
    
    def _build_compact_prompt(self, allowed_doctypes: List[str]) -> str:
        """Build a compact system prompt with schema information for allowed doctypes."""
        prompt = self._prompt_provider.get_prompt("query")
        today = datetime.now().strftime('%Y-%m-%d')
        last_year = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        last_month = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not allowed_doctypes:
            final_prompt = f"""You are Jive, an ERPNext data assistant. Today: {today}

You may query any DocType the current user can read. There is no fixed allowlist.
Always rely on Frappe permissions at tool time.

TOOLS:
1. describe_doctype(doctype) - Inspect fields, link fields, and child tables on demand.
2. multi_doctype_query(doctype, fields, filters, limit, order_by) - List records from a single doctype.
3. get_document_count(doctype, filters) - Count records.
4. get_document(doctype, name, fields) - Fetch a single document and only the fields you need.
5. aggregate_query(doctype, aggregation, field, filters, group_by) - SUM/AVG/COUNT/MIN/MAX on one doctype.
6. complex_query(sql, description) - For cross-table analysis when required.

WORKING RULES:
- If the user asks about a specific doctype, query that doctype directly even if it was not preconfigured.
- If you need schema details, call describe_doctype first.
- If the user asks about a linked field, fetch the linked document on demand with get_document and only request the needed fields.
- If the user asks about a child table, fetch only the child rows and child fields that are required for the answer.
- Prefer narrow field lists over dumping full documents.
- Child tables should not flood the prompt or response with every nested field.
- For submittable doctypes, default to docstatus=1 unless the user asks otherwise.
- Date format: YYYY-MM-DD. Last year: {last_year}, Last month: {last_month}.
- Be concise and return only what is needed to answer the question."""

        # Build schema summary for the actual allowed_doctypes (not just from cache)
        schema_lines = ["AVAILABLE DATA SOURCES AND FIELDS:"]

        for doctype in (allowed_doctypes or [])[:15]:  # Limit to 15 for prompt size
            # Try to get from cache first
            schema = get_doctype_schema(doctype)

            # If not in cache, load directly
            if not schema:
                try:
                    schema = _load_doctype_schema(doctype)
                except Exception:
                    schema = {"queryable_fields": ["name"], "is_submittable": False, "is_child_table": False}

            if schema.get("error"):
                continue

            # Build field list
            fields = schema.get("queryable_fields", ["name"])[:10]
            field_str = ", ".join(fields) if fields else "name"

            # Build notes
            notes = []
            if schema.get("is_submittable"):
                notes.append("submittable (use docstatus=1)")
            if schema.get("is_child_table"):
                notes.append("child table (join via parent)")
            if schema.get("date_field"):
                notes.append(f"date: {schema['date_field']}")

            line = f"- **{doctype}** (`tab{doctype}`): {field_str}"
            if notes:
                line += f" [{', '.join(notes)}]"

            schema_lines.append(line)

        schema_summary = "\n".join(schema_lines) if len(schema_lines) > 1 else "No data sources configured."

        # Build doctype list
        doctypes = ", ".join(allowed_doctypes[:20]) if allowed_doctypes else "None configured"
        if prompt:
            return append_followup_prompt(
                (
                    prompt
                    .replace("{today}", today)
                    .replace("{last_year}", last_year)
                    .replace("{last_month}", last_month)
                    .replace("{doctypes}", doctypes)
                    .replace("{schema_summary}", schema_summary)
                )
            )

        return build_query_fallback_prompt(today, last_year, last_month, doctypes, schema_summary)

    def chat(
        self,
        message: str,
        history: List[Dict[str, str]] = None,
        allowed_doctypes: List[str] = None,
        session_id: str = None,
        system_prompt: str = None
    ) -> str:
        """
        Process a chat message and return a response.
        OPTIMIZED: Fast path for common queries, LLM fallback for complex ones.
        """
        start_time = time.time()
        from ..utils.interaction_logger import InteractionLogger
        interaction_logger = InteractionLogger("data_query")
        
        try:
            # In query mode there is no fixed allowlist.
            # If an allowlist is provided, we treat it as a compact hint only.
            allowed_doctypes = allowed_doctypes or []
            
            # FAST PATH: Check for pattern match first (no LLM needed)
            # Only use fast path if no history (follow-ups need LLM for context)
            if not history:
                fast_match = self._match_fast_pattern(message)
                if fast_match:
                    # Verify doctype is allowed
                    tool_doctype = fast_match['args'].get('doctype', '')
                    if tool_doctype and allowed_doctypes and tool_doctype not in allowed_doctypes:
                        return f"📋 I can only query these doctypes: {', '.join(allowed_doctypes[:10])}\n\nYou asked about **{tool_doctype}** which is not in my allowed data sources."
                    
                    result = self._execute_tool(fast_match['tool'], fast_match['args'])
                    formatted = self._format_results(result, message)
                    
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    
                    # Try logging the fast-path result or error
                    try:
                        res_data = json.loads(result) if isinstance(result, str) else result
                        if isinstance(res_data, dict) and res_data.get("error"):
                            interaction_logger.log(
                                request_data={"message": message, "fast_path": True, "tool": fast_match['tool']},
                                model="data_query_model_fast",
                                status="error",
                                error=Exception(res_data["error"]),
                                error_traceback=res_data.get("traceback", ""),
                                processing_time_ms=processing_time_ms,
                                session_id=session_id,
                            )
                        else:
                            interaction_logger.log(
                                request_data={"message": message, "fast_path": True, "tool": fast_match['tool']},
                                response_data=formatted[:5000],
                                model="data_query_model_fast",
                                status="success",
                                processing_time_ms=processing_time_ms,
                                session_id=session_id,
                            )
                    except Exception:
                        pass
                        
                    return formatted
            
            # STANDARD PATH: Use LLM with tools
            llm_with_tools = self._get_llm(with_tools=True)
            
            # Build system prompt
            system_prompt = (system_prompt or self._build_compact_prompt(allowed_doctypes) or "").strip()
            
            # Build messages - keep minimal for speed
            messages = [SystemMessage(content=system_prompt)]
            
            # Add context from history (compressed)
            if history:
                # Only include last 3 messages for context
                recent = history[-3:] if len(history) > 3 else history
                for msg in recent:
                    role = msg.get("role", "user")
                    content = msg.get("content") or ""
                    
                    # Truncate long content
                    if len(content) > 400:
                        content = content[:350] + "..."
                    
                    if role == "user":
                        messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        messages.append(AIMessage(content=content))
            
            # Add current message
            messages.append(HumanMessage(content=message))
            
            # Serialize messages for logging
            log_messages = [
                {"role": "system", "content": system_prompt[:2000] + "..." if len(system_prompt) > 2000 else system_prompt}
            ]
            if history:
                for msg in (history[-3:] if len(history) > 3 else history):
                    log_messages.append({"role": msg.get("role", "user"), "content": (msg.get("content") or "")[:500]})
            log_messages.append({"role": "user", "content": message})
            
            # LLM call - may include tool calls
            llm_start = time.time()
            response = llm_with_tools.invoke(messages)
            
            # Check for tool calls
            if hasattr(response, "tool_calls") and response.tool_calls:
                # Execute first tool only (speed optimization)
                tool_call = response.tool_calls[0]
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("args", {})
                
                # Verify doctype is allowed
                tool_doctype = tool_args.get('doctype', '')
                if tool_doctype and allowed_doctypes and tool_doctype not in allowed_doctypes:
                    return f"📋 I can query: {', '.join(allowed_doctypes[:8])}\n\n**{tool_doctype}** is not in my allowed data sources. Please ask about one of the available doctypes."
                
                result = self._execute_tool(tool_name, tool_args)
                
                # Format results directly
                formatted = self._format_results(result, message)
                
                # Add any additional context from LLM if it had commentary
                if response.content and len(response.content) > 10:
                    formatted = f"{response.content}\n\n{formatted}"
                
                processing_time_ms = int((time.time() - llm_start) * 1000)

                # Log successful or failed tool interaction
                try:
                    res_data = json.loads(result) if isinstance(result, str) else result
                    is_error = isinstance(res_data, dict) and res_data.get("error")
                except:
                    is_error = False

                if is_error:
                    interaction_logger.log(
                        request_data={"messages": log_messages, "model": "data_query_model"},
                        model="data_query_model",
                        status="error",
                        error=Exception(res_data["error"]),
                        error_traceback=res_data.get("traceback", ""),
                        processing_time_ms=processing_time_ms,
                        session_id=session_id,
                    )
                else:
                    interaction_logger.log(
                        request_data={"messages": log_messages, "model": "data_query_model"},
                        response_data=formatted[:5000],
                        model="data_query_model",
                        status="success",
                        processing_time_ms=processing_time_ms,
                        session_id=session_id,
                    )
                
                elapsed = time.time() - start_time
                if elapsed > 15:
                    frappe.log_error(
                        message=f"Slow query: {elapsed:.1f}s for: {message[:100]}",
                        title="Jive Slow Query"
                    )
                
                return formatted
            
            # No tool calls - return direct response (LLM decided not to query)
            if response.content:
                processing_time_ms = int((time.time() - llm_start) * 1000)
                interaction_logger.log(
                    request_data={"messages": log_messages, "model": "data_query_model"},
                    response_data=response.content,
                    model="data_query_model",
                    status="success",
                    processing_time_ms=processing_time_ms,
                    session_id=session_id,
                )
                return response.content
            
            if allowed_doctypes:
                return f"I can help you query: {', '.join(allowed_doctypes[:8])}\n\nPlease ask about one of these doctypes."
            return "Please mention the doctype, record, or field you want to query."
            
        except Exception as e:
            error_msg = str(e).lower()
            processing_time_ms = int((time.time() - start_time) * 1000)

            # Log error interaction
            interaction_logger.log(
                request_data={"message": message},
                model="data_query_model",
                status="timeout" if 'timeout' in error_msg else "error",
                error=e,
                error_traceback=frappe.get_traceback(),
                processing_time_ms=processing_time_ms,
                session_id=session_id,
            )

            if 'timeout' in error_msg:
                return "⏱️ Request timed out. Please try a simpler query."
            
            frappe.log_error(
                message=f"Jive chat error: {e}\n\n{frappe.get_traceback()}",
                title="Jive Agent Error"
            )
            
            return "I encountered an error processing your request. Please try rephrasing your question."


# Singleton instance
_agent_instance = None


def get_agent() -> JiveAgent:
    """Get or create the singleton agent instance."""
    global _agent_instance
    
    if _agent_instance is None:
        _agent_instance = JiveAgent()
    
    return _agent_instance
