from ampower_jive.mcp.utils.core_utils import ensure_frappe_init
from ampower_jive.mcp.config.clients import openai_client
import frappe
import json


def run_helpdesk(user_prompt):
    try:
        ensure_frappe_init()
    except Exception as e:
        return json.dumps({"error": f"Frappe initialization failed: {str(e)}"})

    HELPDESK_PROMPT = (
        frappe.db.get_value("Prompt", {"name": "HELPDESK"}, "prompt")
        or "You are a helpful expert, give only answers relevant to asked questions."
    )

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini-search-preview",
            messages=[
                {"role": "system", "content": HELPDESK_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        return json.dumps({"reply": response.choices[0].message.content})

    except Exception as e:
        return json.dumps({"error": f"Failed to get the response : {str(e)} "})
