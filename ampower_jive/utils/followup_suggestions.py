"""
Shared follow-up suggestion helpers.

The main assistant response stays focused on answering the user. When the
LLM produces follow-up questions, they are stored in a hidden marker block so
the frontend can render them as chips without changing the existing message
shape.
"""

import json
import re
from typing import Dict, List, Optional

import frappe
from langchain_core.messages import HumanMessage, SystemMessage

from ampower_jive.utils.config_provider import get_config_provider


FOLLOWUP_BLOCK_START = "[[FOLLOWUP_SUGGESTIONS]]"
FOLLOWUP_BLOCK_END = "[[/FOLLOWUP_SUGGESTIONS]]"
FOLLOWUP_PROMPT_SUFFIX = """

FOLLOW-UP FORMAT:
This is a REQUIRED part of your response when the answer is not a refusal or error.
At the very end of your response, append this exact hidden block with exactly 3 strong follow-up questions:
[[FOLLOWUP_SUGGESTIONS]]{"suggestions":["question 1?","question 2?","question 3?"]}[[/FOLLOWUP_SUGGESTIONS]]

Rules:
- Put only valid JSON inside the hidden block.
- Always return exactly 3 questions when possible.
- Keep each question concise, specific, and relevant to the latest user question and assistant answer.
- Do not add any extra text inside the hidden block.
- Do not omit the hidden block unless you genuinely cannot produce 3 relevant questions.
"""


def strip_followup_block(text: str) -> str:
    """Remove an embedded follow-up block from assistant content."""
    if not text:
        return ""

    pattern = re.compile(
        rf"\n?\s*{re.escape(FOLLOWUP_BLOCK_START)}[\s\S]*?{re.escape(FOLLOWUP_BLOCK_END)}\s*",
        re.MULTILINE,
    )
    return pattern.sub("", text).strip()


def append_followup_block(text: str, suggestions: List[str]) -> str:
    """Append a hidden follow-up block to stored assistant content."""
    base_text = (text or "").rstrip()
    cleaned = [s for s in (suggestions or []) if isinstance(s, str) and s.strip()]
    if not cleaned:
        return base_text

    payload = {"suggestions": cleaned[:3]}
    block = f"\n\n{FOLLOWUP_BLOCK_START}{json.dumps(payload, ensure_ascii=False)}{FOLLOWUP_BLOCK_END}"
    return f"{base_text}{block}"


def append_followup_prompt(prompt: str) -> str:
    """Append the shared follow-up instruction block to a system prompt."""
    prompt = (prompt or "").rstrip()
    if FOLLOWUP_BLOCK_START in prompt:
        return prompt
    return f"{prompt}{FOLLOWUP_PROMPT_SUFFIX}"


