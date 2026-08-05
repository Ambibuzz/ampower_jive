# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document

class JiveConfig(Document):
    def on_update(self):
        from ampower_jive.utils.config_provider import get_config_provider
        from ampower_jive.agent.rag_resolution import invalidate_cache as invalidate_rag_resolution_cache
        from ampower_jive.utils.prompt_provider import get_prompt_provider

        try:
            get_config_provider().invalidate_cache()
        except Exception:
            pass

        try:
            invalidate_rag_resolution_cache()
        except Exception:
            pass

        get_prompt_provider().invalidate()
