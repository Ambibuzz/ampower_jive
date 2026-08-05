"""
Jive Core HTTP Client

HTTP client for calling Jive Core APIs from ampower_jive.
This allows ampower_jive to fetch config, API keys, and prompts
from a central Jive Core instance without any direct imports.
"""

import frappe
import json
import requests
from typing import Dict, Any, Optional

from ampower_jive.utils.context_summary import summarize_context_payload


def _summarize_context_payload(context_payload):
    return summarize_context_payload(context_payload)


class JiveCoreClient:
    """
    HTTP client for Jive Core API calls.
    
    Handles authentication and provides methods to fetch:
    - API keys
    - Model settings
    - System prompts
    - General settings
    """
    
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        """
        Initialize Jive Core client.
        
        Args:
            base_url: Base URL of Jive Core instance (e.g., https://core.example.com)
            api_key: API key for authentication
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/') if base_url else ""
        self.api_key = api_key
        self.timeout = timeout
        self._session = None
    
    @property
    def session(self) -> requests.Session:
        """Get or create a requests session."""
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                'Authorization': f'token {self.api_key}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            })
        return self._session
    
    def _make_request(
        self,
        method: str,
        params: Dict[str, Any] = None,
        http_method: str = 'GET'
    ) -> Dict[str, Any]:
        """
        Make an API request to Jive Core.
        
        Args:
            method: The API method name (e.g., 'ampower_jive_core.api.get_api_key')
            params: Optional parameters to pass
            http_method: HTTP method (GET or POST)
            
        Returns:
            API response as dict
            
        Raises:
            JiveCoreConnectionError: If connection fails
        """
        if not self.base_url:
            raise JiveCoreConnectionError("Jive Core URL not configured")
        
        url = f"{self.base_url}/api/method/{method}"
        
        # Shallow-copy to avoid mutating the caller's dict when injecting site_name
        payload = dict(params) if params else {}
        
        # Always inject current site name for tenant validation on the core side.
        # This is always overwritten (not conditional) to prevent internal callers
        # from accidentally or maliciously setting a wrong site_name.
        if getattr(frappe.local, 'site', None):
            payload['site_name'] = frappe.local.site
        
        try:
            if (params or {}).get("context_aware") or (params or {}).get("context_payload"):
                frappe.logger().info(
                    f"[JiveContextDebug] tenant.client.forward {json.dumps(_summarize_context_payload((params or {}).get('context_payload')), default=str, ensure_ascii=False)}"
                )

            if http_method.upper() == 'POST':
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.timeout
                )
            else:
                response = self.session.get(
                    url,
                    params=payload,
                    timeout=self.timeout
                )

            
            response.raise_for_status()
            
            data = response.json()
            
            # Frappe API wraps response in 'message'
            if 'message' in data:
                return data['message']
            return data
            
        except requests.exceptions.Timeout:
            raise JiveCoreConnectionError(f"Timeout connecting to Jive Core at {self.base_url}")
        except requests.exceptions.ConnectionError as e:
            raise JiveCoreConnectionError(f"Failed to connect to Jive Core: {e}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise JiveCoreConnectionError("Invalid Jive Core API key")
            elif e.response.status_code == 403:
                raise JiveCoreConnectionError("Access denied - check API key permissions")
            elif e.response.status_code == 404:
                raise JiveCoreConnectionError(f"API endpoint not found: {method}")
            else:
                raise JiveCoreConnectionError(f"HTTP error {e.response.status_code}: {e}")
        except Exception as e:
            raise JiveCoreConnectionError(f"Unexpected error: {e}")
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test the connection to Jive Core.
        
        Returns:
            Dict with connection status and info
        """
        try:
            result = self._make_request('ampower_jive_core.api.get_core_status')
            return {
                'success': True,
                'status': 'Connected',
                'enabled': result.get('enabled', False),
                'site_name': result.get('site_name'),
                'message': 'Successfully connected to Jive Core'
            }
        except JiveCoreConnectionError as e:
            return {
                'success': False,
                'status': 'Error',
                'message': str(e)
            }
    
    def get_api_key(self) -> Optional[str]:
        """
        Get the OpenAI API key from Jive Core.
        
        Returns:
            API key string or None
        """
        try:
            result = self._make_request('ampower_jive_core.api.get_api_key')
            return result if isinstance(result, str) else None
        except JiveCoreConnectionError:
            return None
    
    def get_model_settings(self, agent_type: str = None) -> Dict[str, Any]:
        """
        Get model settings from Jive Core.
        
        Args:
            agent_type: Optional agent type (data_query, helpdesk, agent_mode, insights)
            
        Returns:
            Dict with model settings
        """
        params = {'agent_type': agent_type} if agent_type else {}
        try:
            return self._make_request(
                'ampower_jive_core.api.get_model_settings',
                params
            )
        except JiveCoreConnectionError:
            return {}
    
    def get_system_prompt(self, agent_type: str, fallback: str = None) -> str:
        """
        Get a system prompt from Jive Core.
        
        Args:
            agent_type: Agent type (data_query, helpdesk, agent, insights)
            fallback: Fallback prompt if none configured
            
        Returns:
            Prompt text
        """
        try:
            result = self._make_request(
                'ampower_jive_core.api.get_system_prompt',
                {'agent_type': agent_type, 'fallback': fallback}
            )
            return result if isinstance(result, str) else (fallback or "")
        except JiveCoreConnectionError:
            return fallback or ""
    
    def get_general_settings(self) -> Dict[str, Any]:
        """
        Get general settings from Jive Core.
        
        Returns:
            Dict with general settings
        """
        try:
            return self._make_request('ampower_jive_core.api.get_general_settings')
        except JiveCoreConnectionError:
            return {}
    
    def get_ui_settings(self) -> Dict[str, Any]:
        """
        Get UI settings from Jive Core.
        
        Returns:
            Dict with UI settings
        """
        try:
            return self._make_request('ampower_jive_core.api.get_ui_settings')
        except JiveCoreConnectionError:
            return {}
    
    def get_all_settings(self) -> Dict[str, Any]:
        """
        Get all managed settings from Jive Core in a single call.
        
        Returns:
            Dict with all settings (models, general, ui, prompts, billing)
        """
        try:
            return self._make_request('ampower_jive_core.api.get_all_managed_settings')
        except JiveCoreConnectionError:
            return {}
    
    def log_token_usage(
        self,
        agent_type: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        user: str = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Log token usage to Jive Core.
        
        Args:
            agent_type: Type of agent
            model: Model name
            tokens_in: Input tokens
            tokens_out: Output tokens
            user: User identifier
            session_id: Session ID
            
        Returns:
            Dict with log status
        """
        try:
            return self._make_request(
                'ampower_jive_core.api.log_token_usage',
                {
                    'agent_type': agent_type,
                    'model': model,
                    'tokens_in': tokens_in,
                    'tokens_out': tokens_out,
                    'user': user,
                    'session_id': session_id,
                    'site_name': frappe.local.site
                },
                http_method='POST'
            )
        except JiveCoreConnectionError as e:
            return {'logged': False, 'error': f'Connection failed: {str(e)}'}

    def log_interaction(
        self,
        agent_type: str,
        model: str = None,
        status: str = "success",
        request_payload: str = None,
        response_payload: str = None,
        error_message: str = None,
        error_traceback: str = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        processing_time_ms: int = 0,
        user: str = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Log a detailed LLM interaction to Jive Core.

        Args:
            agent_type: Type of agent (data_query, helpdesk, agent_mode, insights)
            model: LLM model used
            status: success, error, or timeout
            request_payload: JSON string of the request sent to LLM
            response_payload: Full response text from LLM
            error_message: Error message if failed
            error_traceback: Full traceback if failed
            tokens_in: Prompt tokens
            tokens_out: Completion tokens
            processing_time_ms: Duration in ms
            user: User identifier
            session_id: Session ID

        Returns:
            Dict with log status
        """
        try:
            return self._make_request(
                'ampower_jive_core.api.log_interaction',
                {
                    'agent_type': agent_type,
                    'model': model,
                    'status': status,
                    'request_payload': request_payload,
                    'response_payload': response_payload,
                    'error_message': error_message,
                    'error_traceback': error_traceback,
                    'tokens_in': tokens_in,
                    'tokens_out': tokens_out,
                    'processing_time_ms': processing_time_ms,
                    'user': user or frappe.session.user,
                    'session_id': session_id,
                    'site_name': frappe.local.site,
                },
                http_method='POST'
            )
        except Exception as e:
            frappe.log_error(f"JiveCoreClient log_interaction failed: {e}", "Jive Core Sync Error")
            return {'logged': False, 'error': str(e)}

    def update_log_feedback(
        self,
        log_name: str,
        feedback: str,
        feedback_comment: str = None,
        user: str = None
    ) -> Dict[str, Any]:
        """
        Send user feedback for a specific interaction log to Jive Core.
        
        Args:
            log_name: Name of the Jive Logs document
            feedback: 'Like' or 'Dislike'
            feedback_comment: Optional text comment
            user: User ID
            
        Returns:
            Dict with status
        """
        try:
            return self._make_request(
                'ampower_jive_core.api.update_log_feedback',
                {
                    'log_name': log_name,
                    'feedback': feedback,
                    'feedback_comment': feedback_comment,
                    'user': user or frappe.session.user,
                    'site_name': frappe.local.site,
                },
                http_method='POST'
            )
        except Exception as e:
            frappe.log_error(f"JiveCoreClient update_log_feedback failed: {e}", "Jive Core Sync Error")
            return {'success': False, 'error': str(e)}
    def update_log_feedback_by_session(
        self,
        session_id: str,
        feedback: str,
        feedback_comment: str = None,
        user: str = None,
        response_snippet: str = None
    ) -> Dict[str, Any]:
        """
        Send user feedback for the latest interaction log in a session to Jive Core.
        
        Args:
            session_id: Chat session ID
            feedback: 'Like' or 'Dislike'
            feedback_comment: Optional text comment
            user: User ID
            response_snippet: Optional string matcher to identify exact message
            
        Returns:
            Dict with status
        """
        try:
            return self._make_request(
                'ampower_jive_core.api.update_log_feedback_by_session',
                {
                    'session_id': session_id,
                    'feedback': feedback,
                    'feedback_comment': feedback_comment,
                    'user': user or frappe.session.user,
                    'site_name': frappe.local.site,
                    'response_snippet': response_snippet
                },
                http_method='POST'
            )
        except Exception as e:
            frappe.log_error(f"JiveCoreClient update_log_feedback_by_session failed: {e}", "Jive Core Sync Error")
            return {'success': False, 'error': str(e)}


class JiveCoreConnectionError(Exception):
    """Exception raised when Jive Core connection fails."""
    pass