class FollowupSuggestionService:
    """Generate exactly three follow-up questions from a completed answer."""

    MODE_TO_PURPOSE = {
        "query": "query",
        "context": "query",
        "helpdesk": "helpdesk",
        "hd_tickets": "hd_tickets",
        "insights": "insights",
        "rag": "rag",
    }

    MODE_TO_AGENT_TYPE = {
        "query": "data_query",
        "context": "data_query",
        "helpdesk": "helpdesk",
        "hd_tickets": "hd_tickets",
        "insights": "insights",
        "rag": "rag",
    }

    def __init__(self, mode: str):
        self.mode = (mode or "query").lower().strip()
        self.provider = get_config_provider()

    def generate(
        self,
        user_message: str,
        assistant_response: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> List[str]:
        """
        Ask the LLM for exactly three follow-up questions.

        Returns an empty list when the model does not return a valid structured
        response. No deterministic fallback is used.
        """
        visible_response = strip_followup_block(assistant_response or "")
        if self._should_skip(visible_response):
            return []

        visible_response = visible_response[:2500]
        user_message = (user_message or "")[:1000]

        llm = self._build_llm()
        if not llm:
            return []

        conversation_focus = self._build_conversation_focus(user_message or "", visible_response, history or [])
        prompt = self._build_prompt(conversation_focus)
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content="Return only the JSON payload now."),
        ]

        try:
            response = llm.invoke(messages)
            raw_output = response.content if response and getattr(response, "content", None) else ""
        except Exception:
            return []

        suggestions = self._parse_suggestions(raw_output)
        return suggestions if len(suggestions) == 3 else []

    def _build_llm(self):
        from ampower_jive.agent.llm_pool import get_cached_llm

        agent_type = self.MODE_TO_AGENT_TYPE.get(self.mode, "data_query")
        purpose = self.MODE_TO_PURPOSE.get(self.mode, "query")
        settings = self.provider.get_model_settings(agent_type) or {}

        model = settings.get("model")
        temperature = settings.get("temperature", 0.2)

        try:
            return get_cached_llm(
                purpose=purpose,
                model=model,
                temperature=temperature if temperature is not None else 0.2,
                timeout=20,
            )
        except Exception:
            frappe.log_error(
                message=frappe.get_traceback(),
                title="Followup Suggestion LLM Error",
            )
            return None

    def _build_prompt(self, conversation_focus: str) -> str:
        return f"""You generate follow-up questions for Jive chat.

Use only the question and answer pairs below.
Do not use any other context.
The suggestions must be actual queries the user can ask Jive next.
Phrase them as direct questions to Jive, not as commentary or analysis.

Return ONLY valid JSON with this exact shape:
{{"suggestions":["question 1","question 2","question 3"]}}

Rules:
- Return exactly 3 questions when you can do so confidently.
- Each item must be a concise question the user could ask next.
- Each item must be something the user can ask Jive directly.
- Questions must stay on the same topic as the assistant answer.
- Match the user's language and tone.
- Do not add numbering, bullets, markdown, code fences, or extra keys.
- Do not explain your reasoning.
- If you cannot produce 3 strong follow-ups, return {{"suggestions":[]}}.
- Avoid generic prompts like "Tell me more".
- Prefer concrete next-step questions that deepen the current answer.

Conversation focus:
{conversation_focus}
"""

    @staticmethod
    def _build_conversation_focus(
        user_message: str,
        assistant_response: str,
        history: List[Dict[str, str]],
    ) -> str:
        blocks = []
        previous_turn = FollowupSuggestionService._extract_previous_turn(history)
        if previous_turn:
            previous_question, previous_answer = previous_turn
            blocks.append(
                "Previous question:\n"
                f"{previous_question}\n\n"
                "Previous answer:\n"
                f"{previous_answer}"
            )

        blocks.append(
            "Current question:\n"
            f"{(user_message or '').strip()}\n\n"
            "Current answer:\n"
            f"{(assistant_response or '').strip()}"
        )
        return "\n\n".join(blocks)

    @staticmethod
    def _extract_previous_turn(history: List[Dict[str, str]]) -> Optional[tuple[str, str]]:
        if not history:
            return None

        filtered = []
        for msg in history:
            if not isinstance(msg, dict):
                continue
            role = (msg.get("role") or "").lower().strip()
            if role not in {"user", "assistant"}:
                continue
            content = strip_followup_block(msg.get("content") or "").strip()
            if not content:
                continue
            filtered.append({"role": role, "content": content})

        if len(filtered) < 2:
            return None

        for idx in range(len(filtered) - 1, 0, -1):
            current = filtered[idx]
            previous = filtered[idx - 1]
            if current["role"] == "assistant" and previous["role"] == "user":
                return previous["content"], current["content"]
            if current["role"] == "user" and previous["role"] == "assistant":
                return current["content"], previous["content"]

        return None

    @staticmethod
    def _should_skip(response_text: str) -> bool:
        if not response_text:
            return True

        text = response_text.strip().lower()
        return (
            text.startswith("**openai api key is not configured**")
            or text.startswith("openai api key is not configured")
            or text.startswith("**frappe insights is not installed")
            or text.startswith("i could not detect a supported open view")
            or text.startswith("access denied")
            or text.startswith("❌ error")
        )

    @staticmethod
    def _parse_suggestions(raw_output: str) -> List[str]:
        if not raw_output:
            return []

        text = raw_output.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

        try:
            payload = json.loads(text)
        except Exception:
            return []

        suggestions = payload.get("suggestions") if isinstance(payload, dict) else []
        if not isinstance(suggestions, list):
            return []

        cleaned: List[str] = []
        seen = set()
        for item in suggestions:
            if not isinstance(item, str):
                continue
            question = re.sub(r"\s+", " ", item).strip(" -•\t\r\n")
            if not question:
                continue
            if not question.endswith("?"):
                question += "?"

            normalized = question.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(question)

        return cleaned[:3]
