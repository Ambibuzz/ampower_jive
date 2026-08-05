"""
Jive Config Provider

Unified configuration provider that fetches settings either:
1. Locally from Jive Config singleton (default mode)
2. Remotely from Jive Core API (when use_jive_core is enabled)

Implements caching with TTL to minimize API calls.
"""

import json
import frappe
import time
from typing import Dict, Any, Optional
from threading import Lock

from ampower_jive.utils.app_dependencies import is_helpdesk_installed
from ampower_jive.utils.context_summary import summarize_context_payload


BUILTIN_AGENT_MODES = [
    {
        "agent_key": "query",
        "label": "Data Query",
        "hint": "Search your ERPNext data",
        "icon": "⬡",
        "color": "#6366f1",
        "handler_type": "query",
        "status_message": "Searching your data...",
        "supports_context": True,
        "supports_upload": False,
        "supports_gif": False,
        "visible_in_chat": True,
        "enabled": True,
        "sort_order": 10,
    },
    {
        "agent_key": "helpdesk",
        "label": "Helpdesk",
        "hint": "Get help and guidance",
        "icon": "?",
        "color": "#f59e0b",
        "handler_type": "helpdesk",
        "status_message": "Generating response...",
        "supports_context": False,
        "supports_upload": True,
        "supports_gif": True,
        "visible_in_chat": True,
        "enabled": True,
        "sort_order": 20,
    },
    {
        "agent_key": "hd_tickets",
        "label": "HD Tickets",
        "hint": "Check ticket lists, status, updates, and activity",
        "icon": "#",
        "color": "#f97316",
        "handler_type": "hd_tickets",
        "status_message": "Checking your tickets...",
        "supports_context": False,
        "supports_upload": False,
        "supports_gif": False,
        "visible_in_chat": True,
        "enabled": True,
        "sort_order": 25,
    },
    {
        "agent_key": "agent",
        "label": "Agent",
        "hint": "Create and modify documents",
        "icon": "◈",
        "color": "#10b981",
        "handler_type": "agent",
        "status_message": "Analyzing your request...",
        "supports_context": True,
        "supports_upload": False,
        "supports_gif": False,
        "visible_in_chat": True,
        "enabled": True,
        "sort_order": 30,
    },
    {
        "agent_key": "insights",
        "label": "Insights",
        "hint": "Create charts and dashboards",
        "icon": "◉",
        "color": "#8b5cf6",
        "handler_type": "insights",
        "status_message": "Creating visualization...",
        "supports_context": True,
        "supports_upload": False,
        "supports_gif": False,
        "visible_in_chat": True,
        "enabled": True,
        "sort_order": 40,
    },
    {
        "agent_key": "rag",
        "label": "RAG",
        "hint": "Ask questions about attached documents",
        "icon": "◈",
        "color": "#0ea5e9",
        "handler_type": "rag",
        "status_message": "Searching your knowledge base...",
        "supports_context": False,
        "supports_upload": False,
        "supports_gif": False,
        "visible_in_chat": True,
        "enabled": True,
        "sort_order": 50,
    },
]

BUILTIN_AGENT_ENABLE_FIELDS = {
    "query": "enable_query_agent",
    "helpdesk": "enable_helpdesk_agent",
    "hd_tickets": "enable_hd_tickets",
    "agent": "enable_agent_mode",
    "insights": "enable_insights_agent",
    "rag": "enable_rag_agent",
}


def _summarize_context_payload(context_payload):
    return summarize_context_payload(context_payload)


