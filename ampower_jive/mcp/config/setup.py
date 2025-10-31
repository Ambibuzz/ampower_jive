import time
import os, frappe, logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def start_mcp_server():
    site_name = os.environ.get("FRAPPE_SITE", "your-site-name")
    from ampower_jive.mcp.config.clients import mcp
    from ampower_jive.mcp.registry import tools_registry

    while True:
        try:
            frappe.init(site=site_name)
            frappe.connect()
            logger.info(f"Frappe initialized for site: {site_name}")

            # Add connection health check
            frappe.db.sql("SELECT 1")
            logger.info("Database connection verified")

            break
        except Exception as e:
            logger.error(f"Frappe init failed: {e}. Retrying in 5 seconds...")
            time.sleep(5)

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    start_mcp_server()
