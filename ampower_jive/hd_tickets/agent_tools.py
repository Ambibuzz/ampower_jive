"""LangChain tools for the HD Tickets agent graph."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.tools import tool

from ampower_jive.hd_tickets.constants import DEFAULT_LIST_LIMIT, MAX_ACTIVITY_ITEMS, MAX_LIST_LIMIT
from ampower_jive.hd_tickets.services.customer_scope_service import CustomerScopeService
from ampower_jive.hd_tickets.services.ticket_activity_service import TicketActivityService
from ampower_jive.hd_tickets.services.ticket_create_service import TicketCreateService
from ampower_jive.hd_tickets.services.ticket_repository import TicketRepository
from ampower_jive.hd_tickets.services.ticket_write_service import TicketWriteService
from ampower_jive.hd_tickets.services.text_normalizer import summarize_text_points, to_plain_text


class HDTicketsToolKit:
    """Expose the HD ticket read and create-plan services as LLM tools."""

    def __init__(
        self,
        repository: TicketRepository,
        activity_service: TicketActivityService,
        scope_service: CustomerScopeService,
        create_service: TicketCreateService,
        write_service: TicketWriteService,
    ):
        self._repository = repository
        self._activity_service = activity_service
        self._scope_service = scope_service
        self._create_service = create_service
        self._write_service = write_service
        self._tools = self._build_tools()

    @property
    def tools(self) -> list:
        return self._tools

    def _build_tools(self) -> list:
        @tool
        def list_visible_tickets(
            customer_hint: str = "",
            status: str = "",
            limit: int = DEFAULT_LIST_LIMIT,
            offset: int = 0,
        ) -> str:
            """
            List visible HD tickets.

            Use this for recent tickets, customer ticket lists, or whenever the
            user refers to a ticket list. The result order matters and can be
            reused for follow-up references like first, second, or third ticket.
            Use offset for pagination when the user asks for the next set.
            """
            scope = self._scope_service.resolve_customer_scope(customer_hint=customer_hint, operation="read")
            if scope.clarify_question:
                return self._serialize(
                    {
                        "success": False,
                        "response_ready": True,
                        "response": scope.clarify_question,
                    }
                )

            filters = self._build_filters(scope.customer_name, status)
            limit_value = self._sanitize_limit(limit)
            offset_value = self._sanitize_offset(offset)
            tickets = self._repository.list_tickets(filters=filters, limit=limit_value, offset=offset_value)
            return self._serialize(
                {
                    "success": True,
                    "scope": self._scope_payload(scope),
                    "filters": filters,
                    "tickets": tickets,
                    "pagination": {
                        "tool_name": "list_visible_tickets",
                        "args": {
                            "customer_hint": customer_hint,
                            "status": status,
                            "limit": limit_value,
                            "offset": offset_value,
                        },
                        "returned_count": len(tickets),
                        "next_offset": offset_value + len(tickets),
                    },
                }
            )

        @tool
        def count_visible_tickets(customer_hint: str = "", status: str = "") -> str:
            """
            Count visible HD tickets.

            Use this only for counting questions like how many tickets exist for
            a customer or status.
            """
            scope = self._scope_service.resolve_customer_scope(customer_hint=customer_hint, operation="read")
            if scope.clarify_question:
                return self._serialize(
                    {
                        "success": False,
                        "response_ready": True,
                        "response": scope.clarify_question,
                    }
                )

            filters = self._build_filters(scope.customer_name, status)
            count = self._repository.count_tickets(filters)
            return self._serialize(
                {
                    "success": True,
                    "scope": self._scope_payload(scope),
                    "filters": filters,
                    "count": count,
                }
            )

        @tool
        def get_ticket_details(ticket_ids: List[str]) -> str:
            """
            Get ticket details for one or more specific HD ticket ids.

            Use this for creation dates, reporters, subject, description,
            priority, status, customer, or general ticket details.
            """
            normalized_ids = self._normalize_ticket_ids(ticket_ids)
            if not normalized_ids:
                return self._serialize(
                    {
                        "success": False,
                        "response_ready": True,
                        "response": "Please specify at least one ticket id.",
                    }
                )

            tickets = [
                self._clean_ticket_detail(detail)
                for detail in (self._repository.get_ticket_detail(ticket_id) for ticket_id in normalized_ids)
                if detail
            ]
            if not tickets:
                return self._serialize(
                    {
                        "success": False,
                        "response_ready": True,
                        "response": "I couldn't find any visible tickets for those ticket ids.",
                    }
                )

            return self._serialize(
                {
                    "success": True,
                    "requested_ticket_ids": normalized_ids,
                    "tickets": tickets,
                }
            )

        @tool
        def get_ticket_activity(ticket_ids: List[str]) -> str:
            """
            Get recent activity for one or more specific HD ticket ids.

            Use this for timelines, comments, communications, replies, or
            recent updates on known tickets.
            """
            normalized_ids = self._normalize_ticket_ids(ticket_ids)
            if not normalized_ids:
                return self._serialize(
                    {
                        "success": False,
                        "response_ready": True,
                        "response": "Please specify at least one ticket id.",
                    }
                )

            items = []
            for ticket_id in normalized_ids:
                detail = self._repository.get_ticket_detail(ticket_id)
                if not detail:
                    continue
                activity = self._activity_service.get_ticket_activities(ticket_id)
                items.append(
                    {
                        "ticket": detail,
                        "activity": self._trim_activity(activity),
                    }
                )

            if not items:
                return self._serialize(
                    {
                        "success": False,
                        "response_ready": True,
                        "response": "I couldn't find any visible ticket activity for those ticket ids.",
                    }
                )

            return self._serialize(
                {
                    "success": True,
                    "requested_ticket_ids": normalized_ids,
                    "items": items,
                }
            )

        @tool
        def search_visible_tickets(
            search_text: str,
            customer_hint: str = "",
            limit: int = DEFAULT_LIST_LIMIT,
            offset: int = 0,
        ) -> str:
            """
            Search visible HD tickets by topic, keyword, or ticket text.

            Use this only when the user wants to find tickets by content rather
            than by explicit ticket id.
            Use offset for pagination when the user asks for the next set.
            """
            scope = self._scope_service.resolve_customer_scope(customer_hint=customer_hint, operation="read")
            if scope.clarify_question:
                return self._serialize(
                    {
                        "success": False,
                        "response_ready": True,
                        "response": scope.clarify_question,
                    }
                )

            filters = self._build_filters(scope.customer_name, "")
            limit_value = self._sanitize_limit(limit)
            offset_value = self._sanitize_offset(offset)
            tickets, match_sources = self._repository.search_tickets(
                search_text=search_text,
                filters=filters,
                limit=limit_value,
                offset=offset_value,
            )
            return self._serialize(
                {
                    "success": True,
                    "scope": self._scope_payload(scope),
                    "filters": filters,
                    "tickets": tickets,
                    "match_sources": match_sources,
                    "pagination": {
                        "tool_name": "search_visible_tickets",
                        "args": {
                            "search_text": search_text,
                            "customer_hint": customer_hint,
                            "limit": limit_value,
                            "offset": offset_value,
                        },
                        "returned_count": len(tickets),
                        "next_offset": offset_value + len(tickets),
                    },
                }
            )

        @tool
        def prepare_hd_ticket_create_plan(
            subject: str = "",
            description: str = "",
            priority: str = "",
            customer_hint: str = "",
        ) -> str:
            """
            Prepare an approval-backed plan to create a new HD ticket.

            Use this only when the user wants to create, raise, open, log, file,
            or submit a new ticket. Subject, description, and priority are
            required. If any are missing, the tool response tells you exactly
            what to ask next.
            """
            result = self._create_service.create_ticket(
                subject=subject,
                description=description,
                priority=priority,
                customer_hint=customer_hint,
            )
            return self._serialize(result)

        @tool
        def prepare_hd_ticket_comment_plan(ticket_id: str = "", content: str = "") -> str:
            """
            Prepare an approval-backed plan to add an internal comment to a ticket.

            Use this when the user wants to add an internal note or comment to a
            known HD ticket. Ticket id and comment text are required.
            """
            result = self._write_service.prepare_comment_plan(
                ticket_id=ticket_id,
                content=content,
            )
            return self._serialize(result)

        @tool
        def prepare_hd_ticket_communication_plan(
            ticket_id: str = "", message: str = ""
        ) -> str:
            """
            Prepare an approval-backed plan to add a communication to a ticket.

            Use this when the user wants to add a communication or reply entry
            to a known HD ticket. Ticket id and communication text are required.
            """
            result = self._write_service.prepare_communication_plan(
                ticket_id=ticket_id,
                message=message,
            )
            return self._serialize(result)

        return [
            list_visible_tickets,
            count_visible_tickets,
            get_ticket_details,
            get_ticket_activity,
            search_visible_tickets,
            prepare_hd_ticket_create_plan,
            prepare_hd_ticket_comment_plan,
            prepare_hd_ticket_communication_plan,
        ]

    def _build_filters(self, customer_name: str, status: str) -> Dict[str, Any]:
        filters: Dict[str, Any] = {}
        if customer_name:
            filters["customer"] = customer_name
        if status:
            filters["status"] = status.strip()
        return filters

    def _scope_payload(self, scope) -> Dict[str, Any]:
        return {
            "mode": scope.mode,
            "customer_name": scope.customer_name,
            "customer_label": scope.customer_label,
            "visible_customers": scope.visible_customers,
        }

    def _sanitize_limit(self, limit: int) -> int:
        try:
            value = int(limit or DEFAULT_LIST_LIMIT)
        except Exception:
            value = DEFAULT_LIST_LIMIT
        return max(1, min(value, MAX_LIST_LIMIT))

    def _sanitize_offset(self, offset: int) -> int:
        try:
            value = int(offset or 0)
        except Exception:
            value = 0
        return max(value, 0)

    def _normalize_ticket_ids(self, ticket_ids: List[str]) -> List[str]:
        normalized = []
        seen = set()
        for ticket_id in ticket_ids or []:
            text = str(ticket_id or "").strip().upper()
            if not text:
                continue
            if text.isdigit():
                text = text.zfill(4)
            if text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _trim_activity(self, activity: Dict[str, Any]) -> Dict[str, Any]:
        trimmed = {}
        for key in ("communications", "comments", "history", "calls", "views"):
            value = activity.get(key) if isinstance(activity, dict) else []
            if isinstance(value, list):
                trimmed[key] = [self._clean_activity_item(item) for item in value[:MAX_ACTIVITY_ITEMS]]
            else:
                trimmed[key] = value or []
        return trimmed

    def _clean_ticket_detail(self, detail: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(detail or {})
        if cleaned.get("description"):
            cleaned["description"] = to_plain_text(cleaned.get("description"))
        return cleaned

    def _clean_activity_item(self, item: Any) -> Any:
        if not isinstance(item, dict):
            return item

        cleaned = dict(item)
        summary_points: list[str] = []
        for field_name in ("content", "message", "description"):
            if cleaned.get(field_name):
                points = summarize_text_points(cleaned.get(field_name))
                cleaned[field_name] = " ".join(points) if points else to_plain_text(cleaned.get(field_name))
                if points:
                    cleaned[f"{field_name}_summary_points"] = points
                    if not summary_points:
                        summary_points = points
        if summary_points:
            cleaned["summary_points"] = summary_points
        cleaned["activity_date"] = (
            cleaned.get("communication_date")
            or cleaned.get("creation")
            or cleaned.get("modified")
            or ""
        )
        return cleaned

    def _serialize(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, default=str, ensure_ascii=False)