class JiveConfigProvider:
    """
    Unified config provider for Jive.
    
    Automatically determines whether to fetch config locally or
    from a remote Jive Core instance based on the `use_jive_core`
    setting in Jive Config.
    """
    
    _instance = None
    _lock = Lock()
    _shared_cache_version_key = "ampower_jive:config_provider:version"
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Cache configuration
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._config_cache = None
        self._config_cache_time = 0
        self._config_cache_version = None
        
        # TTL settings
        self._config_ttl = 30  # Check config every 30 seconds
        self._data_ttl = 60  # Cache remote data for 60 seconds
        
        # Core client (lazy loaded)
        self._core_client = None
        self._core_client_config = None
        
        self._initialized = True
    
    def _get_local_config(self):
        """Get local Jive Config with caching."""
        now = time.time()
        shared_version = frappe.cache().get_value(self._shared_cache_version_key)

        if self._config_cache_version != shared_version:
            self._config_cache = None
            self._config_cache_time = 0
            self._config_cache_version = shared_version

        if self._config_cache and (now - self._config_cache_time) < self._config_ttl:
            return self._config_cache
        
        try:
            config = frappe.get_single("Jive Config")
            self._config_cache = config
            self._config_cache_time = now
            self._config_cache_version = shared_version
            return config
        except Exception as e:
            frappe.log_error(f"Failed to get Jive Config: {e}")
            return None
    
    def _is_core_enabled(self) -> bool:
        """Check if Jive Core integration is enabled."""
        config = self._get_local_config()
        if not config:
            return False
        return bool(config.get("use_jive_core"))
    
    def _get_core_client(self):
        """Get or create Jive Core client."""
        config = self._get_local_config()
        if not config:
            return None
        
        url = config.get("jive_core_url")
        api_key = (
            config.get_password("jive_core_api_key", raise_exception=False)
            if hasattr(config, "get_password")
            else None
        )
        
        if not url or not api_key:
            return None
        
        # Check if we need to recreate client (config changed)
        config_key = f"{url}:{api_key[:8] if api_key else ''}"
        if self._core_client_config != config_key:
            from .jive_core_client import JiveCoreClient
            self._core_client = JiveCoreClient(url, api_key)
            self._core_client_config = config_key
        
        return self._core_client
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        if key not in self._cache:
            return None
        
        timestamp = self._cache_timestamps.get(key, 0)
        if (time.time() - timestamp) > self._data_ttl:
            return None
        
        return self._cache[key]
    
    def _set_cached(self, key: str, value: Any):
        """Set value in cache."""
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()
    
    def get_api_key(self) -> Optional[str]:
        """
        Get the OpenAI API key.
        
        Returns:
            API key from Jive Core when core mode is enabled, otherwise local config
        """
        if self._is_core_enabled():
            # Check cache first
            cached = self._get_cached("api_key")
            if cached:
                return cached
            
            client = self._get_core_client()
            if client:
                try:
                    api_key = client.get_api_key()
                    if api_key:
                        self._set_cached("api_key", api_key)
                        return api_key
                except Exception as e:
                    frappe.log_error(f"Failed to get API key from Jive Core: {e}")

            return None

        # Fallback to local config only when Jive Core is disabled.
        config = self._get_local_config()
        if config:
            return (
                config.get_password("open_ai_key", raise_exception=False)
                if hasattr(config, "get_password")
                else None
            )
        return None
    
    def get_model_settings(self, agent_type: str = None) -> Dict[str, Any]:
        """
        Get model settings for an agent type.
        
        Args:
            agent_type: Agent type (data_query, helpdesk, agent_mode, insights)
            
        Returns:
            Dict with model, temperature, max_tokens, etc.
        """
        cache_key = f"model_settings:{agent_type or 'all'}"
        
        if self._is_core_enabled():
            cached = self._get_cached(cache_key)
            if cached:
                return cached
            
            client = self._get_core_client()
            if client:
                try:
                    settings = client.get_model_settings(agent_type)
                    if settings:
                        self._set_cached(cache_key, settings)
                        return settings
                except Exception as e:
                    frappe.log_error(f"Failed to get model settings from Jive Core: {e}")
        
        # Fallback to local config
        return self._get_local_model_settings(agent_type)
    
    def _get_local_model_settings(self, agent_type: str = None) -> Dict[str, Any]:
        """Get model settings from local config."""
        config = self._get_local_config()
        if not config:
            return {}
        
        # Map agent type to config fields
        settings_map = {
            "data_query": {
                "model": config.get("chat_model") or "gpt-4o-mini",
                "temperature": config.get("chat_temperature") or 0.3,
                "max_tokens": config.get("chat_max_tokens") or 4096
            },
            "helpdesk": {
                "model": config.get("help_desk_model") or "gpt-4o-mini",
                "temperature": config.get("helpdesk_temperature") or 0.3,
                "max_tokens": config.get("helpdesk_max_tokens") or 4096
            },
            "hd_tickets": {
                "model": config.get("hd_tickets_model") or "gpt-4o-mini",
                "temperature": config.get("helpdesk_temperature") or 0.3,
                "max_tokens": config.get("helpdesk_max_tokens") or 4096,
            },
            "agent_mode": {
                "model": config.get("agent_model") or "gpt-4o-mini",
                "temperature": config.get("agent_temperature") or 0.2,
                "require_approval": config.get("agent_require_approval") or 1
            },
            "insights": {
                "model": config.get("insights_model") or "gpt-4o-mini",
                "temperature": config.get("insights_temperature") or 0.3
            }
        }
        
        if agent_type and agent_type in settings_map:
            return settings_map[agent_type]
        
        return settings_map

    def _build_core_token_usage(self, config) -> Dict[str, Dict[str, int]]:
        """Build the legacy core token usage payload from Jive Config."""
        return {
            "daily": {
                "current": config.get("daily_tokens_used") or 0,
                "limit": config.get("daily_token_limit") or 0,
            },
            "monthly": {
                "current": config.get("monthly_tokens_used") or 0,
                "limit": config.get("monthly_token_limit") or 0,
            },
        }

    def get_local_token_usage(self, persist: bool = True) -> Dict[str, Any]:
        """Read the current local token usage snapshot from the local log service."""
        try:
            from ampower_jive.utils.token_log_service import TokenLogService

            service = TokenLogService(site_name=frappe.local.site)
            if persist:
                return service.refresh_usage_snapshot()
            return service.get_usage_snapshot()
        except Exception as exc:
            frappe.log_error(f"Failed to get local token usage snapshot: {exc}")
            return {
                "daily": {"current": 0, "limit": 0, "unlimited": True, "allowed": True, "projected": 0},
                "monthly": {"current": 0, "limit": 0, "unlimited": True, "allowed": True, "projected": 0},
            }

    def _sync_core_usage_cache(self, quota: Dict[str, Any]) -> None:
        """Persist the latest core quota snapshot back to Jive Config."""
        try:
            config = frappe.get_doc("Jive Config", "Jive Config")
            daily = quota.get("daily", {}) if isinstance(quota, dict) else {}
            monthly = quota.get("monthly", {}) if isinstance(quota, dict) else {}

            config.daily_tokens_used = daily.get("current", 0)
            config.daily_token_limit = daily.get("limit", 0)
            config.monthly_tokens_used = monthly.get("current", 0)
            config.monthly_token_limit = monthly.get("limit", 0)
            config.token_usage_last_updated = frappe.utils.now()
            config.save(ignore_permissions=True)

            if not hasattr(frappe.local, "_realtime_log"):
                frappe.local._realtime_log = []
            frappe.db.commit()
        except Exception as exc:
            frappe.log_error(f"Failed to update core usage cache: {exc}")

    def _parse_json_field(self, value, default):
        if not value:
            return default

        if isinstance(value, (list, dict)):
            return value

        try:
            parsed = json.loads(value)
            return parsed if parsed is not None else default
        except Exception:
            return default

    def _is_agent_enabled(self, config, agent_key: str) -> bool:
        normalized_key = (agent_key or "").lower().strip()
        fieldname = BUILTIN_AGENT_ENABLE_FIELDS.get(normalized_key)
        if not fieldname:
            return True
        enabled = bool(frappe.utils.cint(config.get(fieldname, 1)))
        if normalized_key == "hd_tickets":
            enabled = (
                enabled
                and bool(frappe.utils.cint(config.get("enable_helpdesk_agent", 1)))
                and is_helpdesk_installed()
            )
        return enabled

    def _get_builtin_agent_runtime_settings(self, agent_key: str) -> Dict[str, Any]:
        normalized_key = (agent_key or "").lower().strip()
        model_settings_key = {
            "query": "data_query",
            "helpdesk": "helpdesk",
            "hd_tickets": "hd_tickets",
            "agent": "agent_mode",
            "insights": "insights",
        }.get(normalized_key)
        prompt_key = {
            "query": "query",
            "helpdesk": "helpdesk",
            "hd_tickets": "hd_tickets",
            "agent": "agent",
            "insights": "insights",
        }.get(normalized_key)

        runtime_settings: Dict[str, Any] = {}
        if model_settings_key:
            model_settings = self.get_model_settings(model_settings_key) or {}
            for fieldname in ("model", "temperature", "max_tokens"):
                if model_settings.get(fieldname) not in (None, ""):
                    runtime_settings[fieldname] = model_settings.get(fieldname)

        if prompt_key:
            system_prompt = self.get_prompt(prompt_key)
            if system_prompt:
                runtime_settings["system_prompt"] = system_prompt

        return runtime_settings

    def _build_builtin_agent_catalog(self, config=None):
        config = config or self._get_local_config()
        catalog = []
        for agent in BUILTIN_AGENT_MODES:
            entry = dict(agent)
            entry.update(self._get_builtin_agent_runtime_settings(entry.get("agent_key")))
            entry.setdefault("hint", "")
            entry.setdefault("status_message", "")
            entry.setdefault("supports_context", False)
            entry.setdefault("supports_upload", False)
            entry.setdefault("supports_gif", False)
            tenant_enabled = self._is_agent_enabled(config, entry.get("agent_key"))
            entry["tenant_enabled"] = tenant_enabled
            entry["is_available"] = bool(entry.get("visible_in_chat", True) and entry.get("enabled", True) and tenant_enabled)
            catalog.append(entry)
        return catalog

    def get_available_agent_catalog(self) -> list[dict]:
        """Return the built-in agent catalog filtered to enabled modes."""
        return [agent for agent in self._build_builtin_agent_catalog() if agent.get("is_available")]

    def _build_agent_availability_payload(self, config) -> Dict[str, Any]:
        """Build the tenant-level agent availability flags for the frontend."""
        helpdesk_installed = is_helpdesk_installed()
        return {
            "enable_query_agent": bool(frappe.utils.cint(config.get("enable_query_agent", 1))),
            "enable_helpdesk_agent": bool(frappe.utils.cint(config.get("enable_helpdesk_agent", 1))),
            "enable_hd_tickets": bool(frappe.utils.cint(config.get("enable_hd_tickets", 1))) and helpdesk_installed,
            "enable_agent_mode": bool(frappe.utils.cint(config.get("enable_agent_mode", 1))),
            "enable_insights_agent": bool(frappe.utils.cint(config.get("enable_insights_agent", 1))),
            "enable_rag_agent": bool(frappe.utils.cint(config.get("enable_rag_agent", 1))),
            "enable_rag_helpdesk": bool(frappe.utils.cint(config.get("enable_rag_helpdesk", 0))),
            "helpdesk_installed": helpdesk_installed,
            "available_agents": self.get_available_agent_catalog(),
        }

    def get_agent_config(self, agent_key: str) -> Dict[str, Any]:
        """
        Get a single agent configuration by key.

        Built-in modes are resolved from the static catalog.
        """
        key = (agent_key or "").lower().strip()
        if not key:
            return {}

        for agent in self._build_builtin_agent_catalog():
            if agent.get("agent_key") == key:
                return agent
        return {}
    
    def get_prompt(self, key: str) -> str:
        """
        Get a system prompt by key.
        
        Args:
            key: Prompt key (agent, query, helpdesk, insights, context)
            
        Returns:
            Prompt text
        """
        key = (key or "").lower().strip()
        cache_key = f"prompt:{key}"
        
        # Map prompt keys to agent types
        agent_type_map = {
            "agent": "agent_mode",
            "query": "data_query",
            "helpdesk": "helpdesk",
            "hd_tickets": "hd_tickets",
            "insights": "insights",
            "context": "context"
        }
        
        if self._is_core_enabled():
            cached = self._get_cached(cache_key)
            if cached is not None:  # Empty string is valid
                return cached
            
            client = self._get_core_client()
            if client:
                try:
                    agent_type = agent_type_map.get(key, key)
                    prompt = (client.get_system_prompt(agent_type) or "").strip()
                    if prompt:
                        self._set_cached(cache_key, prompt)
                        return prompt
                except Exception as e:
                    frappe.log_error(f"Failed to get prompt from Jive Core: {e}")
        
        # Fallback to local config
        return self._get_local_prompt(key)
    
    def _get_local_prompt(self, key: str) -> str:
        """Get prompt from local config."""
        config = self._get_local_config()
        if not config:
            return ""

        prompt_map = {
            "agent": config.get("agent_system_prompt"),
            "query": config.get("data_query_system_prompt"),
            "insights": config.get("insights_system_prompt"),
            "helpdesk": config.get("helpdesk_prompt"),
            "hd_tickets": config.get("hd_tickets_system_prompt"),
            "context": config.get("context_aware_system_prompt"),
        }
        
        return (prompt_map.get(key) or "").strip()
    
    def get_general_settings(self) -> Dict[str, Any]:
        """
        Get general settings (history, retention, features).
        
        Returns:
            Dict with general settings
        """
        cache_key = "general_settings"
        
        if self._is_core_enabled():
            cached = self._get_cached(cache_key)
            if cached:
                return cached
            
            client = self._get_core_client()
            if client:
                try:
                    settings = client.get_general_settings()
                    if settings:
                        self._set_cached(cache_key, settings)
                        return settings
                except Exception as e:
                    frappe.log_error(f"Failed to get general settings from Jive Core: {e}")
        
        # Fallback to local config
        config = self._get_local_config()
        if not config:
            return {}
        
        return {
            "max_history_messages": config.get("max_history_messages") or 10,
            "conversation_retention_days": config.get("conversation_retention_days") or 30,
            "enable_voice_input": config.get("enable_voice_input") or 1,
            "enable_file_upload": config.get("enable_file_upload") or 1,
            "enable_gif_generation": config.get("enable_gif_generation") or 1
        }
    
    def get_ui_settings(self) -> Dict[str, Any]:
        """
        Get UI settings (welcome message, colors, etc).
        
        Returns:
            Dict with UI settings
        """
        cache_key = "ui_settings"
        
        if self._is_core_enabled():
            cached = self._get_cached(cache_key)
            if cached:
                return cached
            
            client = self._get_core_client()
            if client:
                try:
                    settings = client.get_ui_settings()
                    if settings:
                        self._set_cached(cache_key, settings)
                        return settings
                except Exception as e:
                    frappe.log_error(f"Failed to get UI settings from Jive Core: {e}")
        
        # Fallback to local config
        config = self._get_local_config()
        if not config:
            return {}
        
        return {
            "welcome_title": config.get("welcome_title") or "What would you like to know?",
            "welcome_message": config.get("welcome_message") or "",
            "primary_color": config.get("primary_color") or "#6366f1",
            "show_suggestions": config.get("show_suggestions") or 1
        }
    
    def is_active(self) -> bool:
        """
        Check if Jive is active.
        
        Returns:
            True if Jive is enabled and configured
        """
        config = self._get_local_config()
        if not config:
            return False
        return bool(config.get("active_jive"))
    
    def is_core_mode(self) -> bool:
        """
        Check if running in Jive Core mode.
        
        Returns:
            True if using Jive Core for config
        """
        return self._is_core_enabled()
    
    def get_local_config(self):
        """
        Get the local Jive Config document.
        
        Useful when you need direct access to local fields
        (like included_doctypes for data sources).
        
        Returns:
            Jive Config document
        """
        return self._get_local_config()
    
    def is_feature_enabled(self, feature: str) -> bool:
        """
        Check if a feature is enabled.
        
        Supports features: enable_voice_input, enable_file_upload, enable_gif_generation
        
        Args:
            feature: Feature name (e.g., 'enable_voice_input')
            
        Returns:
            True if the feature is enabled
        """
        cache_key = f"feature:{feature}"
        
        if self._is_core_enabled():
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached
            
            # Fetch from Jive Core general settings
            settings = self.get_general_settings()
            value = bool(settings.get(feature, 1))
            self._set_cached(cache_key, value)
            return value
        
        # Local config
        config = self._get_local_config()
        return bool(config.get(feature, 1)) if config else True
    
    def get_agent_require_approval(self) -> bool:
        """
        Get whether agent mode requires user approval.
        
        Returns:
            True if agent actions require approval
        """
        model_settings = self.get_model_settings("agent_mode")
        return bool(model_settings.get("require_approval", 1))

    def get_rag_pipeline_mode(self) -> str:
        """Return the active RAG pipeline mode from Jive Config."""
        config = self._get_local_config()
        if not config:
            return "Legacy Site RAG"
        return (config.get("rag_pipeline_mode") or "Legacy Site RAG").strip()
    
    def get_all_config_for_frontend(self) -> Dict[str, Any]:
        """
        Get all configuration needed for the frontend.
        
        Used by the get_jive_config API to return complete settings.
        When Jive Core mode is enabled, fetches from remote.
        
        Returns:
            Dict with all frontend-relevant config
        """
        config = self._get_local_config()
        if not config:
            return {}

        allowed_doctypes = self._get_allowed_doctypes(config)
        if self._is_core_enabled():
            return self._build_core_frontend_config(config, allowed_doctypes)

        return self._build_local_frontend_config(config, allowed_doctypes)

    def _get_allowed_doctypes(self, config) -> list:
        allowed_doctypes = []
        if config.included_doctypes:
            for row in config.included_doctypes:
                dt = row.doctype_name
                if dt and frappe.has_permission(dt, "read"):
                    allowed_doctypes.append(dt)
        return allowed_doctypes

    def _build_core_frontend_config(self, config, allowed_doctypes: list) -> Dict[str, Any]:
        model_settings = self.get_model_settings()
        general_settings = self.get_general_settings()
        ui_settings = self.get_ui_settings()
        core_token_usage = self._build_core_token_usage(config)
        local_token_usage = self.get_local_token_usage(persist=False)
        return {
            "active": bool(config.get("active_jive")),
            "allowed_doctypes": allowed_doctypes,
            "token_usage": core_token_usage,
            "core_token_usage": core_token_usage,
            "local_token_usage": local_token_usage,
            **self._build_agent_availability_payload(config),
            "chat_model": model_settings.get("data_query", {}).get("model", "gpt-4o-mini"),
            "chat_temperature": model_settings.get("data_query", {}).get("temperature", 0.3),
            "chat_max_tokens": model_settings.get("data_query", {}).get("max_tokens", 4096),
            "help_desk_model": model_settings.get("helpdesk", {}).get("model", "gpt-4o-mini"),
            "helpdesk_temperature": model_settings.get("helpdesk", {}).get("temperature", 0.3),
            "helpdesk_max_tokens": model_settings.get("helpdesk", {}).get("max_tokens", 4096),
            "hd_tickets_model": model_settings.get("hd_tickets", {}).get("model", config.get("hd_tickets_model") or "gpt-4o-mini"),
            "agent_model": model_settings.get("agent_mode", {}).get("model", "gpt-4o-mini"),
            "agent_temperature": model_settings.get("agent_mode", {}).get("temperature", 0.2),
            "agent_require_approval": bool(model_settings.get("agent_mode", {}).get("require_approval", 1)),
            "insights_model": model_settings.get("insights", {}).get("model", "gpt-4o-mini"),
            "insights_temperature": model_settings.get("insights", {}).get("temperature", 0.3),
            "enable_voice_input": bool(general_settings.get("enable_voice_input", 1)),
            "enable_file_upload": bool(general_settings.get("enable_file_upload", 1)),
            "enable_gif_generation": bool(general_settings.get("enable_gif_generation", 1)),
            "max_history_messages": general_settings.get("max_history_messages", 10),
            "welcome_title": ui_settings.get("welcome_title", "What would you like to know?"),
            "welcome_message": ui_settings.get("welcome_message", ""),
            "primary_color": ui_settings.get("primary_color", "#6366f1"),
            "show_suggestions": bool(ui_settings.get("show_suggestions", 1)),
            "max_context_tokens": config.get("max_context_tokens") or 12000,
            "rag_pipeline_mode": self.get_rag_pipeline_mode(),
            "rag_default_vector_database": config.get("rag_default_vector_database") or "",
            "default_mode": "query",
            "setup_required": False,
            "use_jive_core": True,
        }

    def _build_local_frontend_config(self, config, allowed_doctypes: list) -> Dict[str, Any]:
        api_key = (
            config.get_password("open_ai_key", raise_exception=False)
            if hasattr(config, "get_password")
            else None
        )
        local_token_usage = self.get_local_token_usage()
        core_token_usage = self._build_core_token_usage(config)
        return {
            "active": bool(config.get("active_jive")),
            "allowed_doctypes": allowed_doctypes,
            "token_usage": local_token_usage,
            "core_token_usage": core_token_usage,
            "local_token_usage": local_token_usage,
            **self._build_agent_availability_payload(config),
            "chat_model": config.get("chat_model") or "gpt-4o-mini",
            "chat_temperature": config.get("chat_temperature") or 0.3,
            "chat_max_tokens": config.get("chat_max_tokens") or 4096,
            "help_desk_model": config.get("help_desk_model") or "gpt-4o-mini",
            "helpdesk_temperature": config.get("helpdesk_temperature") or 0.3,
            "helpdesk_max_tokens": config.get("helpdesk_max_tokens") or 4096,
            "hd_tickets_model": config.get("hd_tickets_model") or "gpt-4o-mini",
            "agent_model": config.get("agent_model") or "gpt-4o-mini",
            "agent_temperature": config.get("agent_temperature") or 0.2,
            "agent_require_approval": bool(config.get("agent_require_approval", 1)),
            "insights_model": config.get("insights_model") or config.get("chat_model") or "gpt-4o-mini",
            "insights_temperature": config.get("insights_temperature") or 0.3,
            "enable_voice_input": bool(config.get("enable_voice_input", 1)),
            "enable_file_upload": bool(config.get("enable_file_upload", 1)),
            "enable_gif_generation": bool(config.get("enable_gif_generation", 1)),
            "max_history_messages": config.get("max_history_messages") or 10,
            "welcome_title": config.get("welcome_title") or "What would you like to know?",
            "welcome_message": config.get("welcome_message") or "",
            "primary_color": config.get("primary_color") or "#6366f1",
            "show_suggestions": bool(config.get("show_suggestions", 1)),
            "max_context_tokens": config.get("max_context_tokens") or 12000,
            "rag_pipeline_mode": self.get_rag_pipeline_mode(),
            "rag_default_vector_database": config.get("rag_default_vector_database") or "",
            "default_mode": "query",
            "setup_required": not api_key,
            "use_jive_core": False,
        }
    
    def report_usage(
        self,
        agent_type: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        user: str = None,
        session_id: str = None
    ) -> bool:
        """
        Report token usage to Jive Core.
        
        Args:
            agent_type: Type of agent
            model: Model name
            tokens_in: Input tokens
            tokens_out: Output tokens
            user: User identifier
            session_id: Session ID
            
        Returns:
            True if reported successfully
        """
        from ampower_jive.utils.token_log_service import TokenLogService

        core_mode = self._is_core_enabled()
        state = "With Jive Core" if core_mode else "Without Jive Core"
        token_service = TokenLogService(site_name=frappe.local.site)
        local_log_name = self._log_local_usage(token_service, agent_type, model, tokens_in, tokens_out, user, session_id, state, core_mode)
        if core_mode:
            return self._report_core_usage(token_service, agent_type, model, tokens_in, tokens_out, user, session_id, local_log_name)

        return bool(local_log_name)

    def _log_local_usage(
        self,
        token_service,
        agent_type: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        user: str,
        session_id: str,
        state: str,
        core_mode: bool,
    ) -> str | None:
        local_log_name = token_service.log_usage(
            agent_type=agent_type,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            user=user,
            session_id=session_id,
            feature_type="chat",
            success=True,
            processing_time_ms=0,
            state=state,
            sync_cached_usage=not core_mode,
        )

        if not hasattr(frappe.local, "jive_token_usage_detail") or not frappe.local.jive_token_usage_detail:
            frappe.local.jive_token_usage_detail = {
                "tokens_in": int(tokens_in or 0),
                "tokens_out": int(tokens_out or 0),
                "total_tokens": int(tokens_in or 0) + int(tokens_out or 0),
                "state": state,
                "site_name": frappe.local.site,
            }

        local_snapshot = getattr(frappe.local, "jive_token_usage", None)
        if not local_snapshot:
            local_snapshot = token_service.get_usage_snapshot()
        if not hasattr(frappe.local, "jive_token_usage") or not frappe.local.jive_token_usage:
            frappe.local.jive_token_usage = local_snapshot

        return local_log_name

    def _report_core_usage(
        self,
        token_service,
        agent_type: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        user: str,
        session_id: str,
        local_log_name: str | None,
    ) -> bool:
        client = self._get_core_client()
        if client:
            try:
                result = client.log_token_usage(
                    agent_type=agent_type,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    user=user,
                    session_id=session_id,
                )

                if isinstance(result, dict):
                    if not result.get("logged"):
                        error = result.get("error", "Unknown error")
                        self._refresh_usage_after_core_attempt(token_service, local_log_name)
                        frappe.log_error(
                            message=f"Jive Core refused token usage: {error}",
                            title="Jive Token Log Error",
                        )
                        return False

                    quota = result.get("quota", {})
                    if quota:
                        frappe.local.jive_token_usage = quota
                        self._sync_core_usage_cache(quota)

                    return True
            except Exception as e:
                frappe.log_error(
                    message=f"Failed to report usage to Jive Core: {e}",
                    title="Jive Report Usage Error",
                )
                self._refresh_usage_after_core_attempt(token_service, local_log_name)
                return bool(local_log_name)
        self._refresh_usage_after_core_attempt(token_service, local_log_name)
        return bool(local_log_name)

    def _refresh_usage_after_core_attempt(self, token_service, local_log_name: str | None) -> None:
        if local_log_name:
            token_service.refresh_usage_snapshot()
        
    def invalidate_cache(self, key: str = None):
        """
        Invalidate cached values.
        
        Args:
            key: Specific key to invalidate, or None to clear all
        """
        if key:
            self._cache.pop(key, None)
            self._cache_timestamps.pop(key, None)
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            self._config_cache = None
            self._config_cache_time = 0
            self._config_cache_version = None
            try:
                frappe.cache().set_value(self._shared_cache_version_key, str(time.time()))
            except Exception:
                pass


# Module-level singleton accessor
_provider = None


def get_config_provider() -> JiveConfigProvider:
    """
    Get the singleton config provider instance.
    
    Returns:
        JiveConfigProvider instance
    """
    global _provider
    if _provider is None:
        _provider = JiveConfigProvider()
    return _provider

@frappe.whitelist()
def test_jive_core_connection() -> Dict[str, Any]:
    """
    Test connection to Jive Core.
    
    Whitelisted API for frontend "Test Connection" button.
    
    Returns:
        Dict with connection status
    """
    provider = get_config_provider()
    
    if not provider.is_core_mode():
        return {
            "success": False,
            "status": "Not Configured",
            "message": "Jive Core integration is not enabled"
        }
    
    client = provider._get_core_client()
    if not client:
        return {
            "success": False,
            "status": "Error",
            "message": "Failed to create Jive Core client - check URL and API key"
        }
    
    result = client.test_connection()
    
    # Update connection status field without saving the whole singleton doc
    try:
        frappe.db.set_single_value("Jive Config", "jive_core_connection_status", result.get("status", "Unknown"))
        provider.invalidate_cache()
    except Exception:
        pass

    return result
