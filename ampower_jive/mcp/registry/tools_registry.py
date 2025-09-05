from ampower_jive.mcp.tools import helpdesk_tools, query_frappe_doctypes
from ampower_jive.mcp.config.clients import mcp


mcp.tool(
    description="""
    Run a user query by pulling Frappe doctypes data and analyze it.
    Args: question (str): The user query to process.
    Returns: dict: The response from the AI after processing the query.
"""
)(query_frappe_doctypes.query_frappe_doctypes)
mcp.tool(
    description="""
    Run Helpdesk with web scraping over forums, help manuals and documentations.
    Args: user_prompt (str): The user query to process.
    Returns: dict: The response from the AI after processing the query.
"""
)(helpdesk_tools.run_helpdesk)
