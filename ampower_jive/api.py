"""
AmPower Jive API Endpoints.

This module is now a thin compatibility facade that re-exports the
feature-specific handlers from `ampower_jive.api_features`.
"""

from ampower_jive.api_features.access import (
    BUILTIN_CHAT_MODES,
    check_helpdesk_installed,
    check_jive_access,
    get_allowed_doctypes_list,
    get_jive_config,
    get_mode_config,
    is_mode_available,
    has_jive_access,
    is_system_manager,
    normalize_chat_mode,
)
from ampower_jive.api_features.agent_actions import approve_plan, reject_plan
from ampower_jive.api_features.chat import (
    chat,
    enqueue_rag_index_build,
    enqueue_vector_database_index_build,
    handle_agent_mode,
    handle_core_managed_agent_mode,
    process_data_query,
    process_rag_query,
)
from ampower_jive.api_features.common import (
    _append_followup_suggestions,
    _append_helpdesk_recommendations,
    _build_helpdesk_fallback_suggestions,
    _build_insights_api_key_missing_response,
    _build_insights_not_installed_response,
    _ensure_local_monthly_quota,
    _finalize_insights_response,
    _log_context_debug,
    _log_mode_error,
    _log_mode_turn,
    _remove_duplicate_sections,
    _save_local_feedback,
    _sync_feedback_to_core,
    _summarize_context_payload,
    _strip_followup_blocks_from_history,
    clean_insights_response,
)
from ampower_jive.api_features.conversations import (
    archive_conversation,
    clear_conversation,
    get_conversation_history,
    get_user_conversations,
    update_conversation_title,
)
from ampower_jive.api_features.helpdesk import (
    clear_helpdesk_context,
    get_helpdesk_context,
    mark_issue_resolved,
    process_helpdesk_query,
    remove_helpdesk_context_file,
    submit_chat_message_feedback,
    upload_helpdesk_context,
)
from ampower_jive.api_features.hd_tickets import process_hd_tickets_query
from ampower_jive.api_features.insights import (
    check_insights_installed,
    delete_insights_workbook,
    handle_insights_mode,
)
from ampower_jive.utils.chat_support import (
    _assistant_log_payload,
    _build_history_message,
    _expand_chat_log_row,
    _get_last_token_usage_detail,
    _is_error_response,
    _normalize_feedback_value,
    add_message_to_log,
    create_new_conversation,
    get_messages_from_log,
    safe_commit,
)
from ampower_jive.utils.followup_suggestions import (
    FollowupSuggestionService,
    append_followup_block,
    strip_followup_block,
)
from ampower_jive.utils.context_aware import process_context_aware_query
from ampower_jive.utils.prompt_provider import get_prompt_provider
