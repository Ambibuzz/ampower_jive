# Copyright (c) 2026, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class JiveRagUser(Document):
    def validate(self):
        if getattr(self, "user", None):
            self.user = self.user.strip()
        if getattr(self, "customer_link", None):
            self.customer_link = self.customer_link.strip()
        if getattr(self, "customer_id", None):
            self.customer_id = self.customer_id.strip()
        if getattr(self, "notes", None):
            self.notes = self.notes.strip()
        self._migrate_legacy_vector_database_if_needed()
        self._normalize_linked_vector_databases()

        if not getattr(self, "linked_vector_databases", None):
            raise frappe.ValidationError("Add at least one linked vector database.")

    def _migrate_legacy_vector_database_if_needed(self) -> None:
        """Copy the legacy single VDB value into the child table for the current document only.

        This runs only when a record is opened and saved. It does not migrate all existing
        Jive Rag User records automatically.
        """
        if getattr(self, "linked_vector_databases", None):
            return

        legacy_vector_database = self._get_legacy_vector_database()
        if legacy_vector_database:
            self.append(
                "linked_vector_databases",
                {"jive_vector_database": legacy_vector_database},
            )

    def _get_legacy_vector_database(self) -> str:
        """Read the old single-VDB value when it still exists on the current record."""
        current_value = str(getattr(self, "jive_vector_database", "") or "").strip()
        if current_value:
            return current_value

        if not self.name or not self._legacy_vector_database_field_exists():
            return ""

        result = frappe.db.sql(
            """
            SELECT jive_vector_database
            FROM `tabJive Rag User`
            WHERE name = %s
            """,
            (self.name,),
            as_dict=True,
        )
        if not result:
            return ""
        return str(result[0].get("jive_vector_database") or "").strip()

    @staticmethod
    def _legacy_vector_database_field_exists() -> bool:
        result = frappe.db.sql(
            "SHOW COLUMNS FROM `tabJive Rag User` LIKE %s",
            ("jive_vector_database",),
        )
        return bool(result)

    def _normalize_linked_vector_databases(self) -> None:
        """Trim and deduplicate linked vector database rows before validation."""
        cleaned_rows = []
        seen = set()

        for row in list(getattr(self, "linked_vector_databases", []) or []):
            vector_database = str(getattr(row, "jive_vector_database", "") or "").strip()
            if not vector_database or vector_database in seen:
                continue

            row.jive_vector_database = vector_database
            cleaned_rows.append(row)
            seen.add(vector_database)

        self.set("linked_vector_databases", cleaned_rows)


# Keep the legacy alias so imports from the old generated class name still work.
JIVERAGUSER = JiveRagUser
