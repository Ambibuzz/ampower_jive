# Copyright (c) 2026, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class JiveConfigRAGDocument(Document):
    def validate(self):
        if getattr(self, "document_title", None):
            self.document_title = self.document_title.strip()
        if getattr(self, "document_file", None):
            self.document_file = self.document_file.strip()
        if getattr(self, "status", None):
            self.status = self.status.strip().title()
