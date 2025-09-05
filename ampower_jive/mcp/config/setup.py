import os, frappe, logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def start_mcp_server():
    site_name = os.environ.get("FRAPPE_SITE", "your-site-name")
    from ampower_jive.mcp.config.clients import mcp
    # Initialize resources and tools registries, DO NOT REMOVE
    from ampower_jive.mcp.registry import resources_registry
    from ampower_jive.mcp.registry import tools_registry
    try:
        frappe.init(site=site_name)
        frappe.connect()
        logger.info(f"Frappe initialized for site: {site_name}")
    except Exception as e:
        logger.error(f"Frappe init failed: {e}")

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    start_mcp_server()
