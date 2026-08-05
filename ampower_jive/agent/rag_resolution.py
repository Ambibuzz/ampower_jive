"""Resolve which RAG knowledge base should serve the current request."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Dict, Iterable, List, Optional

import frappe

from ampower_jive.utils.config_provider import get_config_provider
from ampower_jive.utils.company_permissions import can_access_scoped_vector_database


CACHE_VERSION_KEY = "ampower_jive:rag_resolution:version"
CACHE_PREFIX = "ampower_jive:rag_resolution"
LEGACY_MODE = "legacy"
VECTOR_DATABASE_MODE = "customer_vdb"
RAG_USER_DOCTYPE = "Jive Rag User"
RAG_USER_CHILD_DOCTYPE = "Jive Rag User Vector Database"
RAG_USER_CHILD_FIELD = "linked_vector_databases"
LEGACY_VECTOR_DATABASE_FIELD = "jive_vector_database"


def _normalize_vector_databases(values: Iterable[Any]) -> List[str]:
    """Return trimmed vector database names while preserving first-seen order."""
    normalized: List[str] = []
    seen = set()
    for value in values:
        vector_database = str(value or "").strip()
        if not vector_database or vector_database in seen:
            continue
        seen.add(vector_database)
        normalized.append(vector_database)
    return normalized


@dataclass(frozen=True)
class RagTarget:
    """Resolved RAG destination for a chat or build request."""

    pipeline_mode: str
    vector_databases: List[str] = field(default_factory=list)
    vector_database: Optional[str] = None
    mapping_name: Optional[str] = None
    resolution_source: str = "legacy"
    customer_link: Optional[str] = None
    customer_id: Optional[str] = None

    def __post_init__(self) -> None:
        """Normalize linked vector databases and keep the first one for compatibility."""
        normalized_vector_databases = _normalize_vector_databases([*(self.vector_databases or []), self.vector_database])
        object.__setattr__(self, "vector_databases", normalized_vector_databases)
        object.__setattr__(self, "vector_database", normalized_vector_databases[0] if normalized_vector_databases else None)

    @property
    def is_vector_database_mode(self) -> bool:
        """Return whether this target should use vector-database-backed RAG."""
        return self.pipeline_mode == VECTOR_DATABASE_MODE and bool(self.vector_databases)

    @property
    def has_multiple_vector_databases(self) -> bool:
        """Return whether the resolved target spans more than one vector database."""
        return len(self.vector_databases) > 1


def _cache_version() -> str:
    """Read the cache-busting version used for resolved RAG targets."""
    version = frappe.cache().get_value(CACHE_VERSION_KEY)
    return str(version or "0")


def invalidate_cache(doc=None, method=None) -> None:
    """Bump the cache version so all future resolutions miss safely."""
    frappe.cache().set_value(CACHE_VERSION_KEY, frappe.utils.now_datetime().isoformat())


def _normalize_mode(value: Any) -> str:
    """Map configured pipeline mode text to the resolver's internal mode key."""
    text = str(value or "").strip().lower()
    if not text:
        return LEGACY_MODE
    if any(
        marker in text
        for marker in (
            "user specific",
            "user-specific",
            "user_specific",
            "customer specific",
            "customer-specific",
            "customer_specific",
            "vector database",
        )
    ) or text in {"vdb", "customer_vdb"}:
        return VECTOR_DATABASE_MODE
    return LEGACY_MODE


def _extract_context_hints(context_payload: Any) -> Dict[str, str]:
    """Pull customer routing hints from supported context payload shapes."""
    if not isinstance(context_payload, dict):
        return {}

    hints: Dict[str, str] = {}
    candidate_paths: Iterable[Dict[str, Any]] = (
        context_payload,
        context_payload.get("metadata") if isinstance(context_payload.get("metadata"), dict) else {},
        context_payload.get("page_field_values") if isinstance(context_payload.get("page_field_values"), dict) else {},
        context_payload.get("current_doc") if isinstance(context_payload.get("current_doc"), dict) else {},
    )
    for source in candidate_paths:
        if not isinstance(source, dict):
            continue
        for key in ("customer", "customer_link", "customer_name", "customer_id"):
            value = source.get(key)
            if value not in (None, "", [], {}):
                hints.setdefault(key, str(value).strip())
    return hints


