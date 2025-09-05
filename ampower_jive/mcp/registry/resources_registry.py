from ampower_jive.mcp.resources import frappe_resources
from ampower_jive.mcp.config.clients import mcp


mcp.resource("frappe://documents/{encoded_args}")(frappe_resources.get_documents)
