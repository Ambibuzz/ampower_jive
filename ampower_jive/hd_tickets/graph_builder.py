"""LangGraph builder for the HD Tickets tool-driven workflow."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import frappe
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from ampower_jive.agent.llm_pool import compress_history
from ampower_jive.hd_tickets.agent_tools import HDTicketsToolKit
from ampower_jive.hd_tickets.constants import DEFAULT_LIST_LIMIT, NO_RESULTS_MESSAGE
from ampower_jive.hd_tickets.dtos import HDTicketsGraphState, TicketRequestContext
from ampower_jive.hd_tickets.prompts import HD_TICKETS_AGENT_PROMPT
from ampower_jive.hd_tickets.services.customer_scope_service import CustomerScopeService
from ampower_jive.hd_tickets.services.llm_service import TicketLLMService
from ampower_jive.hd_tickets.services.pagination_state_service import PaginationStateService
from ampower_jive.hd_tickets.services.request_context_service import TicketRequestContextService
from ampower_jive.hd_tickets.services.ticket_activity_service import TicketActivityService
from ampower_jive.hd_tickets.services.ticket_create_context_service import TicketCreateContextService
from ampower_jive.hd_tickets.services.ticket_create_service import TicketCreateService
from ampower_jive.hd_tickets.services.ticket_repository import TicketRepository
from ampower_jive.hd_tickets.services.ticket_write_service import TicketWriteService
from ampower_jive.hd_tickets.services.text_normalizer import to_plain_text
from ampower_jive.utils.followup_suggestions import (
    append_followup_block,
    append_followup_prompt,
    strip_followup_block,
)
from ampower_jive.utils.prompt_provider import get_prompt_provider


class HDTicketsGraphBuilder:
    """Build the HD Tickets graph that lets the LLM route to ticket tools."""

    def build(self):
        repository = TicketRepository()
        scope_service = CustomerScopeService(repository)
        create_service = TicketCreateService(scope_service)
        write_service = TicketWriteService()
        activity_service = TicketActivityService(repository)
        toolkit = HDTicketsToolKit(
            repository=repository,
            activity_service=activity_service,
            scope_service=scope_service,
            create_service=create_service,
            write_service=write_service,
        )
        return HDTicketsAgentWorkflow(
            llm_service=TicketLLMService(),
            context_service=TicketRequestContextService(),
            tools=toolkit.tools,
            create_context_service=TicketCreateContextService(),
            create_service=create_service,
            pagination_state_service=PaginationStateService(),
            repository=repository,
            scope_service=scope_service,
        ).build()


class HDTicketsAgentWorkflow:
    """Stateful HD Tickets agent workflow with explicit tool execution."""

    MAX_ITERATIONS = 3
    HISTORY_MESSAGE_CHAR_LIMIT = 12000

    def __init__(
        self,
        *,
        llm_service: TicketLLMService,
        context_service: TicketRequestContextService,
        tools: list,
        create_context_service: TicketCreateContextService,
        create_service: TicketCreateService,
        pagination_state_service: PaginationStateService,
        repository: TicketRepository,
        scope_service: CustomerScopeService,
    ):
        self._llm_service = llm_service
        self._context_service = context_service
        self._tools = tools
        self._tools_by_name = {tool.name: tool for tool in tools}
        self._create_context_service = create_context_service
        self._create_service = create_service
        self._pagination_state_service = pagination_state_service
        self._repository = repository
        self._scope_service = scope_service
        self._prompt_provider = get_prompt_provider()
        self._graph = None

    def build(self):
        if self._graph is not None:
            return self._graph

        workflow = StateGraph(HDTicketsGraphState)
        workflow.add_node("prepare", self._prepare_node)
        workflow.add_node("reason", self._reason_node)
        workflow.add_node("execute_tools", self._execute_tools_node)
        workflow.add_node("finalize", self._finalize_node)

        workflow.add_edge(START, "prepare")
        workflow.add_edge("prepare", "reason")
        workflow.add_conditional_edges(
            "reason",
            self._route_after_reason,
            {
                "execute_tools": "execute_tools",
                "finalize": "finalize",
            },
        )
        workflow.add_conditional_edges(
            "execute_tools",
            self._route_after_tools,
            {
                "reason": "reason",
                "finalize": "finalize",
            },
        )
        workflow.add_edge("finalize", END)

        self._graph = workflow.compile()
        return self._graph

    def _prepare_node(self, state: HDTicketsGraphState) -> Dict[str, Any]:
        request_context = self._context_service.extract(state.get("context_payload"))
        history = self._sanitize_history(state.get("history") or [])
        messages = [SystemMessage(content=self._build_system_prompt(request_context))]
        pagination_context = self._build_pagination_system_message(
            conversation_id=state.get("conversation_id") or "",
            user_message=state.get("message") or "",
        )
        if pagination_context:
            messages.append(SystemMessage(content=pagination_context))
        messages.extend(self._history_to_messages(history))
        messages.append(HumanMessage(content=state.get("message") or ""))
        direct_response = self._try_direct_response(
            message=state.get("message") or "",
            history=history,
            request_context=request_context,
            conversation_id=state.get("conversation_id") or "",
        )
        return {
            "request_context": request_context,
            "messages": messages,
            "iteration_count": 0,
            "needs_approval": False,
            "plan": [],
            "done": bool(direct_response),
            "response": direct_response or "",
        }

    def _reason_node(self, state: HDTicketsGraphState) -> Dict[str, Any]:
        if state.get("done"):
            return {}

        messages = list(state.get("messages") or [])
        iteration_count = int(state.get("iteration_count") or 0)
        if iteration_count >= self.MAX_ITERATIONS:
            return {
                "done": True,
                "response": "I need a narrower request to continue. Please mention the ticket id or the exact ticket details you need.",
            }

        llm = self._llm_service.get_bound_llm(self._tools)
        if not llm:
            return {
                "done": True,
                "response": "HD Tickets is unavailable because the AI model is not configured.",
            }

        response = llm.invoke(messages)
        messages.append(response)

        if not getattr(response, "tool_calls", None):
            content = (getattr(response, "content", "") or "").strip()
            return {
                "messages": messages,
                "iteration_count": iteration_count + 1,
                "done": True,
                "response": content or NO_RESULTS_MESSAGE,
            }

        return {
            "messages": messages,
            "iteration_count": iteration_count + 1,
        }

    def _execute_tools_node(self, state: HDTicketsGraphState) -> Dict[str, Any]:
        messages = list(state.get("messages") or [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return {
                "done": True,
                "response": NO_RESULTS_MESSAGE,
            }

        ai_message = messages[-1]
        for tool_call in getattr(ai_message, "tool_calls", []) or []:
            tool_name = tool_call.get("name", "")
            tool_args = self._prepare_tool_args(
                tool_name,
                tool_call.get("args", {}) or {},
                messages[:-1],
                state.get("request_context"),
            )
            tool_id = tool_call.get("id", "")

            result = self._invoke_tool(tool_name, tool_args)
            tool_payload = self._parse_tool_payload(result)
            messages.append(ToolMessage(content=result, tool_call_id=tool_id))
            self._update_pagination_state(
                conversation_id=state.get("conversation_id") or "",
                tool_name=tool_name,
                tool_payload=tool_payload,
            )

            if tool_payload.get("needs_approval") and tool_payload.get("plan"):
                return {
                    "messages": messages,
                    "plan": tool_payload.get("plan"),
                    "needs_approval": True,
                    "done": True,
                    "response": tool_payload.get("response") or "I prepared a ticket creation plan for your review.",
                }

            if tool_payload.get("response_ready"):
                return {
                    "messages": messages,
                    "done": True,
                    "response": tool_payload.get("response") or NO_RESULTS_MESSAGE,
                }

        return {"messages": messages}

    def _finalize_node(self, state: HDTicketsGraphState) -> Dict[str, Any]:
        return {
            "response": state.get("response") or NO_RESULTS_MESSAGE,
            "needs_approval": bool(state.get("needs_approval")),
            "plan": state.get("plan") or [],
        }

    def _route_after_reason(self, state: HDTicketsGraphState) -> str:
        if state.get("done"):
            return "finalize"

        messages = state.get("messages") or []
        if messages and isinstance(messages[-1], AIMessage) and getattr(messages[-1], "tool_calls", None):
            return "execute_tools"
        return "finalize"

    def _route_after_tools(self, state: HDTicketsGraphState) -> str:
        return "finalize" if state.get("done") else "reason"

    def _build_system_prompt(self, request_context: TicketRequestContext) -> str:
        context_payload = request_context.to_prompt_payload() if request_context else {}
        context_text = json.dumps(context_payload or {"ticket_context": "not available"}, ensure_ascii=False, indent=2)
        base_prompt = (self._prompt_provider.get_prompt("hd_tickets") or "").strip()
        agent_prompt = HD_TICKETS_AGENT_PROMPT.format(current_ticket_context=context_text)
        prompt = f"{base_prompt}\n\n{agent_prompt}".strip() if base_prompt else agent_prompt
        return append_followup_prompt(prompt)

    def _try_direct_response(
        self,
        *,
        message: str,
        history: List[Dict[str, str]],
        request_context: TicketRequestContext,
        conversation_id: str,
    ) -> str:
        lowered = (message or "").strip().lower()
        if not lowered or self._is_create_request(lowered):
            return ""

        ticket_id = self._resolve_ticket_reference(message, history, request_context)
        if ticket_id:
            if self._is_status_request(lowered):
                return self._build_status_response(ticket_id)
            if self._is_detail_request(lowered):
                return self._build_detail_response(ticket_id)
            return ""

        if self._needs_llm_interpretation(lowered):
            return ""
        if self._is_search_request(lowered):
            return ""

        if self._is_count_request(lowered):
            return self._build_count_response(lowered)
        if self._is_list_request(lowered):
            return self._build_list_response(lowered, conversation_id=conversation_id)
        return ""

    def _build_list_response(self, lowered_message: str, *, conversation_id: str) -> str:
        scope = self._scope_service.resolve_customer_scope(operation="read")
        if scope.clarify_question:
            return scope.clarify_question

        status = self._extract_status_hint(lowered_message)
        filters = self._build_filters(scope.customer_name, status)
        tickets = self._repository.list_tickets(filters=filters)
        if not tickets:
            return NO_RESULTS_MESSAGE

        if conversation_id:
            self._pagination_state_service.set(
                conversation_id,
                {
                    "tool_name": "list_visible_tickets",
                    "args": {
                        "customer_hint": "",
                        "status": status,
                        "limit": DEFAULT_LIST_LIMIT,
                        "offset": 0,
                    },
                    "returned_count": len(tickets),
                    "next_offset": len(tickets),
                },
            )

        lines = ["Here are the visible tickets:"]
        for ticket in tickets:
            lines.append(
                f"- {ticket.get('name')} - {ticket.get('subject') or 'No subject'} ({ticket.get('status') or 'Unknown'})"
            )
        return self._with_followups(
            "\n".join(lines),
            self._build_list_followups(tickets, status),
        )

    def _build_count_response(self, lowered_message: str) -> str:
        scope = self._scope_service.resolve_customer_scope(operation="read")
        if scope.clarify_question:
            return scope.clarify_question

        status = self._extract_status_hint(lowered_message)
        filters = self._build_filters(scope.customer_name, status)
        count = self._repository.count_tickets(filters)
        if status:
            return self._with_followups(
                f"I found {count} visible ticket(s) with status '{status}'.",
                [
                    f"Can you list those {status.lower()} tickets?",
                    "Can you show my open tickets?" if status != "Open" else "Can you show my resolved tickets?",
                    "Can you count all my visible tickets?",
                ],
            )
        return self._with_followups(
            f"I found {count} visible ticket(s).",
            [
                "Can you show my open tickets?",
                "Can you show my resolved tickets?",
                "Can you list all my visible tickets?",
            ],
        )

    def _build_status_response(self, ticket_id: str) -> str:
        ticket = self._repository.get_ticket_detail(ticket_id)
        if not ticket:
            return "I couldn't find any visible tickets for those ticket ids."

        status = ticket.get("status") or "Unknown"
        subject = ticket.get("subject") or "No subject"
        response = f"Ticket {ticket.get('name') or ticket_id} is currently {status}.\nSubject: {subject}"
        return self._with_followups(
            response,
            [
                f"Can you show the full details of {ticket.get('name') or ticket_id}?",
                f"Can you show the latest communication on {ticket.get('name') or ticket_id}?",
                "Can you list my other open tickets?",
            ],
        )

    def _build_detail_response(self, ticket_id: str) -> str:
        ticket = self._repository.get_ticket_detail(ticket_id)
        if not ticket:
            return "I couldn't find any visible tickets for those ticket ids."

        description = to_plain_text(ticket.get("description") or "")
        lines = [ticket.get("name") or ticket_id]
        if ticket.get("subject"):
            lines.append(f"Subject: {ticket.get('subject')}")
        if ticket.get("status"):
            lines.append(f"Status: {ticket.get('status')}")
        if ticket.get("priority"):
            lines.append(f"Priority: {ticket.get('priority')}")
        if ticket.get("customer"):
            lines.append(f"Customer: {ticket.get('customer')}")
        if ticket.get("creation"):
            lines.append(f"Created: {ticket.get('creation')}")
        if ticket.get("modified"):
            lines.append(f"Last updated: {ticket.get('modified')}")
        if description:
            lines.append("Description:")
            lines.append(description)

        return self._with_followups(
            "\n".join(lines),
            [
                f"Can you show the latest communication on {ticket.get('name') or ticket_id}?",
                f"What is the current status of {ticket.get('name') or ticket_id}?",
                "Can you list my other open tickets?",
            ],
        )

    def _resolve_ticket_reference(
        self,
        message: str,
        history: List[Dict[str, str]],
        request_context: TicketRequestContext,
    ) -> str:
        explicit_ticket_id = self._extract_explicit_ticket_id(message)
        if explicit_ticket_id:
            return explicit_ticket_id

        ordinal_index = self._extract_ordinal_index(message)
        if ordinal_index is not None:
            recent_ids = self._extract_recent_ticket_ids(history)
            if 0 <= ordinal_index < len(recent_ids):
                return recent_ids[ordinal_index]

        lowered = (message or "").strip().lower()
        if request_context and request_context.has_ticket and any(
            phrase in lowered for phrase in ("this ticket", "that ticket", "same ticket", "this one", "that one")
        ):
            return request_context.ticket_id

        if request_context and request_context.has_ticket and self._is_ticket_specific_request(lowered):
            return request_context.ticket_id

        recent_ids = self._extract_recent_ticket_ids(history)
        if len(recent_ids) == 1 and any(phrase in lowered for phrase in ("same ticket", "that one", "this one")):
            return recent_ids[0]

        return ""

    def _extract_explicit_ticket_id(self, message: str) -> str:
        match = re.search(r"\b(\d{3,4})\b", message or "")
        if not match:
            return ""
        return match.group(1).zfill(4)

    def _extract_ordinal_index(self, message: str) -> int | None:
        lowered = (message or "").strip().lower()
        ordinal_map = {
            "first": 0,
            "1st": 0,
            "second": 1,
            "2nd": 1,
            "third": 2,
            "3rd": 2,
            "fourth": 3,
            "4th": 3,
            "fifth": 4,
            "5th": 4,
        }
        for token, index in ordinal_map.items():
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                return index
        return None

    def _extract_recent_ticket_ids(self, history: List[Dict[str, str]]) -> List[str]:
        for item in reversed(history or []):
            if (item.get("role") or "").strip().lower() != "assistant":
                continue
            content = item.get("content") or ""
            matches = re.findall(r"^\s*[-*]\s*(\d{3,4})\b", content, re.MULTILINE)
            if matches:
                return [match.zfill(4) for match in matches]

        for item in reversed(history or []):
            if (item.get("role") or "").strip().lower() != "assistant":
                continue
            match = re.search(r"^\s*(\d{3,4})\b", item.get("content") or "", re.MULTILINE)
            if match:
                return [match.group(1).zfill(4)]

        return []

    def _build_filters(self, customer_name: str, status: str) -> Dict[str, str]:
        filters: Dict[str, str] = {}
        if customer_name:
            filters["customer"] = customer_name
        if status:
            filters["status"] = status
        return filters

    def _extract_status_hint(self, lowered_message: str) -> str:
        status_map = {
            "awaiting response": "Replied",
            "replied": "Replied",
            "resolved": "Resolved",
            "closed": "Closed",
            "open": "Open",
        }
        for token, status in status_map.items():
            if token in lowered_message:
                return status
        return ""

    def _is_create_request(self, lowered_message: str) -> bool:
        return any(
            token in lowered_message
            for token in ("create ticket", "raise ticket", "open ticket", "log ticket", "new ticket", "submit ticket")
        )

    def _is_search_request(self, lowered_message: str) -> bool:
        search_tokens = ("search", "keyword", "topic", "text", "content", "find tickets about")
        return any(token in lowered_message for token in search_tokens)

    def _is_count_request(self, lowered_message: str) -> bool:
        return any(token in lowered_message for token in ("how many", "count", "total tickets", "total ticket"))

    def _is_list_request(self, lowered_message: str) -> bool:
        return any(token in lowered_message for token in ("list", "show", "what are", "which are", "my tickets"))

    def _is_status_request(self, lowered_message: str) -> bool:
        return "status" in lowered_message or bool(
            re.search(r"\bis\s+(?:this|that|ticket|\d{3,4})\s+(?:open|closed|resolved|replied)\b", lowered_message)
        )

    def _is_detail_request(self, lowered_message: str) -> bool:
        detail_tokens = (
            "detail",
            "description",
            "summary",
            "subject",
            "about this ticket",
            "about that ticket",
            "show ticket",
            "show this ticket",
            "show that ticket",
        )
        return any(token in lowered_message for token in detail_tokens)

    def _is_ticket_specific_request(self, lowered_message: str) -> bool:
        return self._is_status_request(lowered_message) or self._is_detail_request(lowered_message)

    def _needs_llm_interpretation(self, lowered_message: str) -> bool:
        complex_tokens = (
            "assigned",
            "unassigned",
            "agent",
            "group",
            "team",
            "project",
            "priority",
            "raised by",
            "created by",
            "updated by",
            "email",
        )
        return any(token in lowered_message for token in complex_tokens)

    def _build_list_followups(self, tickets: List[Dict[str, Any]], status: str) -> List[str]:
        if not tickets:
            return []

        first_ticket_id = tickets[0].get("name") or ""
        followups = []
        if first_ticket_id:
            followups.append(f"Can you show the details of {first_ticket_id}?")
            followups.append(f"Can you show the latest communication on {first_ticket_id}?")
        if status == "Open":
            followups.append("Can you show my resolved tickets?")
        else:
            followups.append("Can you show my open tickets?")
        return followups[:3]

    def _with_followups(self, response: str, suggestions: List[str]) -> str:
        cleaned = [item for item in suggestions if item]
        if not response or not cleaned:
            return response
        return append_followup_block(response, cleaned[:3])

    def _sanitize_history(self, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        cleaned = []
        for item in history:
            if not isinstance(item, dict):
                continue
            role = (item.get("role") or "").strip().lower()
            if role not in {"user", "assistant", "system"}:
                continue
            content = strip_followup_block(item.get("content") or "").strip()
            if not content:
                continue
            cleaned.append({"role": role, "content": content})
        return compress_history(cleaned, max_messages=6, max_chars=self.HISTORY_MESSAGE_CHAR_LIMIT)

    def _history_to_messages(self, history: List[Dict[str, str]]) -> List[Any]:
        messages: List[Any] = []
        for item in history:
            role = item.get("role")
            content = item.get("content") or ""
            if role == "system":
                messages.append(SystemMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
        return messages

    def _invoke_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        tool = self._tools_by_name.get(tool_name)
        if not tool:
            return json.dumps({"success": False, "response_ready": True, "response": f"Unknown HD Tickets tool: {tool_name}"})

        try:
            result = tool.invoke(tool_args)
        except Exception as exc:
            frappe.log_error(
                message=f"{exc}\n\n{frappe.get_traceback()}",
                title="HD Tickets Tool Error",
            )
            return json.dumps(
                {
                    "success": False,
                    "response_ready": True,
                    "response": f"I encountered an error while checking the tickets: {exc}",
                }
            )

        if isinstance(result, str):
            return result
        return json.dumps(result, default=str, ensure_ascii=False)

    def _parse_tool_payload(self, result: str) -> Dict[str, Any]:
        try:
            payload = json.loads(result or "{}")
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _prepare_tool_args(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        messages: List[Any],
        request_context: TicketRequestContext | None,
    ) -> Dict[str, Any]:
        if tool_name != "prepare_hd_ticket_create_plan":
            return self._enrich_ticket_activity_tool_args(
                tool_name=tool_name,
                tool_args=tool_args,
                messages=messages,
                request_context=request_context,
            )
        return self._create_context_service.enrich(
            tool_args,
            messages,
            priority_catalog=self._create_service.get_priority_catalog(),
        )

    def _enrich_ticket_activity_tool_args(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        messages: List[Any],
        request_context: TicketRequestContext | None,
    ) -> Dict[str, Any]:
        if tool_name not in {
            "prepare_hd_ticket_comment_plan",
            "prepare_hd_ticket_communication_plan",
        }:
            return tool_args

        enriched = dict(tool_args or {})
        if not str(enriched.get("ticket_id") or "").strip():
            inferred_ticket_id = self._infer_ticket_id_from_messages(messages, request_context)
            if inferred_ticket_id:
                enriched["ticket_id"] = inferred_ticket_id
        return enriched

    def _infer_ticket_id_from_messages(
        self,
        messages: List[Any],
        request_context: TicketRequestContext | None,
    ) -> str:
        if request_context and request_context.has_ticket:
            return request_context.ticket_id

        for message in reversed(messages or []):
            content = str(getattr(message, "content", "") or "")
            explicit_ticket_id = self._extract_explicit_ticket_id(content)
            if explicit_ticket_id:
                return explicit_ticket_id
        return ""

    def _build_pagination_system_message(self, conversation_id: str, user_message: str) -> str:
        if not self._is_pagination_followup(user_message):
            return ""

        payload = self._pagination_state_service.get(conversation_id)
        if not payload:
            return (
                "Pagination context: there is no previous ticket list or search page stored in this conversation. "
                "If the user asks for the next set, explain that they should first ask for a ticket list or search."
            )

        return (
            "Pagination context from the previous ticket results:\n"
            f"{json.dumps(payload, default=str, ensure_ascii=False, indent=2)}\n\n"
            "If the user asks for the next set, show more, or next page, call the same tool again with the same "
            "arguments and use next_offset as the new offset."
        )

    def _update_pagination_state(
        self,
        *,
        conversation_id: str,
        tool_name: str,
        tool_payload: Dict[str, Any],
    ) -> None:
        if not conversation_id:
            return

        pagination = tool_payload.get("pagination") if isinstance(tool_payload, dict) else None
        if tool_name in {"list_visible_tickets", "search_visible_tickets"} and isinstance(pagination, dict):
            self._pagination_state_service.set(
                conversation_id,
                {
                    "tool_name": pagination.get("tool_name") or tool_name,
                    "args": pagination.get("args") or {},
                    "returned_count": int(pagination.get("returned_count") or 0),
                    "next_offset": int(pagination.get("next_offset") or 0),
                },
            )

    def _is_pagination_followup(self, user_message: str) -> bool:
        lowered = (user_message or "").strip().lower()
        return any(
            phrase in lowered
            for phrase in (
                "next set",
                "next page",
                "show more",
                "more tickets",
                "next tickets",
                "more results",
            )
        ) or lowered in {"next", "more"}
