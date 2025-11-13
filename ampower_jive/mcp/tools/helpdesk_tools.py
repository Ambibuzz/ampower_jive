# Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
# For license information, please see license.txt

import json
import frappe
from ..config.open_ai_client import OpenAIConfig
from ampower_jive.mcp.utils.core_utils import ensure_frappe_init, teardown_session, logger

try:

    def run_helpdesk(user_prompt: str) -> str:
        """
        Run Helpdesk using OpenAI chat model with Frappe prompt context.

        Args:
            user_prompt (str): The query from user.

        Returns:
            str: JSON string containing either 'reply' or 'error'.
        """
        logger.info("Helpdesk Tool Initiated...")

        try:
            ensure_frappe_init()
        except Exception as e:
            teardown_session()
            return {"error": f"Frappe initialization failed: {e}"}

        # Get prompt from DB, else fallback
        helpdesk_prompt = (
            frappe.db.get_value("Prompt", {"name": "HELPDESK"}, "prompt")
            or "You are a helpful expert in frappe ERPNext, HRMS, India compliance and CRM. Give only answers relevant to asked questions."
        )

        try:
            openai_client = OpenAIConfig().client
            model = OpenAIConfig()._get_helpdesk_model()
            logger.info(f"User question: {user_prompt}")
            response = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": helpdesk_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            reply = response.choices[0].message.content.strip()
            teardown_session()
            logger.info(f"Helpdesk Tool Completed, Response : {reply}")
            return {"reply": reply}

        except Exception as e:
            logger.error(f"Error while running helpdesk tool {e}")
            teardown_session()
            return {"error": f"Failed to get response: {e}"}

except Exception as e:
    logger.error(f"Error while running helpdesk tool: {e}")
    teardown_session()
