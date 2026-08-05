"""Customer-specific RAG adapter built on top of the shared RagService."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils.file_manager import save_file

from ampower_jive.agent.rag_service import RagService, RagSettings, DEFAULT_CHAT_MODEL, DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, DEFAULT_EMBEDDING_MODEL, DEFAULT_HYBRID_WEIGHT, DEFAULT_INDEX_BACKEND, DEFAULT_KEYWORD_WEIGHT, DEFAULT_TOP_K
from ampower_jive.utils.company_permissions import can_access_scoped_vector_database
from ampower_jive.utils.config_provider import get_config_provider
from ampower_jive.utils.interaction_logger import InteractionLogger


VECTOR_DATABASE_DOCTYPE = "Jive Vector Data Base"
VECTOR_DATABASE_DOCUMENT_DOCTYPE = "Jive Vector Data Base Document"
# Reciprocal Rank Fusion uses this constant to merge results from multiple knowledge bases
# fairly, so one source does not dominate only because it returned more matches.
RRF_RANKING_K = 60


def _json_default(value: Any) -> str:
    """Serialize datetime-like values safely for JSON logging and storage."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class VectorDatabaseRagService(RagService):
    """Thin adapter that reuses the shared RAG pipeline for one vector database."""

    def __init__(self, vector_database_name: str, site_name: Optional[str] = None):
        super().__init__(site_name=site_name)
        self.vector_database_name = (vector_database_name or "").strip()

    def get_config(self):
        if not self.vector_database_name:
            raise frappe.ValidationError("Vector database name is required.")

        doc = frappe.get_doc(VECTOR_DATABASE_DOCTYPE, self.vector_database_name)
        doc.rag_processing_status = getattr(doc, "status", "Draft")
        doc.rag_last_processed = getattr(doc, "last_indexed_at", None)
        doc.rag_manifest_json_path = getattr(doc, "manifest_file", "")
        doc.rag_index_path = getattr(doc, "index_file", "")
        doc.rag_chunk_store_path = getattr(doc, "chunk_store_file", "")
        return doc

    def get_documents(self) -> List[Any]:
        doc = self.get_config()
        return [row for row in (getattr(doc, "rag_documents", []) or []) if getattr(row, "document_file", None)]

    def get_settings(self) -> RagSettings:
        config = get_config_provider().get_local_config()
        return RagSettings(
            embedding_model=str(getattr(config, "user_specific_rag_embedding_model", None) or DEFAULT_EMBEDDING_MODEL).strip(),
            chunk_size=max(200, int(getattr(config, "user_specific_rag_chunk_size", None) or DEFAULT_CHUNK_SIZE)),
            chunk_overlap=max(
                0,
                min(
                    int(getattr(config, "user_specific_rag_chunk_overlap", None) or DEFAULT_CHUNK_OVERLAP),
                    max(0, int(getattr(config, "user_specific_rag_chunk_size", None) or DEFAULT_CHUNK_SIZE) - 1),
                ),
            ),
            top_k=max(1, int(getattr(config, "user_specific_rag_top_k", None) or DEFAULT_TOP_K)),
            answer_model=str(getattr(config, "user_specific_rag_answer_model", None) or DEFAULT_CHAT_MODEL).strip(),
            temperature=float(getattr(config, "user_specific_rag_temperature", None) or 0.3),
            max_tokens=max(1, int(getattr(config, "user_specific_rag_max_tokens", None) or 4096)),
            index_backend=str(getattr(config, "user_specific_rag_index_backend", None) or DEFAULT_INDEX_BACKEND).strip().lower(),
            enable_incremental_indexing=bool(int(getattr(config, "user_specific_rag_enable_incremental_indexing", 1) or 1)),
            enable_embedding_cache=bool(int(getattr(config, "user_specific_rag_enable_embedding_cache", 1) or 1)),
            enable_hybrid_search=bool(int(getattr(config, "user_specific_rag_enable_hybrid_search", 1) or 1)),
            enable_metadata_filtering=bool(int(getattr(config, "user_specific_rag_enable_metadata_filtering", 1) or 1)),
            enable_streaming=bool(int(getattr(config, "user_specific_rag_enable_streaming", 1) or 1)),
            hybrid_weight=float(getattr(config, "user_specific_rag_hybrid_weight", DEFAULT_HYBRID_WEIGHT) or DEFAULT_HYBRID_WEIGHT),
            keyword_weight=float(getattr(config, "user_specific_rag_keyword_weight", DEFAULT_KEYWORD_WEIGHT) or DEFAULT_KEYWORD_WEIGHT),
        )

    def _current_artifact_state(self) -> Dict[str, Any]:
        return {
            "manifest": self._load_artifact_field("rag_manifest_json_path", default={}) or {},
            "index": self._load_artifact_field("rag_index_path", default={}) or {},
            "chunks": self._load_artifact_field("rag_chunk_store_path", default=[]) or [],
        }

    def _save_artifact_file(self, file_name: str, payload: Any) -> str:
        content = payload
        if not isinstance(content, (bytes, bytearray)):
            content = json.dumps(payload, ensure_ascii=False, default=_json_default, separators=(",", ":"))

        file_doc = save_file(
            file_name,
            content,
            VECTOR_DATABASE_DOCTYPE,
            self.vector_database_name,
            is_private=1,
        )
        return file_doc.file_url

    def _delete_artifact_file(self, file_url: str) -> None:
        return super()._delete_artifact_file(file_url)

    def _set_config_fields(self, **fields: Any) -> None:
        mapped_fields: Dict[str, Any] = {}
        for fieldname, value in fields.items():
            if fieldname == "rag_processing_status":
                mapped_fields["status"] = value
            elif fieldname == "rag_last_processed":
                mapped_fields["last_indexed_at"] = value
            elif fieldname == "rag_manifest_json_path":
                mapped_fields["manifest_file"] = value
            elif fieldname == "rag_index_path":
                mapped_fields["index_file"] = value
            elif fieldname == "rag_chunk_store_path":
                mapped_fields["chunk_store_file"] = value
            elif fieldname == "rag_processing_error":
                mapped_fields["processing_error"] = value
            elif fieldname == "rag_document_count":
                mapped_fields["document_count"] = value
            elif fieldname == "rag_chunk_count":
                mapped_fields["chunk_count"] = value
            elif fieldname == "rag_vector_count":
                mapped_fields["vector_count"] = value
            elif fieldname == "rag_source_signature":
                mapped_fields["source_signature"] = value
            elif fieldname == "rag_build_signature":
                mapped_fields["build_signature"] = value
            else:
                mapped_fields[fieldname] = value

        for fieldname, value in mapped_fields.items():
            frappe.db.set_value(VECTOR_DATABASE_DOCTYPE, self.vector_database_name, fieldname, value, update_modified=False)
        self._doc = None

    def _update_rag_document_row(self, row_name: str, values: Dict[str, Any]) -> None:
        if row_name:
            frappe.db.set_value(VECTOR_DATABASE_DOCUMENT_DOCTYPE, row_name, values, update_modified=False)

    def queue_processing(self) -> Dict[str, Any]:
        doc = self.get_config()
        if not frappe.has_permission(VECTOR_DATABASE_DOCTYPE, "write", doc.name):
            return {"success": False, "message": "You do not have permission to process this vector database."}

        if not self.get_documents():
            return {"success": False, "message": "Add at least one document before processing the vector database."}

        if getattr(doc, "status", "") in {"Queued", "Processing"}:
            return {"success": False, "message": "This vector database is already queued or running."}

        self._set_config_fields(rag_processing_status="Queued")
        frappe.enqueue(
            "ampower_jive.agent.vector_database_service.build_vector_database_index",
            queue="long",
            timeout=1800,
            is_async=True,
            enqueue_after_commit=True,
            vector_database_name=self.vector_database_name,
            site_name=self.site_name,
        )
        return {"success": True, "queued": True, "message": "Vector database processing queued."}

    def build_index(self) -> Dict[str, Any]:
        result = super().build_index()
        if result.get("success"):
            manifest = self._current_artifact_state().get("manifest") or {}
            signature = manifest.get("document_signature") or self._current_document_signature()
            documents = manifest.get("documents") or []
            has_unindexed_documents = any((doc.get("status") or "").strip().title() != "Indexed" for doc in documents if isinstance(doc, dict))
            final_status = "Ready" if not has_unindexed_documents else "Stale"
            processing_error = "" if not has_unindexed_documents else "; ".join(
                sorted(
                    {
                        str(doc.get("error") or doc.get("status") or "Unindexed document")
                        for doc in documents
                        if isinstance(doc, dict) and (doc.get("status") or "").strip().title() != "Indexed"
                    }
                )
            )
            self._set_config_fields(
                status=final_status,
                processing_error=processing_error,
                source_signature=signature,
                build_signature=signature,
                rag_document_count=manifest.get("document_count") or result.get("documents_processed") or 0,
                rag_chunk_count=manifest.get("chunk_count") or result.get("chunks_created") or 0,
                rag_vector_count=manifest.get("vector_count") or result.get("chunks_created") or 0,
            )
        return result

    def _assert_query_allowed(self, user: str) -> None:
        doc = self.get_config()
        if not can_access_scoped_vector_database(
            user,
            company=getattr(doc, "company", None),
            customer=getattr(doc, "customer", None),
        ):
            raise frappe.ValidationError("You do not have permission to query this vector database.")

    def _load_query_artifacts(self, question: str):
        """Validate vector-database freshness before loading reusable query artifacts."""
        doc = self.get_config()

        current_signature = self._current_document_signature()
        manifest = self._current_artifact_state().get("manifest") or {}
        documents = getattr(doc, "rag_documents", []) or []
        has_unindexed_documents = any(
            (getattr(row, "status", "") or "Pending").strip().title() not in {"Indexed", "Queued", "Processing"}
            for row in documents
        )
        if manifest.get("document_signature") and manifest.get("document_signature") != current_signature:
            self._set_config_fields(status="Stale", source_signature=current_signature)
            raise frappe.ValidationError("This vector database has changed. Rebuild it before querying.")

        if getattr(doc, "status", "") == "Stale" or has_unindexed_documents:
            if has_unindexed_documents and getattr(doc, "status", "") != "Stale":
                self._set_config_fields(status="Stale")
            raise frappe.ValidationError("This vector database is stale. Rebuild it before querying.")

        return super()._load_query_artifacts(question)

    def query(self, *args, **kwargs) -> Dict[str, Any]:
        user = (kwargs.get("user") or frappe.session.user or "").strip()
        try:
            self._assert_query_allowed(user)
        except frappe.ValidationError as exc:
            return {
                "success": False,
                "message": str(exc),
            }

        return super().query(*args, **kwargs)

    def _get_not_ready_message(self) -> str:
        return "Vector database is not processed yet. Please process it from Jive Vector Data Base first."


