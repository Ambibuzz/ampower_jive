from ampower_jive.mcp.utils.core_utils import ensure_frappe_init
from ampower_jive.mcp.config.setup import logger
import frappe
import json


def list_doctypes():
    """List doctypes from Jive Config along with their fields"""
    try:
        logger.info("Listing doctypes from Jive Config")
        ensure_frappe_init()

        config = frappe.get_single("Jive Config")
        included_doctypes = [d.doctype_name for d in config.included_doctypes]

        if not included_doctypes:
            return json.dumps(
                {"error": "No included doctypes configured in Jive Config"}
            )

        doctypes = frappe.get_all(
            "DocType",
            fields=["name"],
            filters={
                "module": "Deep Matrix",
                "name": ["in", included_doctypes],
            },
            order_by="name",
        )

        result = []
        for doctype in doctypes:
            doctype_name = doctype["name"]

            fields = frappe.get_all(
                "DocField",
                fields=["fieldname", "label", "fieldtype", "options", "reqd"],
                filters={"parent": doctype_name},
                order_by="idx",
            )

            result.append({"doctype": doctype_name, "fields": fields})

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"List doctypes error: {str(e)}")
        return json.dumps({"error": str(e)})