class RagResolver:
    """Resolve a user to the applicable RAG source set using server-side rules."""

    def __init__(self):
        """Initialize the resolver with the shared configuration provider."""
        self._provider = get_config_provider()

    def get_pipeline_mode(self) -> str:
        """Return whether tenant RAG should use legacy or vector-database routing."""
        config = self._provider.get_local_config()
        if not config:
            return LEGACY_MODE
        return _normalize_mode(getattr(config, "rag_pipeline_mode", LEGACY_MODE))

    def resolve(
        self,
        user: Optional[str] = None,
        context_payload: Any = None,
        customer_link: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> RagTarget:
        """Resolve and cache the best RAG target for the current request context."""
        pipeline_mode = self.get_pipeline_mode()
        if pipeline_mode != VECTOR_DATABASE_MODE:
            target = RagTarget(
                pipeline_mode=LEGACY_MODE,
                resolution_source="config",
            )
            return target

        user = (user or frappe.session.user or "").strip()
        hints = _extract_context_hints(context_payload)
        customer_link = (customer_link or hints.get("customer") or hints.get("customer_link") or "").strip()
        customer_id = (customer_id or hints.get("customer_id") or hints.get("customer_name") or "").strip()

        cache_key = self._build_cache_key(user, customer_link, customer_id)
        cached = frappe.cache().get_value(cache_key)
        if cached:
            try:
                payload = json.loads(cached)
                cached_target = RagTarget(**payload)
                if self._is_target_allowed(user=user, target=cached_target):
                    return cached_target
            except Exception:
                pass

        target = self._resolve_target(user=user, customer_link=customer_link, customer_id=customer_id)
        frappe.cache().set_value(cache_key, json.dumps(target.__dict__), expires_in_sec=60)
        return target

    def _is_target_allowed(self, user: str, target: RagTarget) -> bool:
        """Re-check cached vector-database targets against the user's current scope."""
        if not target.is_vector_database_mode:
            return True

        return bool(self._filter_allowed_vector_databases(user, target.vector_databases))

    def _build_cache_key(self, user: str, customer_link: str, customer_id: str) -> str:
        """Build a short-lived cache key for one user's routing context."""
        return f"{CACHE_PREFIX}:{_cache_version()}:{user}:{customer_link}:{customer_id}"

    def _filter_allowed_vector_databases(self, user: str, vector_databases: Iterable[str]) -> List[str]:
        """Keep only vector databases the user can access for company and customer scope."""
        allowed_vector_databases: List[str] = []
        for vector_database_name in _normalize_vector_databases(vector_databases):
            scope = frappe.db.get_value(
                "Jive Vector Data Base",
                vector_database_name,
                ["company", "customer"],
                as_dict=True,
            )
            if can_access_scoped_vector_database(
                user,
                company=(scope or {}).get("company"),
                customer=(scope or {}).get("customer"),
            ):
                allowed_vector_databases.append(vector_database_name)
        return allowed_vector_databases

    def _log_permission_contradiction(
        self,
        user: str,
        resolution_source: str,
        mapping_name: Optional[str],
        vector_databases: Iterable[str],
        customer_link: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> None:
        """Log when routing matched a mapping but every linked vector database was denied."""
        try:
            denied_sources = []
            for vector_database_name in _normalize_vector_databases(vector_databases):
                scope = frappe.db.get_value(
                    "Jive Vector Data Base",
                    vector_database_name,
                    ["company", "customer", "customer_id"],
                    as_dict=True,
                ) or {}
                denied_sources.append(
                    {
                        "vector_database_name": vector_database_name,
                        "company": scope.get("company"),
                        "customer": scope.get("customer"),
                        "customer_id": scope.get("customer_id"),
                    }
                )

            frappe.log_error(
                message=json.dumps(
                    {
                        "user": user or frappe.session.user,
                        "mapping_name": mapping_name,
                        "resolution_source": resolution_source,
                        "customer_link": customer_link,
                        "customer_id": customer_id,
                        "requested_vector_databases": _normalize_vector_databases(vector_databases),
                        "denied_sources": denied_sources,
                    },
                    indent=2,
                ),
                title="Jive RAG Permission Contradiction",
            )
        except Exception:
            pass

    def _raise_inaccessible_mapping(
        self,
        user: str,
        row: Dict[str, Any],
        resolution_source: str,
    ) -> None:
        """Log and fail immediately when a matched mapping cannot be used.

        NOTE: This raises an error immediately and stops further resolution.
        """
        vector_databases = row.get("vector_databases") or []
        if not vector_databases:
            return

        self._log_permission_contradiction(
            user=user,
            resolution_source=resolution_source,
            mapping_name=row.get("name"),
            vector_databases=vector_databases,
            customer_link=row.get("customer_link"),
            customer_id=row.get("customer_id"),
        )
        raise frappe.ValidationError("The retrieved data does not have any information.")

    def _legacy_vector_database_field_exists(self) -> bool:
        """Return whether the old single-VDB column still exists in the table."""
        result = frappe.db.sql(
            "SHOW COLUMNS FROM `tabJive Rag User` LIKE %s",
            (LEGACY_VECTOR_DATABASE_FIELD,),
        )
        return bool(result)

    def _get_mapping_rows(self) -> List[Dict[str, Any]]:
        """Load active routing rows together with their linked vector databases."""
        rows = frappe.get_all(
            RAG_USER_DOCTYPE,
            fields=[
                "name",
                "user",
                "user_mandate",
                "customer_link",
                "customer_id",
                "is_active",
            ],
            filters={"is_active": 1},
            order_by="priority asc, modified desc",
        )
        if not rows:
            return []

        mapping_names = [row.get("name") for row in rows if row.get("name")]
        child_rows = frappe.get_all(
            RAG_USER_CHILD_DOCTYPE,
            fields=["parent", "jive_vector_database", "idx"],
            filters={
                "parent": ["in", mapping_names],
                "parenttype": RAG_USER_DOCTYPE,
                "parentfield": RAG_USER_CHILD_FIELD,
            },
            order_by="parent asc, idx asc, modified asc",
        )

        vector_databases_by_mapping = {
            mapping_name: []
            for mapping_name in mapping_names
        }
        for child_row in child_rows:
            vector_databases_by_mapping.setdefault(child_row.get("parent"), []).append(child_row.get("jive_vector_database"))

        if self._legacy_vector_database_field_exists():
            legacy_rows = frappe.db.sql(
                """
                SELECT name, jive_vector_database
                FROM `tabJive Rag User`
                WHERE name IN %(mapping_names)s
                  AND IFNULL(jive_vector_database, '') != ''
                """,
                {"mapping_names": tuple(mapping_names)},
                as_dict=True,
            )
            for legacy_row in legacy_rows:
                if vector_databases_by_mapping.get(legacy_row.get("name")):
                    continue
                vector_databases_by_mapping.setdefault(legacy_row.get("name"), []).append(legacy_row.get("jive_vector_database"))

        for row in rows:
            row["vector_databases"] = _normalize_vector_databases(vector_databases_by_mapping.get(row.get("name"), []))
        return rows

    def _build_target(
        self,
        row: Dict[str, Any],
        resolution_source: str,
        user: str,
    ) -> Optional[RagTarget]:
        """Build a resolved target after filtering out inaccessible vector databases."""
        vector_databases = self._filter_allowed_vector_databases(user, row.get("vector_databases") or [])
        if not vector_databases:
            return None

        return RagTarget(
            pipeline_mode=VECTOR_DATABASE_MODE,
            vector_databases=vector_databases,
            mapping_name=row.get("name"),
            resolution_source=resolution_source,
            customer_link=row.get("customer_link"),
            customer_id=row.get("customer_id"),
        )

    def _resolve_target(self, user: str, customer_link: str, customer_id: str) -> RagTarget:
        """Resolve the best matching RAG target in user, customer, then default order."""
        config = self._provider.get_local_config()
        rows = self._get_mapping_rows()

        for row in rows:
            if (
                row.get("user")
                and row.get("user") == user
                and row.get("user_mandate")
            ):
                target = self._build_target(row, "user", user)
                if target:
                    return target
                self._raise_inaccessible_mapping(user, row, "user")

        for row in rows:
            if (
                row.get("user")
                and row.get("user") == user
            ):
                target = self._build_target(row, "user", user)
                if target:
                    return target
                self._raise_inaccessible_mapping(user, row, "user")

        for row in rows:
            if not row.get("vector_databases"):
                continue
            if customer_link and row.get("customer_link") == customer_link:
                target = self._build_target(row, "customer_link", user)
                if target:
                    return target
                self._raise_inaccessible_mapping(user, row, "customer_link")
            if customer_id and row.get("customer_id") == customer_id:
                target = self._build_target(row, "customer_id", user)
                if target:
                    return target
                self._raise_inaccessible_mapping(user, row, "customer_id")

        default_vdb = config.get("rag_default_vector_database") if config else None
        default_vector_databases = self._filter_allowed_vector_databases(user, [default_vdb]) if default_vdb else []
        if default_vector_databases:
            return RagTarget(
                pipeline_mode=VECTOR_DATABASE_MODE,
                vector_databases=default_vector_databases,
                resolution_source="config_default",
            )
        if default_vdb:
            self._log_permission_contradiction(
                user=user,
                resolution_source="config_default",
                mapping_name=None,
                vector_databases=[default_vdb],
            )
            raise frappe.ValidationError("The retrieved data does not have any information.")

        if not rows:
            raise frappe.ValidationError("No Jive Rag User mappings are configured.")
        raise frappe.ValidationError("No active JIVE Vector Data Base is mapped for this user.")


def resolve_rag_target(
    user: Optional[str] = None,
    context_payload: Any = None,
    customer_link: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> RagTarget:
    """Convenience wrapper for resolving the current request to a RAG target."""
    return RagResolver().resolve(
        user=user,
        context_payload=context_payload,
        customer_link=customer_link,
        customer_id=customer_id,
    )