class MultiVectorDatabaseRagService(RagService):
    """Query multiple vector databases and synthesize one grounded answer."""

    def __init__(self, vector_database_names: List[str], site_name: Optional[str] = None):
        super().__init__(site_name=site_name)
        self.vector_database_names = self._normalize_vector_database_names(vector_database_names)

    @staticmethod
    def _normalize_vector_database_names(vector_database_names: List[str]) -> List[str]:
        """Trim and deduplicate linked vector database names while preserving order."""
        normalized: List[str] = []
        seen = set()
        for value in vector_database_names or []:
            name = str(value or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append(name)
        return normalized

    @staticmethod
    def _score_key(chunk: Dict[str, Any]) -> float:
        """Read a chunk score as a float so sorting and ranking stay consistent."""
        return float(chunk.get("score", 0.0) or 0.0)

    def _source_summary(self, service: VectorDatabaseRagService) -> Dict[str, str]:
        """Return a compact source label for logs, errors, and response metadata."""
        vector_database_key = service.vector_database_name
        try:
            vector_database_key = str(getattr(service.get_config(), "vdb_key", "") or service.vector_database_name).strip()
        except Exception:
            pass
        return {
            "vector_database_name": service.vector_database_name,
            "vector_database_key": vector_database_key,
        }

    @staticmethod
    def _settings_snapshot(settings: RagSettings) -> Dict[str, Any]:
        """Capture the settings that must match before multi-source retrieval can run."""
        return {
            "embedding_model": settings.embedding_model,
            "top_k": settings.top_k,
            "answer_model": settings.answer_model,
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
            "enable_hybrid_search": settings.enable_hybrid_search,
            "enable_metadata_filtering": settings.enable_metadata_filtering,
            "enable_streaming": settings.enable_streaming,
            "hybrid_weight": settings.hybrid_weight,
            "keyword_weight": settings.keyword_weight,
        }

    def _validate_consistent_settings(self, ready_sources: List[Any]) -> None:
        """Block multi-source retrieval when linked knowledge bases use mixed settings."""
        if len(ready_sources) <= 1:
            return

        baseline_service, baseline_artifacts = ready_sources[0]
        baseline_snapshot = self._settings_snapshot(baseline_artifacts.settings)
        mismatches = []

        for service, artifacts in ready_sources[1:]:
            current_snapshot = self._settings_snapshot(artifacts.settings)
            differences = {
                fieldname: {
                    "expected": baseline_snapshot[fieldname],
                    "actual": current_snapshot[fieldname],
                }
                for fieldname in baseline_snapshot
                if baseline_snapshot[fieldname] != current_snapshot[fieldname]
            }
            if differences:
                mismatches.append(
                    {
                        "baseline_source": self._source_summary(baseline_service),
                        "conflicting_source": self._source_summary(service),
                        "differences": differences,
                    }
                )

        if mismatches:
            frappe.log_error(
                message=json.dumps(mismatches, indent=2, default=_json_default),
                title="Jive Multi RAG Settings Mismatch",
            )
            raise frappe.ValidationError(
                "Linked vector databases must use the same retrieval and answer settings before running multi-source RAG."
            )

    @staticmethod
    def _chunk_identity(chunk: Dict[str, Any]) -> tuple:
        """Decide whether chunks from different knowledge bases are the same chunk.

        This is used to avoid sending duplicate context to the answer step.
        """
        checksum = str(chunk.get("checksum", "") or "").strip()
        file_url = str(chunk.get("file_url", "") or "").strip()
        file_name = str(chunk.get("file_name", "") or "").strip().lower()
        document_title = str(chunk.get("original_document_title") or chunk.get("document_title") or "").strip().lower()
        chunk_index = int(chunk.get("chunk_index") or 0)
        chunk_hash = str(chunk.get("chunk_hash", "") or "").strip()
        if not chunk_hash:
            chunk_hash = hashlib.sha1(str(chunk.get("text", "") or "").encode("utf-8")).hexdigest()

        if checksum:
            return ("checksum", checksum, chunk_index, chunk_hash)
        if file_url:
            return ("file_url", file_url, chunk_index, chunk_hash)
        return ("logical", file_name, document_title, chunk_index, chunk_hash)

    def _annotate_retrieved_chunk(
        self,
        vector_database_service: VectorDatabaseRagService,
        chunk: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Attach source metadata so merged results keep their originating KB context."""
        config = vector_database_service.get_config()
        vector_database_key = str(getattr(config, "vdb_key", "") or vector_database_service.vector_database_name).strip()
        original_title = chunk.get("document_title") or chunk.get("file_name") or "Document"

        annotated_chunk = dict(chunk)
        annotated_chunk["vector_database_name"] = vector_database_service.vector_database_name
        annotated_chunk["vector_database_key"] = vector_database_key
        annotated_chunk["document_title"] = f"{vector_database_key} / {original_title}"
        annotated_chunk["original_document_title"] = original_title
        annotated_chunk["score"] = self._score_key(chunk)
        return annotated_chunk

    def _merge_retrieved_chunks(
        self,
        results_by_source: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Merge and rank chunks across all linked knowledge bases.

        NOTE: top_k here is one shared final limit across all linked knowledge bases
        combined, not a separate limit per knowledge base.
        """
        merged_chunks_by_identity: Dict[tuple, Dict[str, Any]] = {}

        for source_index, source_result in enumerate(results_by_source):
            source_meta = source_result.get("source") or {}
            source_chunks = source_result.get("chunks") or []

            for rank, chunk in enumerate(source_chunks, start=1):
                dedupe_key = self._chunk_identity(chunk)
                reciprocal_rank_score = 1.0 / float(RRF_RANKING_K + rank)
                matched_source = {
                    "vector_database_name": source_meta.get("vector_database_name") or chunk.get("vector_database_name"),
                    "vector_database_key": source_meta.get("vector_database_key") or chunk.get("vector_database_key"),
                    "rank": rank,
                    "source_score": self._score_key(chunk),
                }

                existing_chunk = merged_chunks_by_identity.get(dedupe_key)
                if not existing_chunk:
                    enriched_chunk = dict(chunk)
                    enriched_chunk["score"] = reciprocal_rank_score
                    enriched_chunk["rrf_score"] = reciprocal_rank_score
                    enriched_chunk["best_source_score"] = self._score_key(chunk)
                    enriched_chunk["best_rank"] = rank
                    enriched_chunk["first_source_index"] = source_index
                    enriched_chunk["matched_sources"] = [matched_source]
                    merged_chunks_by_identity[dedupe_key] = enriched_chunk
                    continue

                existing_chunk["score"] = float(existing_chunk.get("score", 0.0) or 0.0) + reciprocal_rank_score
                existing_chunk["rrf_score"] = existing_chunk["score"]
                existing_chunk["matched_sources"] = list(existing_chunk.get("matched_sources") or []) + [matched_source]

                if self._score_key(chunk) > float(existing_chunk.get("best_source_score", 0.0) or 0.0):
                    existing_chunk["best_source_score"] = self._score_key(chunk)
                    existing_chunk["best_rank"] = rank
                    existing_chunk["first_source_index"] = min(
                        int(existing_chunk.get("first_source_index", source_index) or source_index),
                        source_index,
                    )
                    existing_chunk["vector_database_name"] = chunk.get("vector_database_name")
                    existing_chunk["vector_database_key"] = chunk.get("vector_database_key")
                    existing_chunk["document_title"] = chunk.get("document_title")
                    existing_chunk["original_document_title"] = chunk.get("original_document_title")
                    existing_chunk["file_name"] = chunk.get("file_name")
                    existing_chunk["file_url"] = chunk.get("file_url")
                    existing_chunk["chunk_index"] = chunk.get("chunk_index")
                    existing_chunk["text"] = chunk.get("text")
                    existing_chunk["checksum"] = chunk.get("checksum")
                    existing_chunk["chunk_hash"] = chunk.get("chunk_hash")

        merged_chunks = sorted(
            merged_chunks_by_identity.values(),
            key=lambda chunk: (
                -float(chunk.get("score", 0.0) or 0.0),
                int(chunk.get("first_source_index", 0) or 0),
                int(chunk.get("best_rank", 0) or 0),
                -float(chunk.get("best_source_score", 0.0) or 0.0),
            ),
        )
        finalized_chunks = merged_chunks[: max(1, top_k)]

        return finalized_chunks

    def query(
        self,
        question: str,
        history: Optional[List[Dict[str, Any]]] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user: Optional[str] = None,
        context_aware: bool = False,
        context_payload: Any = None,
        stream: bool = False,
        stream_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        question = (question or "").strip()
        if not question:
            return {"success": False, "message": "Question cannot be empty."}

        if not self.vector_database_names:
            return {"success": False, "message": "No vector databases are configured for this user."}

        started_at = time.time()
        active_user = (user or frappe.session.user or "").strip()
        services: List[VectorDatabaseRagService] = [
            VectorDatabaseRagService(vector_database_name=name, site_name=self.site_name)
            for name in self.vector_database_names
        ]

        ready_sources = []
        failed_sources: List[Dict[str, str]] = []
        for service in services:
            try:
                service._assert_query_allowed(active_user)
                artifacts = service._load_query_artifacts(question)
                ready_sources.append((service, artifacts))
            except frappe.ValidationError as exc:
                failed_source = self._source_summary(service)
                failed_source["error"] = str(exc)
                failed_sources.append(failed_source)

        if not ready_sources:
            return {
                "success": False,
                "message": failed_sources[0]["error"] if failed_sources else "No queryable vector database is available.",
                "partial_results": False,
                "failed_sources": failed_sources,
            }

        try:
            self._validate_consistent_settings(ready_sources)
        except frappe.ValidationError as exc:
            return {
                "success": False,
                "message": str(exc),
                "partial_results": False,
                "failed_sources": failed_sources,
                "queried_sources": [self._source_summary(service) for service, _ in ready_sources],
            }

        if failed_sources:
            try:
                frappe.log_error(
                    message=json.dumps(
                        {
                            "requested_sources": [self._source_summary(service) for service in services],
                            "queried_sources": [self._source_summary(service) for service, _ in ready_sources],
                            "failed_sources": failed_sources,
                        },
                        indent=2,
                        default=_json_default,
                    ),
                    title="Jive Multi RAG Skipped Sources",
                )
            except Exception:
                pass

        _, primary_artifacts = ready_sources[0]
        primary_settings = primary_artifacts.settings
        retrieval_strategy, query_variants, query_generation_usage = self._resolve_query_variants(
            question=question,
            context_aware=bool(context_aware),
            context_payload=context_payload,
            settings=primary_settings,
        )

        source_results: List[Dict[str, Any]] = []
        for service, artifacts in ready_sources:
            chunks = service._retrieve_chunks_for_queries(
                query_variants,
                artifacts.index_payload,
                artifacts.chunks,
                artifacts.settings,
            )
            if not chunks:
                continue

            source_results.append(
                {
                    "source": self._source_summary(service),
                    "chunks": [
                        self._annotate_retrieved_chunk(service, chunk)
                        for chunk in chunks
                    ],
                }
            )

        global_top_k = max(1, primary_settings.top_k)
        retrieved_chunks = self._merge_retrieved_chunks(source_results, global_top_k)
        if not retrieved_chunks:
            return {"success": False, "message": "No relevant information could be found in the indexed documents."}

        messages = self._compose_messages(
            question=question,
            history=history or [],
            retrieved_chunks=retrieved_chunks,
            context_payload=context_payload,
            context_aware=bool(context_aware),
            include_context_payload=not (bool(context_aware) and context_payload),
            query_variants=query_variants,
        )
        completion = self._chat_completion(
            messages,
            model=primary_settings.answer_model,
            temperature=primary_settings.temperature,
            max_tokens=primary_settings.max_tokens,
            stream=bool(stream and primary_settings.enable_streaming),
            stream_callback=stream_callback,
        )

        choices = completion.get("choices", [])
        if not choices:
            return {"success": False, "message": "No completion was returned by the model."}

        answer_text = ((choices[0].get("message") or {}).get("content") or "").strip()
        answer_text = self._append_followup_suggestions(question, answer_text, history or [])
        partial_results = bool(failed_sources)
        if partial_results:
            skipped_source_labels = ", ".join(
                source.get("vector_database_key") or source.get("vector_database_name") or "Unknown Source"
                for source in failed_sources[:3]
            )
            if len(failed_sources) > 3:
                skipped_source_labels += f", and {len(failed_sources) - 3} more"
            answer_text = (
                "Note: This answer is based on partial results. "
                f"Some linked knowledge bases were skipped: {skipped_source_labels}.\n\n"
                f"{answer_text}"
            )
        answer_usage = completion.get("usage") or {}
        usage = self._merge_usage(query_generation_usage, answer_usage)
        usage["query_generation"] = query_generation_usage
        usage["answer_generation"] = answer_usage
        tokens_in = usage["prompt_tokens"]
        tokens_out = usage["completion_tokens"]
        model_name = primary_settings.answer_model or DEFAULT_CHAT_MODEL

        try:
            get_config_provider().report_usage(
                agent_type="rag",
                model=model_name,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                user=active_user,
                session_id=session_id,
            )
        except Exception:
            frappe.log_error(message=f"Failed to report multi-source RAG usage: {frappe.get_traceback()}", title="Jive Multi RAG Usage Error")

        try:
            InteractionLogger("rag").log(
                request_data={
                    "mode": "rag",
                    "question": question,
                    "history": history or [],
                    "conversation_id": conversation_id,
                    "session_id": session_id,
                    "context_aware": bool(context_aware),
                    "context_payload": context_payload,
                    "retrieval_strategy": retrieval_strategy,
                    "query_variants": query_variants,
                    "query_generation_usage": query_generation_usage,
                    "requested_vector_databases": [service.vector_database_name for service in services],
                    "queried_vector_databases": [service.vector_database_name for service, _ in ready_sources],
                    "partial_results": partial_results,
                    "failed_sources": failed_sources,
                    "sources": [
                        {
                            "vector_database_name": chunk.get("vector_database_name"),
                            "vector_database_key": chunk.get("vector_database_key"),
                            "document_title": chunk.get("original_document_title"),
                            "file_name": chunk.get("file_name"),
                            "chunk_index": chunk.get("chunk_index"),
                            "score": chunk.get("score"),
                        }
                        for chunk in retrieved_chunks
                    ],
                },
                response_data=answer_text,
                model=model_name,
                status="success",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                processing_time_ms=int((time.time() - started_at) * 1000),
                user=active_user,
                session_id=session_id,
            )
        except Exception:
            pass

        return {
            "success": True,
            "response": answer_text,
            "mode": "rag",
            "agent_key": "rag",
            "conversation_id": conversation_id,
            "session_id": session_id,
            "partial_results": partial_results,
            "failed_sources": failed_sources,
            "queried_sources": [self._source_summary(service) for service, _ in ready_sources],
            "sources": [
                {
                    "vector_database_name": chunk.get("vector_database_name"),
                    "vector_database_key": chunk.get("vector_database_key"),
                    "document_title": chunk.get("original_document_title"),
                    "file_name": chunk.get("file_name"),
                    "file_url": chunk.get("file_url"),
                    "chunk_index": chunk.get("chunk_index"),
                    "score": chunk.get("score"),
                }
                for chunk in retrieved_chunks
            ],
            "usage": usage,
            "token_usage": getattr(frappe.local, "jive_token_usage", None),
            "index_backend": "multi",
            "retrieval_strategy": retrieval_strategy,
            "query_count": len(query_variants),
            "health": {
                "chunks": sum(len(result.get("chunks") or []) for result in source_results),
                "retrieved": len(retrieved_chunks),
                "index_backend": "multi",
                "validated": True,
                "retrieval_strategy": retrieval_strategy,
                "query_count": len(query_variants),
                "vector_database_count": len(ready_sources),
            },
        }


def build_vector_database_index(vector_database_name: str, site_name: Optional[str] = None) -> Dict[str, Any]:
    return VectorDatabaseRagService(vector_database_name, site_name=site_name).build_index()


def enqueue_vector_database_index_build(vector_database_name: str, site_name: Optional[str] = None) -> Dict[str, Any]:
    return VectorDatabaseRagService(vector_database_name, site_name=site_name).queue_processing()


def build_all_vector_database_indices(site_name: Optional[str] = None) -> Dict[str, Any]:
    rows = frappe.get_all(
        VECTOR_DATABASE_DOCTYPE,
        fields=["name"],
        filters={"status": ["!=", "Archived"]},
        order_by="modified desc",
    )
    results = []
    for row in rows:
        results.append(build_vector_database_index(row.name, site_name=site_name))
    return {"success": True, "results": results, "count": len(results)}


def enqueue_all_vector_database_index_builds(site_name: Optional[str] = None) -> Dict[str, Any]:
    frappe.enqueue(
        "ampower_jive.agent.vector_database_service.build_all_vector_database_indices",
        queue="long",
        timeout=3600,
        is_async=True,
        enqueue_after_commit=True,
        site_name=site_name or frappe.local.site,
    )
    return {"success": True, "queued": True, "message": "Vector database builds queued."}
