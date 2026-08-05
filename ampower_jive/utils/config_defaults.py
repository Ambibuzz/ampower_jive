"""Shared default values for the local Jive Config singleton."""

from ampower_jive.utils.context_aware import get_context_aware_default_prompt


DEFAULT_JIVE_CONFIG = {
    "active_jive": 0,
    "enable_voice_input": 1,
    "enable_file_upload": 1,
    "enable_gif_generation": 1,
    "enable_query_agent": 1,
    "enable_helpdesk_agent": 1,
    "enable_hd_tickets": 1,
    "enable_agent_mode": 1,
    "enable_insights_agent": 1,
    "enable_rag_agent": 1,
    "enable_rag_helpdesk": 0,
    "max_history_messages": 10,
    "conversation_retention_days": 30,
    "chat_model": "gpt-4o-mini",
    "chat_temperature": 0.3,
    "chat_max_tokens": 4096,
    "help_desk_model": "gpt-4o-mini-search-preview",
    "helpdesk_temperature": 0.3,
    "helpdesk_max_tokens": 4096,
    "hd_tickets_model": "gpt-4o-mini",
    "agent_model": "gpt-4o-mini",
    "agent_temperature": 0.2,
    "agent_require_approval": 1,
    "welcome_title": "What would you like to know?",
    "welcome_message": "Ask questions about your ERPNext data, get help with features, or let me help you manage documents.",
    "primary_color": "#6366f1",
    "show_suggestions": 1,
    "context_aware_system_prompt": get_context_aware_default_prompt(),
    "max_context_tokens": 12000,
    "local_daily_token_usage": 0,
    "local_monthly_token_usage": 0,
    "local_monthly_token_limit": 500000,
}


def apply_default_jive_config(doc):
    """Apply the shared local defaults to a Jive Config document."""
    for fieldname, value in DEFAULT_JIVE_CONFIG.items():
        setattr(doc, fieldname, value)
    return doc
