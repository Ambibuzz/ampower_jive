from ampower_jive.mcp.resources.frappe_resources import get_documents
from ampower_jive.mcp.config.clients import openai_client
from ampower_jive.mcp.agents.qa import FrappeAgent
from ampower_jive.mcp.config.setup import logger
import json


def query_frappe_doctypes(question):
    """
    Enhanced query function using agent pattern.
    The function receives only the question and lets the LLM identify required parameters.
    """
    try:
        agent = FrappeAgent(
            client=openai_client,
            get_documents_func=get_documents,
        )

        return agent.process_query(question)

    except Exception as e:
        logger.error(f"Query on doctypes error: {str(e)}")
        return json.dumps({"error": str(e)})
