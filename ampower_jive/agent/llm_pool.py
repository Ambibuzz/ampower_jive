"""
LLM Connection Pool Manager
Inspired by Cursor AI's approach to fast, responsive AI interactions.

Key features:
1. Connection pooling - Reuse LLM connections
2. Request caching - Cache similar queries
3. History compression - Reduce token usage
4. Tiered timeouts - Fast fail with fallbacks
5. Async-ready - Prepared for streaming
"""

import frappe
import time
import hashlib
import json
from typing import Optional, Dict, List, Any
from threading import Lock
from ..utils.tokens import TokenUsageCallbackHandler

# Try to import langchain
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    ChatOpenAI = None
    HumanMessage = AIMessage = SystemMessage = None


class LLMPool:
    """
    Singleton LLM connection pool manager.
    Maintains warm connections for faster responses.
    """
    
    _instance = None
    _lock = Lock()
    
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
        
        self._llm_cache: Dict[str, ChatOpenAI] = {}
        self._response_cache: Dict[str, dict] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._config_hash: str = None
        self._config: Any = None
        self._api_key: str = None
        self._last_config_check: float = 0
        self._config_ttl = 30  # Refresh config every 30 seconds
        self._response_cache_ttl = 300  # Cache responses for 5 minutes
        self._max_cache_size = 100
        self._initialized = True
    
    def _get_config(self) -> tuple:
        """Get config with caching to avoid repeated DB calls."""
        now = time.time()
        
        if self._config and (now - self._last_config_check) < self._config_ttl:
            return self._config, self._api_key
        
        try:
            # Use config provider for API key (supports Jive Core mode)
            from ..utils.config_provider import get_config_provider
            
            provider = get_config_provider()
            api_key = provider.get_api_key()
            
            # Still need local config for some settings
            config = provider.get_local_config()
            
            # Check if config changed
            new_hash = hashlib.md5(f"{api_key}:{config.get('chat_model') if config else ''}".encode()).hexdigest()
            if new_hash != self._config_hash:
                # Config changed - clear LLM cache
                self._llm_cache.clear()
                self._config_hash = new_hash
            
            self._config = config
            self._api_key = api_key
            self._last_config_check = now
            
            return config, api_key
        except Exception as e:
            frappe.log_error(
                message=f"LLMPool config error: {e}\n\n{frappe.get_traceback()}",
                title="LLM Pool"
            )
            return None, None
    
    def get_llm(
        self,
        model: str = None,
        temperature: float = 0.3,
        timeout: int = 45,
        purpose: str = "default",
        callbacks: List[Any] = None,
        add_token_callback: bool = True
    ) -> Optional[ChatOpenAI]:
        """
        Get a cached or new LLM connection.
        
        Args:
            model: Model name (defaults to config)
            temperature: Temperature setting
            timeout: Request timeout in seconds
            purpose: Cache key purpose (e.g., 'insights', 'query', 'helpdesk')
            callbacks: List of LangChain callbacks
            add_token_callback: Whether to add the default TokenUsageCallbackHandler
        
        Returns:
            ChatOpenAI instance or None
        """
        if not LANGCHAIN_AVAILABLE:
            return None
        
        config, api_key = self._get_config()
        
        if not api_key:
            return None
        
        # Get model from config based on purpose
        if purpose == "insights":
            model = model or config.get("insights_model") or config.get("chat_model") or "gpt-4o-mini"
        elif purpose == "agent":
            model = model or config.get("agent_model") or "gpt-4o-mini"
        elif purpose == "helpdesk":
            model = model or config.get("help_desk_model") or "gpt-4o-mini"
        else:
            model = model or config.get("chat_model") or "gpt-4o-mini"
        
        # Check if model supports temperature parameter
        # Models that DON'T support temperature: o1, o3, search-preview, gpt-5
        no_temp_models = ['o1', 'o3', 'search-preview', 'gpt-5']
        supports_temperature = not any(x in model.lower() for x in no_temp_models)
        
        # Create cache key
        # Include add_token_callback in cache key as it changes behavior.
        cache_key = f"{purpose}:{model}:{temperature if supports_temperature else 'no-temp'}:{timeout}:{add_token_callback}"
        callback_list = callbacks or []
        cacheable = not callback_list
        
        # Return cached LLM if exists
        if cacheable and cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        
        # Combine default callbacks with custom ones.
        # If a token callback is already provided explicitly, do not attach a
        # second one. That would report the same completion twice.
        has_explicit_token_callback = any(
            isinstance(callback, TokenUsageCallbackHandler) for callback in callback_list
        )
        default_callbacks = []
        if add_token_callback and not has_explicit_token_callback:
            default_callbacks = [TokenUsageCallbackHandler(purpose)]
        all_callbacks = default_callbacks + callback_list
        
        # Create new LLM with appropriate parameters
        try:
            if supports_temperature:
                llm = ChatOpenAI(
                    model=model,
                    api_key=api_key,
                    temperature=temperature,
                    timeout=timeout,
                    max_retries=2,
                    request_timeout=timeout,
                    callbacks=all_callbacks
                )
            else:
                # Models without temperature support
                llm = ChatOpenAI(
                    model=model,
                    api_key=api_key,
                    timeout=timeout,
                    max_retries=2,
                    request_timeout=timeout,
                    callbacks=all_callbacks
                )
            
            # Cache only stateless instances. Callbacks are often request
            # specific (for example session-scoped token logging), so reusing
            # them across requests would leak state.
            if cacheable:
                self._llm_cache[cache_key] = llm
            
            return llm
        except Exception as e:
            frappe.log_error(
                message=f"LLMPool LLM creation error: {e}\n\n{frappe.get_traceback()}",
                title="LLM Pool"
            )
            return None

    def get_response_from_cache(self, query_hash: str) -> Optional[dict]:
        """Get cached response if still valid."""
        if query_hash not in self._response_cache:
            return None

        timestamp = self._cache_timestamps.get(query_hash, 0)
        if (time.time() - timestamp) > self._response_cache_ttl:
            # Expired - remove from cache
            del self._response_cache[query_hash]
            del self._cache_timestamps[query_hash]
            return None

        return self._response_cache[query_hash]

    def cache_response(self, query_hash: str, response: dict):
        """Cache a response for future use."""
        # Enforce max cache size
        if len(self._response_cache) >= self._max_cache_size:
            # Remove oldest entries
            oldest = sorted(self._cache_timestamps.items(), key=lambda x: x[1])[:20]
            for key, _ in oldest:
                self._response_cache.pop(key, None)
                self._cache_timestamps.pop(key, None)
        
        self._response_cache[query_hash] = response
        self._cache_timestamps[query_hash] = time.time()
    
    def compute_query_hash(self, message: str, mode: str = "default") -> str:
        """
        Compute a hash for query caching.
        Normalizes the query to improve cache hits.
        """
        # Normalize: lowercase, remove extra spaces, common words
        normalized = message.lower().strip()
        normalized = ' '.join(normalized.split())
        
        # Remove common filler words for better matching
        stop_words = {'please', 'can', 'you', 'show', 'me', 'the', 'a', 'an', 'give', 'get'}
        words = [w for w in normalized.split() if w not in stop_words]
        normalized = ' '.join(words)
        
        return hashlib.md5(f"{mode}:{normalized}".encode()).hexdigest()
    
    def clear_cache(self):
        """Clear all caches."""
        self._llm_cache.clear()
        self._response_cache.clear()
        self._cache_timestamps.clear()


