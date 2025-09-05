from ampower_jive.mcp.utils.core_utils import ensure_frappe_init, datetime_handler
from ampower_jive.mcp.config.setup import logger
import frappe
import base64
import json


def get_documents(encoded_args=None):
    """Generic getter function for Frappe doctypes"""
    try:
        ensure_frappe_init()

        parsed_arguments = {}
        if encoded_args:
            try:
                decoded_bytes = base64.b64decode(encoded_args)
                decoded_string = decoded_bytes.decode("utf-8")
                parsed_arguments = json.loads(decoded_string)
            except (json.JSONDecodeError, ValueError, Exception):
                parsed_arguments = {}

        doctype = parsed_arguments.get("doctype", "")
        filters = parsed_arguments.get("filters", {})
        fields = parsed_arguments.get("fields", ["name"])
        limit = parsed_arguments.get("limit", 200)
        order_by = parsed_arguments.get("order_by", "creation desc")

        records = frappe.get_list(
            doctype,
            filters=filters,
            fields=fields,
            limit=limit,
            order_by=order_by,
        )

        return json.dumps(records, default=datetime_handler, indent=2)
    except Exception as e:
        logger.error(f"Get {doctype} error: {str(e)}")
        return json.dumps({"error": str(e)})
