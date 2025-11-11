import time
import os, frappe, logging
from ..utils.core_utils import _teardown_session
from ampower_jive.mcp.config.middleware import FrappeSIDAuthMiddleware


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:

    def start_mcp_server():
        site_name = os.environ.get("FRAPPE_SITE", "your-site-name")
        from ampower_jive.mcp.config.clients import mcp
        from ampower_jive.mcp.registry import tools_registry

        # Registering middleware globally so it runs for all tool calls
        mcp.add_middleware(FrappeSIDAuthMiddleware())
        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST"),
            port=int(os.environ.get("MCP_PORT")),
            stateless_http=True,
            log_level="info"
        )

except Exception as e:
    _teardown_session()
    logger.error(f"Failed to start MCP server: {e}")

if __name__ == "__main__":
    start_mcp_server()
