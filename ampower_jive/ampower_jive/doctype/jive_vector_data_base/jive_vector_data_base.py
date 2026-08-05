# Copyright (c) 2026, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import hashlib
import json

from frappe.model.document import Document


class JiveVectorDataBase(Document):
    def validate(self):
        status = (getattr(self, "status", "") or "Draft").strip().title()
        self.status = status
        if getattr(self, "vdb_key", None):
            self.vdb_key = self.vdb_key.strip()
        if getattr(self, "customer", None):
            self.customer = self.customer.strip()
        if getattr(self, "company", None):
            self.company = self.company.strip()
        if getattr(self, "customer_id", None):
            self.customer_id = self.customer_id.strip()
        if getattr(self, "notes", None):
            self.notes = self.notes.strip()
        if getattr(self, "processing_error", None):
            self.processing_error = self.processing_error.strip()

        source_signature = self._compute_source_signature()
        self.source_signature = source_signature

    def _compute_source_signature(self):
        rows = []
        for row in (getattr(self, "rag_documents", []) or []):
            rows.append(
                {
                    "name": getattr(row, "name", ""),
                    "document_title": getattr(row, "document_title", ""),
                    "document_file": getattr(row, "document_file", ""),
                    "checksum": getattr(row, "checksum", ""),
                    "notes": getattr(row, "notes", ""),
                }
            )
        return hashlib.sha1(json.dumps(rows, sort_keys=True, default=str).encode("utf-8")).hexdigest()
