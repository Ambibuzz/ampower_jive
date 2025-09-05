from ampower_jive.mcp.prompts.frappe_prompts import DOCUMENTS_AGENT_PROMPT
from ampower_jive.mcp.tools.list_frappe_doctypes import list_doctypes
from ampower_jive.mcp.config.setup import logger
from datetime import datetime
import frappe
import base64
import json


additional_context = {
    "date": datetime.today().strftime("%Y-%m-%d"),
    "doctypes": list_doctypes(),
}


class FrappeAgent:
    def __init__(self, client, get_documents_func):
        self.client = client
        self.get_documents = get_documents_func
        self.tools = {
            "get_documents": self._get_documents_wrapper,
        }
        self.query_doc_name = None

    def _get_documents_wrapper(
        self, doctype, filters=None, fields=None, limit=100, order_by=None
    ):
        """Wrapper for get_documents function"""
        try:
            args = {
                "doctype": doctype,
                "filters": filters or {},
                "fields": fields or ["*"],
                "limit": limit,
                "order_by": order_by,
            }
            encoded_args = base64.b64encode(json.dumps(args).encode()).decode()
            return self.get_documents(encoded_args)
        except Exception as e:
            logger.error(f"Get documents error: {str(e)}")
            return json.dumps({"error": str(e)})

    def process_query(self, question):
        """Process user query using the agent state machine"""
        try:
            DEVELOPER_PROMPT = frappe.get_doc(
                "Prompt", "USER_DATABASE_DEFINITION"
            ).prompt
            if not DEVELOPER_PROMPT:
                logger.error("Developer prompt not found")
                return {"response": {"error": "Developer prompt not found"}}
            messages = [
                {
                    "role": "system",
                    "content": DOCUMENTS_AGENT_PROMPT
                    + json.dumps(additional_context, indent=2),
                },
                {
                    "role": "developer",
                    "content": DEVELOPER_PROMPT,
                },
            ]

            query = {"state": "START", "prompt": question}

            steps = []
            steps.append(
                {
                    "step": "INIT",
                    "message": f"Query: {json.dumps(query)}",
                    "timestamp": datetime.now().isoformat(),
                }
            )

            messages.append({"role": "user", "content": json.dumps(query)})

            while True:
                chat_response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.36,
                )

                result = chat_response.choices[0].message.content
                messages.append({"role": "assistant", "content": result})

                steps.append(
                    {
                        "step": "AI_RESPONSE",
                        "message": f"AI Response: {result}",
                        "timestamp": datetime.now().isoformat(),
                    }
                )

                try:
                    call = json.loads(result)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON response: {result}")
                    return {
                        "response": {"error": "Invalid response format from AI"},
                        "steps": steps,
                    }

                if call.get("state") == "OUTPUT":
                    steps.append(
                        {
                            "step": "COMPLETION",
                            "message": "Process completed successfully",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                    response = call.get("response", "No response provided")
                    return response

                elif call.get("state") == "ACTION":
                    function_name = call.get("function")

                    if function_name == "get_documents":
                        doctype = call.get("doctype", "")
                        filters = call.get("filters", {})
                        fields = call.get("fields", ["*"])
                        limit = call.get("limit", 1)
                        order_by = call.get("order_by", "creation desc")

                        function_output = self._get_documents_wrapper(
                            doctype=doctype,
                            filters=filters,
                            fields=fields,
                            limit=limit,
                            order_by=order_by,
                        )

                    else:
                        function_output = json.dumps(
                            {"error": f"Unknown function: {function_name}"}
                        )

                    observation = {"state": "OBSERVATION", "value": function_output}
                    messages.append(
                        {"role": "assistant", "content": json.dumps(observation)}
                    )
                    steps.append(
                        {
                            "step": "OBSERVATION",
                            "message": f"Observation: {json.dumps(observation)}",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

                elif call.get("state") == "PLAN":
                    continue

                else:
                    logger.error(f"Unknown state: {call.get('state')}")
                    steps.append(
                        {
                            "step": "ERROR",
                            "message": f"Error: Unknown state {call.get('state')}",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                    return {
                        "response": {"error": f"Unknown state: {call.get('state')}"},
                        "steps": steps,
                    }

        except Exception as e:
            logger.error(f"Process query error: {str(e)}")
            steps.append(
                {
                    "step": "ERROR",
                    "message": f"Process error: {str(e)}",
                    "timestamp": datetime.now().isoformat(),
                }
            )
            return {"response": {"error": str(e)}, "steps": steps}
