"""
Agent Mode Graph
Handles R/W operations with planning and approval workflow.
Follows Frappe/ERPNext constraints and requires human approval.
OPTIMIZED: Connection pooling, history compression.
"""

import frappe
from typing import List, Dict, Any
import json
import time

from ..utils.interaction_logger import InteractionLogger

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from .agent_tools import get_agent_tools
from .llm_pool import get_cached_llm, compress_history, prune_langraph_messages
from ..utils.followup_suggestions import append_followup_prompt
from ..utils.agent_prompt_defaults import build_agent_fallback_prompt
from ..utils.prompt_provider import get_prompt_provider
from ..utils.tokens import TokenUsageCallbackHandler


class AgentModeGraph:
    """
    Agent for R/W operations that require user approval.
    Enforces Frappe/ERPNext rules and constraints.
    OPTIMIZED with connection pooling.
    """
    
    def __init__(self):
        self.tools = get_agent_tools()
        self.tools_by_name = {t.name: t for t in self.tools}
        self._prompt_provider = get_prompt_provider()
        self._llm = None
    
    def _get_llm(self):
        """Get LLM from pool (lazy, cached)."""
        if self._llm:
            return self._llm
        
        # Use pooled connection with reduced timeout for faster responses
        llm = get_cached_llm(
            purpose="agent",
            temperature=0.2,
            timeout=30,  # Reduced from 45s
            add_token_callback=False
        )
        
        if llm:
            self._llm = llm.bind_tools(self.tools)
            return self._llm
        
        # Fallback to direct initialization using ConfigProvider
        try:
            from ampower_jive.utils.config_provider import get_config_provider
            provider = get_config_provider()
            
            api_key = provider.get_api_key()
            model_settings = provider.get_model_settings("agent_mode")
            model = model_settings.get("model", "gpt-4o-mini")
            temperature = model_settings.get("temperature", 0.2)
            
            if not api_key:
                raise ValueError("OpenAI API key not configured")
            
            # Check if model supports temperature
            no_temp_models = ['o1', 'o3', 'search-preview', 'gpt-5']
            supports_temp = not any(x in model.lower() for x in no_temp_models)
            
            if supports_temp:
                self._llm = ChatOpenAI(
                    model=model,
                    api_key=api_key,
                    temperature=temperature,
                    timeout=30,
                    max_retries=1
                ).bind_tools(self.tools)
            else:
                self._llm = ChatOpenAI(
                    model=model,
                    api_key=api_key,

                    timeout=30,
                    max_retries=1
                ).bind_tools(self.tools)
            
            return self._llm
            
        except Exception as e:
            frappe.log_error(
                message=f"Agent Mode init error: {e}\n\n{frappe.get_traceback()}",
                title="Agent Mode Error"
            )
            raise
    
    def _build_system_prompt(self, allowed_doctypes: List[str]) -> str:
        """Build compact system prompt with Frappe/ERPNext rules."""
        prompt = self._prompt_provider.get_prompt("agent")
        doctypes_str = ", ".join(allowed_doctypes[:15]) if allowed_doctypes else "None"
        current_user = frappe.session.user

        if prompt:
            return append_followup_prompt(
                (
                    prompt
                    .replace("{current_user}", current_user)
                    .replace("{allowed_doctypes}", doctypes_str)
                    .replace("{doctypes_str}", doctypes_str)
                )
            )

        return build_agent_fallback_prompt(allowed_doctypes, current_user)
    
    def process(
        self,
        message: str,
        history: List[Dict[str, str]] = None,
        allowed_doctypes: List[str] = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Process an agent mode request with iterative tool execution.
        OPTIMIZED with history compression and faster timeouts.
        """
        interaction_logger = InteractionLogger("agent_mode")
        llm_start = time.time()

        try:
            if not allowed_doctypes:
                return {
                    "needs_approval": False,
                    "response": "No doctypes are configured for agent mode. Please contact your administrator."
                }
            
            llm = self._get_llm()
            
            # Aggressively compress history for unlimited follow-ups
            compressed = compress_history(history or [], max_messages=3, max_chars=600)
            
            # Build initial messages
            system_prompt = (self._build_system_prompt(allowed_doctypes) or "").strip()
            messages = [
                SystemMessage(content=system_prompt)
            ]
            
            for msg in compressed:
                role = msg.get("role", "user")
                content = msg.get("content") or ""
                
                if role == "system":
                    # Context summaries
                    messages.append(SystemMessage(content=content))
                elif role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            
            messages.append(HumanMessage(content=message))
            
            # Prepare compact log of messages for interaction logging
            log_messages = [
                {"role": "system", "content": system_prompt[:2000] + "..." if len(system_prompt) > 2000 else system_prompt}
            ]
            for msg in compressed:
                log_messages.append({"role": msg.get("role", "user"), "content": (msg.get("content") or "")[:500]})
            log_messages.append({"role": "user", "content": message})
            
            # Iterative tool execution loop (max 3 iterations for speed)
            max_iterations = 3
            plans = []
            thinking_parts = []
            
            for iteration in range(max_iterations):
                # PRUNE messages before each LLM call to prevent accumulation
                if len(messages) > 10:
                    messages = prune_langraph_messages(messages, max_messages=8)
                
                # Get LLM response
                try:
                    # Create callback handler for this specific request to capture current user
                    callbacks = [TokenUsageCallbackHandler("agent_mode")]
                    response = llm.invoke(messages, config={"callbacks": callbacks})
                except Exception as e:
                    if 'timeout' in str(e).lower():
                        return {
                            "needs_approval": False,
                            "response": "⏱️ Request timed out. Please try a simpler request."
                        }
                    raise
                
                # Collect any text response
                if response.content:
                    thinking_parts.append(response.content)
                
                # Check for tool calls
                if not hasattr(response, "tool_calls") or not response.tool_calls:
                    # No tool calls - we're done
                    break
                
                # Add assistant message with tool calls
                messages.append(response)
                
                # Process each tool call
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", "")
                    
                    # Check if it's a planning tool
                    if tool_name.startswith("plan_"):
                        action = tool_name.replace("plan_", "").replace("_document", "")
                        doctype = tool_args.get("doctype", "")
                        
                        # Validate doctype
                        if doctype and doctype not in allowed_doctypes:
                            return {
                                "needs_approval": False,
                                "response": f"Cannot perform operations on '{doctype}'. Allowed: {', '.join(allowed_doctypes[:10])}"
                            }
                        
                        plan_item = {
                            "action": action,
                            "doctype": doctype,
                            "name": tool_args.get("name"),
                            "data": tool_args.get("data", {}),
                            "description": self._get_action_description(action, doctype, tool_args)
                        }
                        plans.append(plan_item)
                        
                        # Add tool result message
                        messages.append(ToolMessage(
                            content=json.dumps({"status": "planned", "description": plan_item["description"]}),
                            tool_call_id=tool_id
                        ))
                    else:
                        # Execute informational tools
                        tool_result = self._execute_tool(tool_name, tool_args)
                        messages.append(ToolMessage(
                            content=tool_result,
                            tool_call_id=tool_id
                        ))
            
            # If we have plans, return for approval
            if plans:
                validation_errors = self._validate_plans(plans)
                
                if validation_errors:
                    return {
                        "needs_approval": False,
                        "response": "I found issues with the planned operation:\n\n" + "\n".join(validation_errors) + "\n\nPlease provide more information."
                    }
                
                thinking = "\n".join(thinking_parts) if thinking_parts else self._generate_thinking(plans)
                
                # Log successful agent interaction
                processing_time_ms = int((time.time() - llm_start) * 1000)
                interaction_logger.log(
                    request_data={"messages": log_messages, "model": "agent_model"},
                    response_data=thinking[:5000],
                    model="agent_model",
                    status="success",
                    processing_time_ms=processing_time_ms,
                    session_id=session_id,
                )
                
                return {
                    "needs_approval": True,
                    "thinking": thinking,
                    "plan": plans
                }
            
            # No plans - return the text response
            final_response = "\n".join(thinking_parts) if thinking_parts else "I couldn't determine what action to take. Please provide more details."
            
            # Log successful interaction
            processing_time_ms = int((time.time() - llm_start) * 1000)
            interaction_logger.log(
                request_data={"messages": log_messages, "model": "agent_model"},
                response_data=final_response[:5000],
                model="agent_model",
                status="success",
                processing_time_ms=processing_time_ms,
                session_id=session_id,
            )
            
            return {
                "needs_approval": False,
                "response": final_response
            }
            
        except Exception as e:
            error_str = str(e).lower()
            frappe.log_error(f"Agent Mode error: {e}\n{frappe.get_traceback()}", "Agent Mode Error")
            
            # Log error interaction
            processing_time_ms = int((time.time() - llm_start) * 1000)
            interaction_logger.log(
                request_data={"message": message},
                model="agent_model",
                status="timeout" if 'timeout' in error_str else "error",
                error=e,
                error_traceback=frappe.get_traceback(),
                processing_time_ms=processing_time_ms,
                session_id=session_id,
            )
            
            # Provide helpful error messages
            if 'timeout' in error_str:
                return {
                    "needs_approval": False,
                    "response": "⏱️ Request timed out. Please try a simpler operation or break it into smaller steps."
                }
            elif 'permission' in error_str:
                return {
                    "needs_approval": False,
                    "response": f"🔒 Permission denied: {str(e)}"
                }
            elif 'mandatory' in error_str or 'required' in error_str:
                return {
                    "needs_approval": False,
                    "response": f"⚠️ Missing required field: {str(e)}\n\nPlease provide all mandatory fields."
                }
            else:
                return {
                    "needs_approval": False,
                    "response": f"I encountered an error processing your request. Please try rephrasing.\n\n*Error: {str(e)[:100]}*"
                }
    
    def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute an informational tool and return result."""
        try:
            tool = self.tools_by_name.get(tool_name)
            if tool:
                result = tool.invoke(tool_args)
                return result if isinstance(result, str) else json.dumps(result)
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            return json.dumps({"error": str(e), "traceback": frappe.get_traceback()})
    
    def _get_action_description(self, action: str, doctype: str, args: dict) -> str:
        """Generate human-readable description."""
        if action == "create":
            data = args.get("data", {})
            key_fields = []
            for key in ["customer_name", "item_code", "item_name", "name", "title"]:
                if key in data:
                    key_fields.append(f"{data[key]}")
            details = ", ".join(key_fields[:2]) if key_fields else "new document"
            return f"Create new {doctype}: {details}"
        
        elif action == "update":
            name = args.get("name", "unknown")
            data = args.get("data", {})
            fields = list(data.keys())[:3]
            return f"Update {doctype} '{name}' - fields: {', '.join(fields)}"
        
        elif action == "submit":
            return f"Submit {doctype} '{args.get('name', '')}'"
        
        elif action == "cancel":
            return f"Cancel {doctype} '{args.get('name', '')}'"
        
        return f"{action.title()} {doctype}"
    
    def _generate_thinking(self, plans: list) -> str:
        """Generate explanation of planned actions."""
        action_emoji = {
            "create": "➕",
            "update": "✏️",
            "submit": "✅",
            "cancel": "❌"
        }
        
        lines = ["📋 **Planned Operations:**\n"]
        
        for i, plan in enumerate(plans, 1):
            action = plan.get('action', 'unknown')
            emoji = action_emoji.get(action, "📄")
            lines.append(f"{emoji} **{i}. {plan['description']}**")
            
            if plan.get("data"):
                lines.append("")
                for key, value in list(plan["data"].items())[:10]:
                    display_val = str(value)[:60] + "..." if len(str(value)) > 60 else value
                    lines.append(f"  • {key}: `{display_val}`")
                if len(plan["data"]) > 10:
                    lines.append(f"  • ...and {len(plan['data']) - 10} more fields")
            lines.append("")
        
        lines.append("---")
        lines.append("⚠️ **Please review carefully before approving.**")
        return "\n".join(lines)
    
    def _validate_plans(self, plans: list) -> List[str]:
        """Validate plans against Frappe rules."""
        errors = []
        
        for plan in plans:
            doctype = plan.get("doctype")
            action = plan.get("action")
            data = plan.get("data", {})
            name = plan.get("name")
            
            if not doctype:
                errors.append("- Missing doctype")
                continue
            
            try:
                meta = frappe.get_meta(doctype)
                
                # Check permissions
                if action == "create" and not frappe.has_permission(doctype, "create"):
                    errors.append(f"- No permission to create {doctype}")
                elif action == "update" and not frappe.has_permission(doctype, "write"):
                    errors.append(f"- No permission to update {doctype}")
                elif action == "submit" and not frappe.has_permission(doctype, "submit"):
                    errors.append(f"- No permission to submit {doctype}")
                elif action == "cancel" and not frappe.has_permission(doctype, "cancel"):
                    errors.append(f"- No permission to cancel {doctype}")
                
                # Check mandatory fields for create
                if action == "create":
                    skip_fields = ["name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"]
                    for field in meta.fields:
                        if field.reqd and field.fieldname not in data and field.fieldname not in skip_fields:
                            if not field.default:
                                errors.append(f"- Missing required field: {field.label or field.fieldname}")
                
                # Check document exists for update/submit/cancel
                if action in ["update", "submit", "cancel"] and name:
                    if not frappe.db.exists(doctype, name):
                        errors.append(f"- {doctype} '{name}' does not exist")
                
                # Validate link fields (limit to first few for speed)
                link_count = 0
                for field in meta.fields:
                    if link_count >= 5:
                        break
                    if field.fieldtype == "Link" and field.fieldname in data:
                        val = data[field.fieldname]
                        if val and field.options and not frappe.db.exists(field.options, val):
                            errors.append(f"- Invalid {field.label or field.fieldname}: '{val}' not found")
                        link_count += 1
                
            except Exception as e:
                errors.append(f"- Validation error: {str(e)}")
        
        return errors