def compress_history(history: List[Dict], max_messages: int = 4, max_chars: int = 2000) -> List[Dict]:
    """
    Compress conversation history to reduce token usage.
    
    Strategies:
    1. Keep only recent messages
    2. Summarize older messages into context
    3. Truncate long messages (especially tool results)
    4. Skip tool messages (they don't transfer well to new context)
    
    Args:
        history: List of message dicts with 'role' and 'content'
        max_messages: Maximum number of messages to keep
        max_chars: Maximum characters per message
    
    Returns:
        Compressed history list with optional summary prefix
    """
    if not history:
        return []
    
    # Filter out tool messages - they cause issues when re-sent without their tool_calls context
    # Only keep user and assistant messages
    filtered_history = [
        msg for msg in history 
        if msg.get("role") in ("user", "assistant", "system")
    ]
    
    if not filtered_history:
        return []
    
    compressed = []
    
    # If we have more history than max, create a summary of older messages
    if len(filtered_history) > max_messages:
        old_messages = filtered_history[:-max_messages]
        summary = summarize_context(old_messages)
        if summary:
            compressed.append({
                "role": "system",
                "content": summary
            })
    
    # Take only recent messages
    recent = filtered_history[-max_messages:] if len(filtered_history) > max_messages else filtered_history
    
    for msg in recent:
        content = msg.get("content", "")
        role = msg.get("role", "user")
        
        # Skip empty messages
        if not content or not content.strip():
            continue
        
        # Truncate tool-like results in assistant messages
        if _looks_like_tool_result(content):
            content = _truncate_tool_result(content, max_chars=500)
        elif len(content) > max_chars:
            # For regular messages
            if role == "assistant":
                # Keep key parts of assistant response
                content = content[:max_chars//2] + "\n...[truncated]...\n" + content[-max_chars//4:]
            else:
                # For user messages, keep beginning
                content = content[:max_chars] + "..."
        
        compressed.append({
            "role": role,
            "content": content
        })
    
    return compressed


def _looks_like_tool_result(content: str) -> bool:
    """Check if content looks like a tool/JSON result."""
    content = content.strip()
    return (
        content.startswith('{') or 
        content.startswith('[') or
        '"success":' in content or
        '"data":' in content or
        '"error":' in content
    )


def _truncate_tool_result(content: str, max_chars: int = 500) -> str:
    """Truncate tool results while keeping key info."""
    try:
        # Try to parse as JSON
        data = json.loads(content)
        
        # Extract summary
        summary_parts = []
        
        if isinstance(data, dict):
            if data.get("success"):
                summary_parts.append("✓ Success")
            if data.get("error"):
                return json.dumps({"error": data["error"][:200]})
            if data.get("count") is not None:
                summary_parts.append(f"Count: {data['count']}")
            if data.get("doctype"):
                summary_parts.append(f"DocType: {data['doctype']}")
            if data.get("showing"):
                summary_parts.append(f"Showing: {data['showing']}")
            
            # For data arrays, just show count
            if "data" in data and isinstance(data["data"], list):
                items = data["data"]
                if items:
                    # Show first item keys as sample
                    first_item = items[0] if items else {}
                    keys = list(first_item.keys())[:5]
                    summary_parts.append(f"Fields: {', '.join(keys)}")
                    # Show first 2-3 items only
                    data["data"] = items[:3]
                    if len(items) > 3:
                        data["_note"] = f"Truncated: showing 3 of {len(items)} items"
        
        # Re-serialize with truncated data
        result = json.dumps(data, default=str)
        if len(result) > max_chars:
            return f"[Tool Result: {', '.join(summary_parts)}]"
        return result
        
    except (json.JSONDecodeError, TypeError):
        # Not JSON, just truncate
        if len(content) > max_chars:
            return content[:max_chars] + "...[truncated]"
        return content


def summarize_context(messages: List[Dict]) -> str:
    """
    Create a brief summary of conversation context.
    Used when history is too long.
    """
    if not messages:
        return ""
    
    # Extract key points from messages
    topics = set()
    actions = []
    
    for msg in messages:
        content = msg.get("content", "").lower()
        role = msg.get("role", "user")
        
        # Extract key nouns/topics
        for keyword in ['sales', 'customer', 'invoice', 'order', 'product', 'item', 
                       'revenue', 'purchase', 'stock', 'inventory', 'report', 'chart',
                       'employee', 'supplier', 'quotation', 'payment', 'expense']:
            if keyword in content:
                topics.add(keyword)
        
        # Extract what user asked for (from user messages)
        if role == "user" and len(content) < 200:
            actions.append(content[:50])
    
    # Build summary
    parts = []
    if topics:
        parts.append(f"Topics discussed: {', '.join(list(topics)[:5])}")
    if actions:
        parts.append(f"User asked: {'; '.join(actions[-2:])}")
    
    if parts:
        return "CONTEXT: " + " | ".join(parts)
    return ""


def prune_langraph_messages(messages: list, max_messages: int = 6) -> list:
    """
    Prune LangGraph messages to prevent accumulation.
    IMPORTANT: Keeps tool call chains intact (AIMessage with tool_calls + ToolMessage).
    
    Args:
        messages: List of LangChain message objects
        max_messages: Maximum messages to keep
    
    Returns:
        Pruned list of messages with valid tool call chains
    """
    if len(messages) <= max_messages:
        return messages
    
    # Separate by type
    system_msgs = []
    conversation = []  # Will hold (msg, is_part_of_tool_chain) tuples
    
    i = 0
    while i < len(messages):
        msg = messages[i]
        msg_type = type(msg).__name__
        
        if msg_type == "SystemMessage":
            system_msgs.append(msg)
            i += 1
            continue
        
        # Check if this is an AI message with tool calls
        if msg_type == "AIMessage" and hasattr(msg, "tool_calls") and msg.tool_calls:
            # This starts a tool chain - collect all following ToolMessages
            chain = [msg]
            i += 1
            while i < len(messages):
                next_msg = messages[i]
                next_type = type(next_msg).__name__
                if next_type == "ToolMessage":
                    chain.append(next_msg)
                    i += 1
                else:
                    break
            # Add the entire chain as one unit
            conversation.append(("chain", chain))
        else:
            # Regular message (HumanMessage, AIMessage without tools)
            conversation.append(("single", msg))
            i += 1
    
    # Now prune conversation, keeping tool chains intact
    # Calculate how many "units" we can keep
    available_slots = max_messages - len(system_msgs)
    
    # Start from the end, count backwards
    kept_units = []
    slots_used = 0
    
    for item in reversed(conversation):
        item_type, content = item
        if item_type == "chain":
            chain_size = len(content)
            if slots_used + chain_size <= available_slots:
                kept_units.insert(0, item)
                slots_used += chain_size
            # If chain doesn't fit, skip it entirely (don't break the chain!)
        else:
            if slots_used + 1 <= available_slots:
                kept_units.insert(0, item)
                slots_used += 1
    
    # Flatten the kept units
    pruned = []
    for item_type, content in kept_units:
        if item_type == "chain":
            pruned.extend(content)
        else:
            pruned.append(content)
    
    return system_msgs + pruned


def get_llm_pool() -> LLMPool:
    """Get the singleton LLM pool instance."""
    return LLMPool()


# Convenience functions
def get_cached_llm(
    purpose: str = "default",
    model: str = None,
    temperature: float = 0.3,
    timeout: int = 20,
    callbacks: List[Any] = None,
    add_token_callback: bool = True
) -> Optional[ChatOpenAI]:
    """Get a cached LLM connection."""
    return get_llm_pool().get_llm(model, temperature, timeout, purpose, callbacks, add_token_callback)
