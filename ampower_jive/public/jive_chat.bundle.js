window.JiveChat = class JiveChat {
    constructor(container, options = {}) {
        this.container = container;
        this.conversationId = null;
        this.isLoading = false;
        this.messages = [];
        this.currentMode = 'query';
        this.contextAware = (() => {
            const stored = localStorage.getItem('jive_context_aware');
            return stored === null ? true : stored === '1';
        })();
        this.queryContextAwarePreference = this.contextAware;
        this.pendingPlan = null;
        this.isRecording = false;
        this.recognition = null;
        this.contextFiles = [];
        this.activeViewContext = null;
        this.routeChangeTimer = null;
        this.routeEventsBound = false;
        this.pageContextObserver = null;
        this.pageContextRefreshTimer = null;
        this.pendingContextRouteKey = '';
        this.sessionId = this.generateSessionId();
        this.conversations = [];
        this.modeOpen = false;
        this.config = null;
        this.theme = localStorage.getItem('jive_theme') || 'dark';
        const portalAccessFromContainer = !!(container && container.dataset && container.dataset.portalAccess === '1');
        this.portalAccess = !!(options.portalAccess || portalAccessFromContainer);
        this.init();
    }

    generateSessionId() {
        return 'sess_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    getBuiltinModes() {
        return {
            query: {
                agent_key: 'query',
                label: 'Data Query',
                hint: 'Search your ERPNext data',
                icon: '⬡',
                color: '#6366f1',
                handler_type: 'query',
                status_message: 'Searching your data...',
                supports_context: true,
                supports_upload: false,
                supports_gif: false,
                visible_in_chat: true,
                enabled: true,
                sort_order: 10
            },
            helpdesk: {
                agent_key: 'helpdesk',
                label: 'Helpdesk',
                hint: 'Get help and guidance',
                icon: '?',
                color: '#f59e0b',
                handler_type: 'helpdesk',
                status_message: 'Generating response...',
                supports_context: false,
                supports_upload: true,
                supports_gif: true,
                visible_in_chat: true,
                enabled: true,
                sort_order: 20
            },
            agent: {
                agent_key: 'agent',
                label: 'Agent',
                hint: 'Create and modify documents',
                icon: '◈',
                color: '#10b981',
                handler_type: 'agent',
                status_message: 'Analyzing your request...',
                supports_context: true,
                supports_upload: false,
                supports_gif: false,
                visible_in_chat: true,
                enabled: true,
                sort_order: 30
            },
            insights: {
                agent_key: 'insights',
                label: 'Insights',
                hint: 'Create charts and dashboards',
                icon: '◉',
                color: '#8b5cf6',
                handler_type: 'insights',
                status_message: 'Creating visualization...',
                supports_context: true,
                supports_upload: false,
                supports_gif: false,
                visible_in_chat: true,
                enabled: true,
                sort_order: 40
            },
            rag: {
                agent_key: 'rag',
                label: 'RAG',
                hint: 'Ask questions about attached documents',
                icon: '◈',
                color: '#0ea5e9',
                handler_type: 'rag',
                status_message: 'Searching your knowledge base...',
                supports_context: true,
                supports_upload: false,
                supports_gif: false,
                visible_in_chat: true,
                enabled: true,
                sort_order: 50
            }
        };
    }

    normalizeMode(mode) {
        const key = (mode || 'query').toLowerCase().trim();
        return key === 'context' ? 'query' : key;
    }

    normalizeModeEntry(entry) {
        const e = entry || {};
        const agentKey = this.normalizeMode(e.agent_key || e.mode || e.key || '');
        const builtin = this.getBuiltinModes()[agentKey] || {};
        return {
            agent_key: agentKey,
            label: e.label || builtin.label || agentKey.toUpperCase(),
            hint: e.hint || e.description || builtin.hint || '',
            icon: e.icon || builtin.icon || '◉',
            color: e.color || builtin.color || '#6366f1',
            handler_type: this.normalizeMode(e.handler_type || builtin.handler_type || agentKey),
            status_message: e.status_message || builtin.status_message || 'Thinking...',
            supports_context: e.supports_context !== undefined ? !!e.supports_context : !!builtin.supports_context,
            supports_upload: e.supports_upload !== undefined ? !!e.supports_upload : !!builtin.supports_upload,
            supports_gif: e.supports_gif !== undefined ? !!e.supports_gif : !!builtin.supports_gif,
            visible_in_chat: e.visible_in_chat !== undefined ? !!e.visible_in_chat : !!builtin.visible_in_chat,
            enabled: e.enabled !== undefined ? !!e.enabled : !!builtin.enabled,
            sort_order: Number(e.sort_order || builtin.sort_order || 100),
            model: e.model || builtin.model || '',
            temperature: e.temperature !== undefined ? e.temperature : builtin.temperature,
            max_tokens: e.max_tokens !== undefined ? e.max_tokens : builtin.max_tokens,
            system_prompt: e.system_prompt || builtin.system_prompt || '',
            tenant_visible_in_chat: e.tenant_visible_in_chat,
            tenant_enabled: e.tenant_enabled
        };
    }

    isTruthyFlag(value, defaultValue = true) {
        if (value === undefined || value === null || value === '') {
            return defaultValue;
        }
        if (typeof value === 'boolean') {
            return value;
        }
        if (typeof value === 'number') {
            return value !== 0;
        }

        const normalized = String(value).trim().toLowerCase();
        if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
        if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
        return defaultValue;
    }

    getAgentAvailabilityMap() {
        const config = this.config || {};
        return {
            query: this.isTruthyFlag(config.enable_query_agent, true),
            helpdesk: this.isTruthyFlag(config.enable_helpdesk_agent, true),
            hd_tickets: this.isTruthyFlag(config.enable_hd_tickets, true),
            agent: this.isTruthyFlag(config.enable_agent_mode, true),
            insights: this.isTruthyFlag(config.enable_insights_agent, true),
            rag: this.isTruthyFlag(config.enable_rag_agent, true)
        };
    }

    isBuiltinModeEnabled(mode) {
        const key = this.normalizeMode(mode);
        const availability = this.getAgentAvailabilityMap();
        return availability[key] !== false;
    }

    getModeCatalog() {
        const catalog = {};
        Object.values(this.getBuiltinModes()).forEach(mode => {
            const normalized = this.normalizeModeEntry(mode);
            if (
                !normalized.agent_key ||
                !this.isBuiltinModeEnabled(normalized.agent_key) ||
                !this.isTruthyFlag(normalized.visible_in_chat, true) ||
                !this.isTruthyFlag(normalized.enabled, true)
            ) {
                return;
            }
            catalog[normalized.agent_key] = normalized;
        });

        const coreModes = Array.isArray(this.config?.available_agents) ? this.config.available_agents : [];
        coreModes.forEach(mode => {
            const normalized = this.normalizeModeEntry(mode);
            if (!normalized.agent_key) return;
            if (
                !this.isTruthyFlag(normalized.visible_in_chat, true) ||
                !this.isTruthyFlag(normalized.enabled, true) ||
                !this.isTruthyFlag(normalized.tenant_visible_in_chat, true) ||
                !this.isTruthyFlag(normalized.tenant_enabled, true) ||
                !this.isTruthyFlag(normalized.is_available, true)
            ) {
                return;
            }
            if (this.getBuiltinModes()[normalized.agent_key] && !this.isBuiltinModeEnabled(normalized.agent_key)) {
                return;
            }
            if (catalog[normalized.agent_key]) return;
            catalog[normalized.agent_key] = normalized;
        });

        return Object.values(catalog).sort((a, b) => (a.sort_order || 100) - (b.sort_order || 100));
    }

    getModeMeta(mode) {
        const key = this.normalizeMode(mode);
        if (key === 'context') {
            const query = this.normalizeModeEntry(this.getBuiltinModes().query);
            return { ...query, agent_key: 'query', context_mode: true };
        }

        const builtin = this.getBuiltinModes()[key];
        if (builtin) {
            return this.normalizeModeEntry(builtin);
        }

        const match = this.getModeCatalog().find(item => item.agent_key === key);
        return match || this.normalizeModeEntry(this.getBuiltinModes().query);
    }

    isModeAllowed(mode) {
        const key = this.normalizeMode(mode);
        if (key === 'context') return true;
        return this.getModeCatalog().some(item => item.agent_key === key);
    }

    getDefaultMode() {
        const configured = this.normalizeMode(this.config?.default_mode || 'query');
        if (this.isModeAllowed(configured)) return configured;
        const fallback = this.getModeCatalog()[0];
        return fallback ? fallback.agent_key : 'query';
    }

    async init() {
        const config = await this.getConfig();

        // Check permissions first
        if (!config.has_access) {
            this.showNoAccess();
            return;
        }

        // Check if Jive is active
        if (!config.active) {
            this.showInactive(config.is_admin);
            return;
        }

        this.config = config;
        this.currentMode = this.getDefaultMode();
        this.render();
        this.bindEvents();
        this.bindPageContextObserver();
        if (this.config.enable_voice_input) {
            this.initVoice();
        }
        this.refreshActiveViewContext(true);
        this.bindRouteEvents();
        this.loadContextFiles();
        this.loadConversations();
    }

    async getConfig() {
        try {
            const r = await frappe.call({
                method: 'ampower_jive.api.get_jive_config',
                args: {
                    portal_access: this.portalAccess ? 1 : 0
                },
                freeze: false
            });
            const config = r.message || { active: false };
            if (this.portalAccess) {
                config.has_access = true;
                config.portal_access = true;
            }
            return config;
        } catch (e) { return { active: false }; }
    }

    initVoice() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) return;
        this.recognition = new SR();
        this.recognition.continuous = false;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-US';
        this.recognition.onresult = (e) => {
            let final = '', interim = '';
            for (let i = e.resultIndex; i < e.results.length; i++) {
                const t = e.results[i][0].transcript;
                e.results[i].isFinal ? final += t : interim += t;
            }
            const input = document.getElementById('jiveInput');
            if (input) { input.value = final || interim; this.autoResize(input); }
            if (final) { this.stopVoice(); setTimeout(() => this.send(), 300); }
        };
        this.recognition.onend = () => { this.isRecording = false; this.updateVoiceUI(); };
        this.recognition.onerror = () => { this.isRecording = false; this.updateVoiceUI(); };
    }

    toggleVoice() {
        if (!this.recognition || !this.config.enable_voice_input) return;
        if (this.isRecording) {
            this.recognition.stop();
            this.isRecording = false;
        } else {
            this.recognition.start();
            this.isRecording = true;
        }
        this.updateVoiceUI();
    }

    stopVoice() {
        if (this.recognition) {
            this.recognition.stop();
            this.isRecording = false;
            this.updateVoiceUI();
        }
    }

    updateVoiceUI() {
        const btn = document.getElementById('voiceBtn');
        if (btn) btn.classList.toggle('active', this.isRecording);
    }

    showNoAccess() {
        this.container.innerHTML = `
            <div class="jive-inactive">
                <div class="jive-inactive-logo">
                    <div class="jive-inactive-icon" style="background:linear-gradient(135deg,#ef4444,#dc2626);">🔒</div>
                    <div class="jive-inactive-brand">
                        <span class="jive-inactive-name">Jive</span>
                        <span class="jive-inactive-by">by Ambibuzz</span>
                    </div>
                </div>
                <h2>Access Required</h2>
                <p>You don't have permission to use Jive AI.</p>
                <p style="font-size:13px;margin-top:4px;">Please contact your administrator to grant you the <strong style="color:#f3f4f6;">'Jive User'</strong> role.</p>
                <a href="/app">← Back to Home</a>
                <div class="jive-inactive-footer">
                    <span>© ${new Date().getFullYear()}</span>
                    <a href="https://ambibuzz.com" target="_blank">Ambibuzz Technologies LLP</a>
                </div>
            </div>
            <style>
                .jive-inactive { display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;border-radius:16px;background:#0a0a0b;color:#6b7280;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;gap:12px;text-align:center;padding:20px;box-shadow:0 10px 40px rgba(0,0,0,0.3); }
                .jive-inactive-logo { display:flex;align-items:center;gap:12px;margin-bottom:12px; }
                .jive-inactive-icon { width:48px;height:48px;background:linear-gradient(135deg,#6366f1,#8b5cf6);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
                .jive-inactive-brand { display:flex;flex-direction:column; }
                .jive-inactive-name { font-size:24px;font-weight:600;color:#f3f4f6;line-height:1.2; }
                .jive-inactive-by { font-size:11px;color:#6b7280; }
                .jive-inactive h2 { color:#f3f4f6;margin:0;font-weight:500;font-size:18px; }
                .jive-inactive p { margin:0;font-size:14px;max-width:400px; }
                .jive-inactive > a { color:#818cf8;text-decoration:none;font-size:14px;margin-top:8px;padding:8px 16px;background:rgba(99,102,241,0.1);border-radius:6px;transition:all 0.15s; }
                .jive-inactive > a:hover { background:rgba(99,102,241,0.2); }
                .jive-inactive-footer { position:absolute;bottom:24px;display:flex;align-items:center;gap:6px;font-size:11px;color:#4b5563; }
                .jive-inactive-footer a { color:#6b7280;text-decoration:none; }
                .jive-inactive-footer a:hover { color:#818cf8; }
            </style>`;
    }

    showInactive(isAdmin = false) {
        const adminLink = isAdmin ? `<a href="/app/jive-config">Open Settings →</a>` : `<p style="font-size:13px;margin-top:4px;">Please contact your administrator to enable Jive.</p>`;
        this.container.innerHTML = `
            <div class="jive-inactive">
                <div class="jive-inactive-logo">
                    <div class="jive-inactive-icon">A</div>
                    <div class="jive-inactive-brand">
                        <span class="jive-inactive-name">Jive</span>
                        <span class="jive-inactive-by">by Ambibuzz</span>
                    </div>
                </div>
                <h2>Jive is not active</h2>
                <p>Jive AI is currently disabled.</p>
                ${adminLink}
                <div class="jive-inactive-footer">
                    <span>© ${new Date().getFullYear()}</span>
                    <a href="https://ambibuzz.com" target="_blank">Ambibuzz Technologies LLP</a>
                </div>
            </div>
            <style>
                .jive-inactive { display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;border-radius:16px;background:#0a0a0b;color:#6b7280;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;gap:12px;box-shadow:0 10px 40px rgba(0,0,0,0.3); }
                .jive-inactive-logo { display:flex;align-items:center;gap:12px;margin-bottom:12px; }
                .jive-inactive-icon { width:48px;height:48px;background:linear-gradient(135deg,#6366f1,#8b5cf6);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:700;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }
                .jive-inactive-brand { display:flex;flex-direction:column; }
                .jive-inactive-name { font-size:24px;font-weight:600;color:#f3f4f6;line-height:1.2; }
                .jive-inactive-by { font-size:11px;color:#6b7280; }
                .jive-inactive h2 { color:#f3f4f6;margin:0;font-weight:500;font-size:18px; }
                .jive-inactive p { margin:0;font-size:14px; }
                .jive-inactive > a { color:#818cf8;text-decoration:none;font-size:14px;margin-top:8px;padding:8px 16px;background:rgba(99,102,241,0.1);border-radius:6px;transition:all 0.15s; }
                .jive-inactive > a:hover { background:rgba(99,102,241,0.2); }
                .jive-inactive-footer { position:absolute;bottom:24px;display:flex;align-items:center;gap:6px;font-size:11px;color:#4b5563; }
                .jive-inactive-footer a { color:#6b7280;text-decoration:none; }
                .jive-inactive-footer a:hover { color:#818cf8; }
            </style>`;
    }

    render() {
        const modes = this.getModeCatalog();
        const modeMap = modes.reduce((acc, mode) => {
            acc[mode.agent_key] = mode;
            return acc;
        }, {});
        const activeMode = this.isModeAllowed(this.currentMode) ? this.normalizeMode(this.currentMode) : this.getDefaultMode();
        const m = modeMap[activeMode] || this.getModeMeta('query');
        this.currentMode = activeMode;
        const doctypes = this.config.allowed_doctypes || [];
        // Show correct model based on current mode
        let model;
        if (this.normalizeMode(this.currentMode) === 'helpdesk') {
            model = this.config.help_desk_model || 'gpt-4o-mini-search-preview';
        } else if (this.normalizeMode(this.currentMode) === 'hd_tickets') {
            model = this.config.hd_tickets_model || (this.getModeMeta(this.currentMode).model || this.config.help_desk_model || 'gpt-4o-mini');
        } else if (this.normalizeMode(this.currentMode) === 'agent') {
            model = this.config.agent_model || 'gpt-4o-mini';
        } else if (this.normalizeMode(this.currentMode) === 'insights') {
            model = this.config.insights_model || 'gpt-4o-mini';
        } else {
            const currentModeConfig = this.getModeMeta(this.currentMode);
            model = currentModeConfig.model || this.config.chat_model || 'gpt-4o-mini';
        }
        const user = frappe.session.user_fullname || frappe.session.user;
        const userEmail = frappe.session.user;
        const enableVoice = this.config.enable_voice_input;
        const enableUpload = this.config.enable_file_upload;

        this.container.innerHTML = `
            <style>
                * { box-sizing: border-box; margin: 0; padding: 0; }
                
                /* Theme Variables - Dark */
                .jive {
                    --bg-primary: #0a0a0b;
                    --bg-secondary: #0f0f11;
                    --bg-tertiary: #111214;
                    --bg-elevated: #1f2937;
                    --bg-hover: #374151;
                    --border-color: #1f2937;
                    --border-light: #2d3748;
                    --text-primary: #e5e7eb;
                    --text-secondary: #9ca3af;
                    --text-muted: #6b7280;
                    --text-dim: #4b5563;
                    --accent: #6366f1;
                    --accent-light: #818cf8;
                    --accent-bg: rgba(99, 102, 241, 0.1);
                    --success: #10b981;
                    --warning: #f59e0b;
                    --error: #ef4444;
                    --scrollbar: #374151;
                }
                
                /* Theme Variables - Light */
                .jive.light {
                    --bg-primary: #ffffff;
                    --bg-secondary: #f9fafb;
                    --bg-tertiary: #f3f4f6;
                    --bg-elevated: #e5e7eb;
                    --bg-hover: #d1d5db;
                    --border-color: #e5e7eb;
                    --border-light: #d1d5db;
                    --text-primary: #111827;
                    --text-secondary: #4b5563;
                    --text-muted: #6b7280;
                    --text-dim: #9ca3af;
                    --accent: #4f46e5;
                    --accent-light: #6366f1;
                    --accent-bg: rgba(79, 70, 229, 0.1);
                    --success: #059669;
                    --warning: #d97706;
                    --error: #dc2626;
                    --scrollbar: #d1d5db;
                }
                
                .jive {
                    display: flex;
                    height: 100%;
                    width: 100%;
                    background: var(--bg-primary);
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    color: var(--text-primary);
                    transition: background 0.3s, color 0.3s;
                    overflow: hidden;
                    border-radius: 16px;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.3);
                    position: relative;
                }
                
                /* Sidebar */
                .jive-sidebar {
                    width: 260px;
                    background: var(--bg-secondary);
                    border-right: 1px solid var(--border-color);
                    display: flex;
                    flex-direction: column;
                    flex-shrink: 0;
                    position: absolute;
                    left: 0;
                    top: 0;
                    bottom: 0;
                    z-index: 50;
                    transform: translateX(-100%);
                    transition: transform 0.3s ease;
                    box-shadow: 4px 0 15px rgba(0,0,0,0.2);
                }
                .jive-sidebar.open {
                    transform: translateX(0);
                }
                
                .jive-sidebar-header {
                    padding: 16px;
                    border-bottom: 1px solid #1f2937;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }
                
                .jive-brand {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }
                
                .jive-logo {
                    width: 28px;
                    height: 28px;
                    background: linear-gradient(135deg, #6366f1, #8b5cf6);
                    border-radius: 8px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 15px;
                    font-weight: 700;
                    color: #fff;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                }
                
                .jive-brand-text {
                    display: flex;
                    flex-direction: column;
                }
                
                .jive-title {
                    font-size: 15px;
                    font-weight: 600;
                    color: #f9fafb;
                    line-height: 1.2;
                }
                
                .jive-subtitle {
                    font-size: 9px;
                    color: #6b7280;
                    font-weight: 400;
                    letter-spacing: 0.3px;
                }
                
                .jive-new-btn {
                    width: 32px;
                    height: 32px;
                    background: #1f2937;
                    border: 1px solid #374151;
                    border-radius: 8px;
                    color: #9ca3af;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.15s;
                }
                
                .jive-new-btn:hover { background: #374151; color: #e5e7eb; }
                .jive-new-btn svg { width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 2; }
                
                /* Chat History */
                .jive-history {
                    flex: 1;
                    overflow-y: auto;
                    padding: 12px;
                }
                
                .jive-history::-webkit-scrollbar { width: 4px; }
                .jive-history::-webkit-scrollbar-track { background: transparent; }
                .jive-history::-webkit-scrollbar-thumb { background: #374151; border-radius: 2px; }
                
                .jive-history-title {
                    font-size: 11px;
                    font-weight: 600;
                    color: #6b7280;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    padding: 8px 12px;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }
                
                .jive-history-title svg {
                    width: 14px;
                    height: 14px;
                    stroke: currentColor;
                    fill: none;
                    stroke-width: 2;
                }
                
                .jive-history-item {
                    display: flex;
                    align-items: flex-start;
                    gap: 10px;
                    padding: 10px 12px;
                    border-radius: 8px;
                    cursor: pointer;
                    transition: all 0.15s;
                    margin-bottom: 2px;
                }
                
                .jive-history-item:hover { background: #1f2937; }
                .jive-history-item.active { background: #1f2937; border-left: 2px solid #6366f1; }
                
                .jive-history-icon {
                    width: 32px;
                    height: 32px;
                    border-radius: 8px;
                    background: #1f2937;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                    font-size: 12px;
                }
                
                .jive-history-icon.query { color: #818cf8; }
                .jive-history-icon.context { color: #a78bfa; }
                .jive-history-icon.helpdesk { color: #fbbf24; }
                .jive-history-icon.agent { color: #34d399; }
                
                .jive-history-content {
                    flex: 1;
                    min-width: 0;
                }
                
                .jive-history-text {
                    font-size: 13px;
                    color: #e5e7eb;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-bottom: 2px;
                }
                
                .jive-history-meta {
                    font-size: 11px;
                    color: #4b5563;
                }
                
                .jive-history-delete {
                    opacity: 0;
                    width: 28px;
                    height: 28px;
                    border-radius: 6px;
                    background: transparent;
                    border: none;
                    color: #6b7280;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.15s;
                    flex-shrink: 0;
                    margin-left: auto;
                }
                
                .jive-history-item:hover .jive-history-delete { opacity: 1; }
                .jive-history-delete:hover { background: #374151; color: #ef4444; }
                .jive-history-delete svg { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 2; }
                
                /* Delete confirmation dialog */
                .jive-confirm-overlay {
                    position: fixed;
                    inset: 0;
                    background: rgba(0, 0, 0, 0.6);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 100001;
                    animation: fadeIn 0.15s ease-out;
                }
                
                @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
                
                .jive-confirm-dialog {
                    background: #1a1b1e;
                    border: 1px solid #3d3f46;
                    border-radius: 12px;
                    padding: 24px;
                    max-width: 320px;
                    width: 90%;
                    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
                    animation: slideUp 0.2s ease-out;
                }
                
                @keyframes slideUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
                
                .jive-confirm-icon {
                    width: 48px;
                    height: 48px;
                    background: rgba(239, 68, 68, 0.1);
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 16px;
                }
                
                .jive-confirm-icon svg { width: 24px; height: 24px; stroke: #ef4444; fill: none; stroke-width: 2; }
                
                .jive-confirm-title {
                    font-size: 16px;
                    font-weight: 600;
                    color: #f3f4f6;
                    text-align: center;
                    margin-bottom: 8px;
                }
                
                .jive-confirm-text {
                    font-size: 13px;
                    color: #9ca3af;
                    text-align: center;
                    margin-bottom: 20px;
                    line-height: 1.5;
                }
                
                .jive-confirm-buttons {
                    display: flex;
                    gap: 10px;
                }
                
                .jive-confirm-btn {
                    flex: 1;
                    padding: 10px 16px;
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.15s;
                    border: none;
                }
                
                .jive-confirm-btn.cancel {
                    background: #374151;
                    color: #e5e7eb;
                }
                
                .jive-confirm-btn.cancel:hover { background: #4b5563; }
                
                .jive-confirm-btn.delete {
                    background: #ef4444;
                    color: #fff;
                }
                
                .jive-confirm-btn.delete:hover { background: #dc2626; }
                
                .jive-history-empty {
                    text-align: center;
                    padding: 40px 16px;
                    color: #4b5563;
                }
                
                .jive-history-empty svg {
                    width: 40px;
                    height: 40px;
                    stroke: #374151;
                    fill: none;
                    stroke-width: 1.5;
                    margin-bottom: 12px;
                }
                
                .jive-history-empty p {
                    font-size: 13px;
                    margin: 0;
                }
                
                /* User Profile */
                .jive-user-section {
                    padding: 12px;
                    border-top: 1px solid #1f2937;
                }
                
                .jive-user-profile {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 10px 12px;
                    border-radius: 8px;
                    background: #1f2937;
                }
                
                .jive-user-avatar {
                    width: 32px;
                    height: 32px;
                    border-radius: 8px;
                    background: linear-gradient(135deg, #6366f1, #8b5cf6);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 14px;
                    font-weight: 600;
                    color: #fff;
                }
                
                .jive-user-info { flex: 1; min-width: 0; }
                .jive-user-name { display: block; font-size: 13px; font-weight: 500; color: #e5e7eb; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
                .jive-user-email { display: block; font-size: 11px; color: #6b7280; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
                
                /* Main Content */
                .jive-main {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    min-width: 0;
                }
                
                /* Header */
                .jive-header {
                    display: flex;
                    align-items: center;
                    justify-content: flex-end;
                    padding: 12px 20px;
                    border-bottom: 1px solid #1f2937;
                    background: #0a0a0b;
                }
                
                .jive-header-btn {
                    padding: 6px 12px;
                    background: transparent;
                    border: 1px solid #374151;
                    border-radius: 6px;
                    color: #9ca3af;
                    font-size: 12px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    transition: all 0.15s;
                    text-decoration: none;
                }
                
                .jive-header-btn:hover { background: #1f2937; color: #e5e7eb; }
                .jive-header-btn svg { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 2; }
                
                /* Chat Area */
                .jive-chat {
                    flex: 1;
                    overflow-y: auto;
                    padding: 24px;
                    display: flex;
                    flex-direction: column;
                }
                
                .jive-chat::-webkit-scrollbar { width: 6px; }
                .jive-chat::-webkit-scrollbar-track { background: transparent; }
                .jive-chat::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
                
                /* Welcome */
                .jive-welcome {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    padding: 40px;
                }
                
                .jive-welcome-icon {
                    width: 64px;
                    height: 64px;
                    background: linear-gradient(135deg, #6366f1, #8b5cf6);
                    border-radius: 16px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 32px;
                    font-weight: 700;
                    color: #fff;
                    margin-bottom: 20px;
                    box-shadow: 0 8px 32px rgba(99, 102, 241, 0.3);
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                }
                
                .jive-welcome-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 12px;
                    background: rgba(99, 102, 241, 0.1);
                    border: 1px solid rgba(99, 102, 241, 0.2);
                    border-radius: 20px;
                    font-size: 11px;
                    color: #818cf8;
                    margin-top: 24px;
                }
                
                .jive-welcome-badge svg {
                    width: 12px;
                    height: 12px;
                    stroke: currentColor;
                    fill: none;
                    stroke-width: 2;
                }
                
                .jive-welcome h1 {
                    font-size: 24px;
                    font-weight: 600;
                    color: #f9fafb;
                    margin-bottom: 8px;
                }
                
                .jive-welcome p {
                    color: #6b7280;
                    font-size: 14px;
                    max-width: 400px;
                    line-height: 1.5;
                }
                
                .jive-suggestions {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                    margin-top: 24px;
                    justify-content: center;
                    max-width: 600px;
                }
                
                .jive-suggestion {
                    padding: 8px 14px;
                    background: #1f2937;
                    border: 1px solid #374151;
                    border-radius: 8px;
                    color: #9ca3af;
                    font-size: 13px;
                    cursor: pointer;
                    transition: all 0.15s;
                }
                
                .jive-suggestion:hover { background: #374151; color: #e5e7eb; border-color: #4b5563; }
                
                /* Messages */
                .jive-messages {
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                    max-width: 800px;
                    width: 100%;
                    margin: 0 auto;
                }
                
                .jive-msg {
                    display: flex;
                    gap: 12px;
                    animation: msgIn 0.2s ease-out;
                }
                
                @keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
                
                .jive-msg-avatar {
                    width: 32px;
                    height: 32px;
                    border-radius: 8px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 14px;
                    flex-shrink: 0;
                }
                
                .jive-msg.user .jive-msg-avatar { background: #374151; color: #e5e7eb; }
                .jive-msg.assistant .jive-msg-avatar { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; }
                
                .jive-msg-content {
                    flex: 1;
                    padding-top: 4px;
                }
                
                .jive-msg-text {
                    font-size: 14px;
                    line-height: 1.6;
                    color: #e5e7eb;
                    white-space: pre-wrap;
                    word-break: break-word;
                }
                
                .jive-msg.user .jive-msg-text { color: #9ca3af; }
                
                .jive-msg-text code {
                    background: #1f2937;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 13px;
                    font-family: 'SF Mono', Monaco, monospace;
                }
                
                .jive-msg-text .jive-link {
                    color: #818cf8;
                    text-decoration: none;
                    border-bottom: 1px solid rgba(129, 140, 248, 0.3);
                    transition: all 0.15s;
                }
                
                .jive-msg-text .jive-link:hover {
                    color: #a5b4fc;
                    border-bottom-color: #a5b4fc;
                }
                
                .jive-msg-text pre {
                    background: #1f2937;
                    padding: 12px;
                    border-radius: 8px;
                    overflow-x: auto;
                    margin: 8px 0;
                }
                
                /* Feedback Styles */
                .jive-msg-feedback {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    margin-top: 8px;
                    opacity: 0.6;
                    transition: opacity 0.2s;
                }
                
                .jive-msg:hover .jive-msg-feedback {
                    opacity: 1;
                }
                
                .jive-feedback-btn {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 28px;
                    height: 28px;
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 6px;
                    color: #9ca3af;
                    cursor: pointer;
                    transition: all 0.15s;
                }
                
                .jive-feedback-btn:hover {
                    background: #1f2937;
                    color: #e5e7eb;
                }
                
                .jive-feedback-btn.active.like {
                    background: rgba(16, 185, 129, 0.1);
                    color: #10b981;
                    border-color: rgba(16, 185, 129, 0.2);
                }
                
                .jive-feedback-btn.active.dislike {
                    background: rgba(239, 68, 68, 0.1);
                    color: #ef4444;
                    border-color: rgba(239, 68, 68, 0.2);
                }

                .jive-feedback-btn.comment {
                    color: #60a5fa;
                }

                .jive-feedback-btn.comment:hover {
                    background: rgba(96, 165, 250, 0.12);
                    color: #93c5fd;
                }
                
                .jive-feedback-form {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    width: 100%;
                    max-width: 400px;
                }
                
                .jive-feedback-input {
                    flex: 1;
                    padding: 6px 10px;
                    border: 1px solid #374151;
                    border-radius: 6px;
                    background: #111214;
                    color: #e5e7eb;
                    font-size: 13px;
                }
                
                .jive-feedback-input:focus {
                    outline: none;
                    border-color: #6366f1;
                }
                
                .jive-feedback-submit, .jive-feedback-cancel {
                    padding: 6px 12px;
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: 500;
                    cursor: pointer;
                    border: none;
                }
                
                .jive-feedback-submit {
                    background: #6366f1;
                    color: #fff;
                }
                
                .jive-feedback-submit:hover {
                    background: #4f46e5;
                }
                
                .jive-feedback-cancel {
                    background: transparent;
                    color: #9ca3af;
                    border: 1px solid #374151;
                }
                
                .jive-feedback-cancel:hover {
                    background: #374151;
                    color: #e5e7eb;
                }
                
                .jive-feedback-thanks {
                    font-size: 13px;
                    color: #10b981;
                    font-weight: 500;
                    opacity: 1;
                }
                
                .jive.light .jive-msg-feedback { opacity: 0.8; }
                .jive.light .jive-feedback-btn { color: #6b7280; }
                .jive.light .jive-feedback-btn:hover { background: #e5e7eb; color: #111827; }
                .jive.light .jive-feedback-btn.active.like { background: rgba(5, 150, 105, 0.1); color: #059669; border-color: rgba(5, 150, 105, 0.2); }
                .jive.light .jive-feedback-btn.active.dislike { background: rgba(220, 38, 38, 0.1); color: #dc2626; border-color: rgba(220, 38, 38, 0.2); }
                
                /* GIF Display Styles */
                .jive-msg-gif {
                    margin-top: 12px;
                    background: #111214;
                    border: 1px solid #2d3748;
                    border-radius: 12px;
                    overflow: hidden;
                    max-width: 500px;
                }
                
                .jive-gif-header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 10px 14px;
                    background: linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(139, 92, 246, 0.1));
                    border-bottom: 1px solid #2d3748;
                    font-size: 12px;
                    color: #818cf8;
                    font-weight: 500;
                }
                
                .jive-gif-header svg {
                    flex-shrink: 0;
                }
                
                .jive-gif-image {
                    display: block;
                    width: 100%;
                    height: auto;
                    background: #0a0a0b;
                }
                
                .jive-gif-image:hover {
                    cursor: pointer;
                }
                
                /* ============ INLINE CHART STYLES ============ */
                .jive-inline-chart {
                    margin-top: 16px;
                    background: linear-gradient(145deg, #1a1b2e 0%, #111214 100%);
                    border: 1px solid #2d3748;
                    border-radius: 12px;
                    overflow: hidden;
                    max-width: 450px;
                }
                
                .jive-chart-header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 12px 16px;
                    background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(139, 92, 246, 0.1));
                    border-bottom: 1px solid #2d3748;
                }
                
                .jive-chart-icon {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 28px;
                    height: 28px;
                    background: linear-gradient(135deg, #6366f1, #8b5cf6);
                    border-radius: 6px;
                }
                
                .jive-chart-icon svg {
                    stroke: white;
                }
                
                .jive-chart-title {
                    flex: 1;
                    font-size: 13px;
                    font-weight: 600;
                    color: #e5e7eb;
                }
                
                .jive-chart-link {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 28px;
                    height: 28px;
                    background: rgba(99, 102, 241, 0.2);
                    border-radius: 6px;
                    color: #818cf8;
                    transition: all 0.2s;
                }
                
                .jive-chart-link:hover {
                    background: rgba(99, 102, 241, 0.4);
                    color: #a5b4fc;
                    transform: translateY(-1px);
                }
                
                .jive-chart-body {
                    padding: 16px;
                }
                
                /* Bar Chart Styles */
                .jive-bar-chart {
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                }
                
                .jive-bar-row {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }
                
                .jive-bar-label {
                    width: 80px;
                    font-size: 11px;
                    color: #9ca3af;
                    text-overflow: ellipsis;
                    overflow: hidden;
                    white-space: nowrap;
                    flex-shrink: 0;
                }
                
                .jive-bar-track {
                    flex: 1;
                    height: 18px;
                    background: rgba(55, 65, 81, 0.5);
                    border-radius: 4px;
                    overflow: hidden;
                }
                
                .jive-bar-fill {
                    height: 100%;
                    border-radius: 4px;
                    transition: width 0.5s ease-out;
                    min-width: 2px;
                }
                
                .jive-bar-value {
                    width: 60px;
                    font-size: 11px;
                    font-weight: 600;
                    color: #e5e7eb;
                    text-align: right;
                    flex-shrink: 0;
                }
                
                /* Donut Chart Styles */
                .jive-donut-chart {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                }
                
                .jive-donut-svg {
                    width: 100px;
                    height: 100px;
                    transform: rotate(-90deg);
                    flex-shrink: 0;
                }
                
                .jive-donut-legend {
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                    flex: 1;
                }
                
                .jive-legend-item {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 11px;
                }
                
                .jive-legend-dot {
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                
                .jive-legend-label {
                    flex: 1;
                    color: #9ca3af;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                
                .jive-legend-value {
                    color: #e5e7eb;
                    font-weight: 600;
                }
                
                /* Number Chart Styles */
                .jive-inline-number {
                    text-align: center;
                    padding: 12px;
                }
                
                .jive-number-value {
                    font-size: 32px;
                    font-weight: 700;
                    background: linear-gradient(135deg, #6366f1, #a855f7);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    background-clip: text;
                }
                
                .jive-number-label {
                    font-size: 12px;
                    color: #9ca3af;
                    margin-top: 4px;
                }
                
                /* ============ LIGHT THEME OVERRIDES ============ */
                .jive.light { background: #ffffff; color: #111827; }
                .jive.light .jive-sidebar { background: #f9fafb; border-right-color: #e5e7eb; }
                .jive.light .jive-sidebar-header { border-bottom-color: #e5e7eb; }
                .jive.light .jive-title { color: #111827; }
                .jive.light .jive-subtitle { color: #6b7280; }
                .jive.light .jive-new-btn { background: #e5e7eb; border-color: #d1d5db; color: #4b5563; }
                .jive.light .jive-new-btn:hover { background: #d1d5db; color: #111827; }
                .jive.light .jive-history::-webkit-scrollbar-thumb { background: #d1d5db; }
                .jive.light .jive-history-title { color: #6b7280; }
                .jive.light .jive-history-item { color: #374151; }
                .jive.light .jive-history-item:hover { background: #f3f4f6; }
                .jive.light .jive-history-item.active { background: #e0e7ff; border-left-color: #4f46e5; }
                .jive.light .jive-history-icon { background: #e5e7eb; }
                .jive.light .jive-history-text { color: #111827; }
                .jive.light .jive-history-meta { color: #6b7280; }
                .jive.light .jive-history-empty { color: #6b7280; }
                .jive.light .jive-history-empty svg { stroke: #d1d5db; }
                .jive.light .jive-history-delete-btn { color: #6b7280; }
                .jive.light .jive-history-delete-btn:hover { color: #dc2626; background: rgba(220, 38, 38, 0.1); }
                .jive.light .jive-user-section { border-top-color: #e5e7eb; }
                .jive.light .jive-user-profile { background: #f3f4f6; }
                .jive.light .jive-user-name { color: #111827; }
                .jive.light .jive-user-email { color: #6b7280; }
                .jive.light .jive-main { background: #ffffff; }
                .jive.light .jive-header { background: #ffffff; border-bottom-color: #e5e7eb; }
                .jive.light .jive-header-btn { border-color: #d1d5db; color: #4b5563; }
                .jive.light .jive-header-btn:hover { background: #f3f4f6; color: #111827; }
                .jive.light .jive-chat { background: #ffffff; }
                .jive.light .jive-chat::-webkit-scrollbar-thumb { background: #d1d5db; }
                .jive.light .jive-welcome h1 { color: #111827; }
                .jive.light .jive-welcome p { color: #6b7280; }
                .jive.light .jive-suggestion { background: #f3f4f6; border-color: #e5e7eb; color: #4b5563; }
                .jive.light .jive-suggestion:hover { background: #e5e7eb; color: #111827; border-color: #d1d5db; }
                .jive.light .jive-msg.user .jive-msg-avatar { background: #e5e7eb; color: #374151; }
                .jive.light .jive-msg.user .jive-msg-text { color: #4b5563; }
                .jive.light .jive-msg-text { color: #111827; }
                .jive.light .jive-msg-text code { background: #f3f4f6; }
                .jive.light .jive-msg-text .jive-link { color: #4f46e5; border-bottom-color: rgba(79, 70, 229, 0.3); }
                .jive.light .jive-msg-text .jive-link:hover { color: #6366f1; border-bottom-color: #6366f1; }
                .jive.light .jive-msg-text pre { background: #f3f4f6; }
                .jive.light .jive-msg-gif { background: #f9fafb; border-color: #e5e7eb; }
                .jive.light .jive-gif-header { background: linear-gradient(135deg, rgba(79, 70, 229, 0.1), rgba(124, 58, 237, 0.1)); border-bottom-color: #e5e7eb; color: #4f46e5; }
                .jive.light .jive-inline-chart { background: linear-gradient(145deg, #f9fafb 0%, #ffffff 100%); border-color: #e5e7eb; }
                .jive.light .jive-chart-header { background: linear-gradient(135deg, rgba(79, 70, 229, 0.1), rgba(124, 58, 237, 0.05)); border-bottom-color: #e5e7eb; }
                .jive.light .jive-chart-title { color: #111827; }
                .jive.light .jive-chart-link { background: rgba(79, 70, 229, 0.1); color: #4f46e5; }
                .jive.light .jive-chart-link:hover { background: rgba(79, 70, 229, 0.2); color: #4338ca; }
                .jive.light .jive-bar-label { color: #4b5563; }
                .jive.light .jive-bar-track { background: #e5e7eb; }
                .jive.light .jive-bar-value { color: #111827; }
                .jive.light .jive-legend-label { color: #4b5563; }
                .jive.light .jive-legend-value { color: #111827; }
                .jive.light .jive-number-label { color: #6b7280; }
                .jive.light .jive-gif-image { background: #f3f4f6; }
                .jive.light .jive-status-spinner { border-color: #e5e7eb; border-top-color: #4f46e5; }
                .jive.light .jive-status-text { color: #6b7280; }
                .jive.light .jive-input-area { background: #ffffff; }
                .jive.light .jive-input-box { background: #f9fafb; border-color: #e5e7eb; }
                .jive.light .jive-input-box:focus-within { border-color: #a5b4fc; }
                .jive.light .jive-input-top { border-bottom-color: #e5e7eb; }
                .jive.light .jive-mode-btn { background: #f3f4f6; border-color: #d1d5db; color: #111827; }
                .jive.light .jive-mode-btn:hover { background: #e5e7eb; }
                .jive.light .jive-mode-btn .arrow { color: #6b7280; }
                .jive.light .jive-mode-dropdown { background: #ffffff; border-color: #e5e7eb; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }
                .jive.light .jive-mode-option:hover { background: #f3f4f6; }
                .jive.light .jive-mode-option.active { background: #e0e7ff; }
                .jive.light .jive-mode-option .info strong { color: #111827; }
                .jive.light .jive-mode-option .info span { color: #6b7280; }
                .jive.light .jive-model-badge { background: #f3f4f6; color: #4b5563; }
                .jive.light .jive-context-toggle { background: #f3f4f6; color: #4b5563; border-color: #d1d5db; }
                .jive.light .jive-context-toggle:hover { background: #e5e7eb; }
                .jive.light .jive-context-toggle input { accent-color: #4f46e5; }
                .jive.light .jive-doctypes-info { background: #f3f4f6; color: #6b7280; }
                .jive.light #jiveInput { color: #111827; }
                .jive.light #jiveInput::placeholder { color: #9ca3af; }
                .jive.light .jive-action-btn { color: #6b7280; }
                .jive.light .jive-action-btn:hover { background: #f3f4f6; color: #111827; }
                .jive.light .jive-action-btn.active { background: #fee2e2; color: #dc2626; }
                .jive.light .jive-send-btn { background: linear-gradient(135deg, #4f46e5, #6366f1); }
                .jive.light .jive-context-bar { background: rgba(79, 70, 229, 0.1); border-color: rgba(79, 70, 229, 0.2); color: #4f46e5; }
                .jive.light .jive-plan-approval { background: #f9fafb; border-color: #e5e7eb; }
                .jive.light .jive-plan-header { color: #111827; border-bottom-color: #e5e7eb; }
                .jive.light .jive-plan-action { background: #ffffff; border-color: #e5e7eb; }
                .jive.light .jive-plan-action-doctype { color: #111827; }
                .jive.light .jive-plan-action-desc { color: #6b7280; }
                .jive.light .jive-plan-action-data { background: #f3f4f6; }
                .jive.light .jive-plan-data-key { color: #4f46e5; }
                .jive.light .jive-plan-data-value { color: #374151; }
                .jive.light .jive-plan-warning { background: rgba(217, 119, 6, 0.1); border-color: rgba(217, 119, 6, 0.2); color: #d97706; }
                .jive.light .jive-plan-btn.reject { background: #f3f4f6; color: #6b7280; }
                .jive.light .jive-plan-btn.reject:hover { background: #fee2e2; color: #dc2626; }
                .jive.light .jive-plan-executing { color: #4f46e5; }
                .jive.light .jive-plan-spinner { border-color: #e5e7eb; border-top-color: #4f46e5; }
                .jive.light .jive-confirm-overlay { background: rgba(0, 0, 0, 0.4); }
                .jive.light .jive-confirm-dialog { background: #ffffff; border-color: #e5e7eb; }
                .jive.light .jive-confirm-title { color: #111827; }
                .jive.light .jive-confirm-text { color: #6b7280; }
                .jive.light .jive-confirm-btn.cancel { background: #f3f4f6; color: #4b5563; }
                .jive.light .jive-confirm-btn.cancel:hover { background: #e5e7eb; }
                /* ============ END LIGHT THEME ============ */
                
                .jive-typing {
                    display: flex;
                    gap: 4px;
                    padding: 8px 0;
                }
                
                .jive-typing span {
                    width: 6px;
                    height: 6px;
                    background: #6366f1;
                    border-radius: 50%;
                    animation: typing 1.4s ease-in-out infinite;
                }
                
                .jive-typing span:nth-child(2) { animation-delay: 0.2s; }
                .jive-typing span:nth-child(3) { animation-delay: 0.4s; }
                
                @keyframes typing { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-4px); } }
                
                /* Status Indicator */
                .jive-status-indicator {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 8px 0;
                }
                
                .jive-status-spinner {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #374151;
                    border-top-color: #818cf8;
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                }
                
                @keyframes spin { to { transform: rotate(360deg); } }
                
                .jive-status-text {
                    font-size: 13px;
                    color: #9ca3af;
                    animation: pulse 2s ease-in-out infinite;
                }
                
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.6; }
                }
                
                /* Plan Approval UI */
                .jive-plan-approval {
                    background: #111214;
                    border: 1px solid #2d3748;
                    border-radius: 12px;
                    padding: 16px;
                    margin-top: 12px;
                    animation: fadeIn 0.3s ease;
                }
                
                @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
                
                .jive-plan-header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    color: #f0f0f0;
                    font-weight: 600;
                    font-size: 14px;
                    margin-bottom: 12px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid #2d3748;
                }
                
                .jive-plan-header svg { color: #10b981; }
                
                .jive-plan-actions {
                    display: flex;
                    flex-direction: column;
                    gap: 10px;
                    margin-bottom: 12px;
                }
                
                .jive-plan-action {
                    background: #1a1b1e;
                    border: 1px solid #2d3748;
                    border-radius: 8px;
                    padding: 12px;
                }
                
                .jive-plan-action-header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 6px;
                }
                
                .jive-plan-action-badge {
                    font-size: 10px;
                    font-weight: 600;
                    padding: 2px 8px;
                    border-radius: 4px;
                    text-transform: uppercase;
                }
                
                .jive-plan-action-badge.create { background: #065f46; color: #34d399; }
                .jive-plan-action-badge.update { background: #1e40af; color: #60a5fa; }
                .jive-plan-action-badge.submit { background: #7c2d12; color: #fb923c; }
                .jive-plan-action-badge.cancel { background: #7f1d1d; color: #f87171; }
                
                .jive-plan-action-doctype {
                    font-size: 13px;
                    font-weight: 500;
                    color: #e5e7eb;
                }
                
                .jive-plan-action-desc {
                    font-size: 12px;
                    color: #9ca3af;
                    margin-bottom: 8px;
                }
                
                .jive-plan-action-data {
                    background: #0d0e10;
                    border-radius: 6px;
                    padding: 10px;
                    font-size: 12px;
                }
                
                .jive-plan-data-title {
                    color: #6b7280;
                    font-size: 11px;
                    margin-bottom: 6px;
                    font-weight: 500;
                }
                
                .jive-plan-data-item {
                    display: flex;
                    gap: 8px;
                    padding: 2px 0;
                    align-items: flex-start;
                }
                
                .jive-plan-data-key {
                    color: #818cf8;
                    min-width: 100px;
                }
                
                .jive-plan-data-value {
                    color: #d1d5db;
                    flex: 1;
                    white-space: pre-wrap;
                    word-break: break-word;
                }
                
                .jive-plan-data-more {
                    color: #6b7280;
                    font-style: italic;
                    margin-top: 4px;
                }
                
                .jive-plan-warning {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 10px 12px;
                    background: rgba(251, 191, 36, 0.1);
                    border: 1px solid rgba(251, 191, 36, 0.2);
                    border-radius: 8px;
                    font-size: 12px;
                    color: #fbbf24;
                    margin-bottom: 12px;
                }
                
                .jive-plan-buttons {
                    display: flex;
                    gap: 10px;
                    justify-content: flex-end;
                }
                
                .jive-plan-btn {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 8px 16px;
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.15s;
                    border: none;
                }
                
                .jive-plan-btn.reject {
                    background: #1f2937;
                    color: #9ca3af;
                }
                
                .jive-plan-btn.reject:hover {
                    background: #374151;
                    color: #f87171;
                }
                
                .jive-plan-btn.approve {
                    background: linear-gradient(135deg, #059669, #10b981);
                    color: white;
                }
                
                .jive-plan-btn.approve:hover {
                    background: linear-gradient(135deg, #047857, #059669);
                    transform: translateY(-1px);
                }
                
                .jive-plan-executing {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 12px;
                    padding: 20px;
                    color: #818cf8;
                    font-size: 14px;
                }
                
                .jive-plan-spinner {
                    width: 20px;
                    height: 20px;
                    border: 2px solid #374151;
                    border-top-color: #818cf8;
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                }
                
                @keyframes spin { to { transform: rotate(360deg); } }
                
                /* Input Area */
                .jive-input-area {
                    padding: 16px 20px 20px;
                    background: #0a0a0b;
                }
                
                .jive-input-container {
                    max-width: 800px;
                    margin: 0 auto;
                }
                
                /* Context Indicator */
                .jive-context-bar {
                    display: none;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 12px;
                    margin-bottom: 8px;
                    background: rgba(99, 102, 241, 0.1);
                    border: 1px solid rgba(99, 102, 241, 0.2);
                    border-radius: 8px;
                    font-size: 12px;
                    color: #818cf8;
                }
                
                .jive-context-bar.visible { display: flex; }
                .jive-context-bar svg { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 2; }
                .jive-context-bar span { flex: 1; }
                .jive-context-clear { background: none; border: none; color: #6b7280; cursor: pointer; font-size: 16px; padding: 0 4px; }
                .jive-context-clear:hover { color: #ef4444; }
                
                /* Main Input Box */
                .jive-input-box {
                    background: #111214;
                    border: 1px solid #2d2f36;
                    border-radius: 12px;
                    transition: all 0.15s;
                }
                
                .jive-input-box:focus-within { border-color: #4b5563; }
                
                .jive-input-top {
                    display: flex;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 8px;
                    padding: 10px 12px;
                    border-bottom: 1px solid #2d2f36;
                }
                
                /* Mode Selector */
                .jive-mode-select {
                    position: relative;
                }
                
                .jive-mode-btn {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 5px 10px;
                    background: #1f2023;
                    border: 1px solid #3d3f46;
                    border-radius: 6px;
                    color: #e5e7eb;
                    font-size: 12px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.15s;
                }
                
                .jive-mode-btn:hover { background: #2d2f36; }
                
                .jive-mode-btn .icon {
                    width: 18px;
                    height: 18px;
                    border-radius: 5px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 10px;
                    color: #fff;
                }
                
                .jive-mode-btn .arrow { font-size: 10px; color: #6b7280; margin-left: 2px; }
                
                .jive-mode-dropdown {
                    position: absolute;
                    bottom: calc(100% + 4px);
                    left: 0;
                    background: #1a1b1e;
                    border: 1px solid #3d3f46;
                    border-radius: 8px;
                    padding: 4px;
                    min-width: 200px;
                    max-height: 320px;
                    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
                    display: none;
                    z-index: 100;
                    overflow-y: auto;
                }
                
                .jive-mode-dropdown.open { display: block; }
                
                .jive-mode-option {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    padding: 10px 12px;
                    border-radius: 6px;
                    cursor: pointer;
                    transition: all 0.1s;
                }
                
                .jive-mode-option:hover { background: #2d2f36; }
                .jive-mode-option.active { background: #2d2f36; }
                
                .jive-mode-option .icon {
                    width: 28px;
                    height: 28px;
                    border-radius: 6px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 12px;
                    color: #fff;
                }
                
                .jive-mode-option .info { flex: 1; }
                .jive-mode-option .info strong { display: block; font-size: 13px; color: #e5e7eb; font-weight: 500; }
                .jive-mode-option .info span { font-size: 11px; color: #6b7280; }
                
                /* Model Badge */
                .jive-model-badge {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 4px 10px;
                    background: #1f2937;
                    border-radius: 6px;
                    color: #9ca3af;
                    font-size: 11px;
                }
                
                .jive-model-badge::before {
                    content: '';
                    width: 6px;
                    height: 6px;
                    background: #10b981;
                    border-radius: 50%;
                }

                .jive-context-toggle {
                    display: inline-flex;
                    align-items: center;
                    gap: 8px;
                    padding: 4px 10px;
                    background: #1f2937;
                    border: 1px solid #374151;
                    border-radius: 6px;
                    color: #9ca3af;
                    font-size: 11px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.15s;
                    user-select: none;
                }

                .jive-context-toggle:hover {
                    background: #2d2f36;
                    color: #e5e7eb;
                }

                .jive-context-toggle input {
                    width: 14px;
                    height: 14px;
                    margin: 0;
                    accent-color: #818cf8;
                    cursor: pointer;
                    flex-shrink: 0;
                }

                .jive-context-toggle span {
                    white-space: nowrap;
                }
                
                /* Doctypes */
                .jive-doctypes-info {
                    margin-left: auto;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 11px;
                    color: #6b7280;
                    padding: 4px 10px;
                    background: #1f2937;
                    border-radius: 6px;
                }
                
                .jive-doctypes-info svg { width: 12px; height: 12px; stroke: currentColor; fill: none; stroke-width: 2; }
                
                /* Textarea */
                .jive-input-main {
                    display: flex;
                    align-items: flex-end;
                    gap: 8px;
                    padding: 10px 12px;
                }
                
                #jiveInput {
                    flex: 1;
                    background: transparent;
                    border: none;
                    color: #e5e7eb;
                    font-size: 14px;
                    font-family: inherit;
                    resize: none;
                    max-height: 150px;
                    line-height: 1.5;
                    padding: 4px 0;
                }
                
                #jiveInput::placeholder { color: #4b5563; }
                #jiveInput:focus { outline: none; }
                
                /* Action Buttons */
                .jive-input-actions {
                    display: flex;
                    align-items: center;
                    gap: 4px;
                }
                
                .jive-action-btn {
                    width: 32px;
                    height: 32px;
                    border-radius: 6px;
                    border: none;
                    background: transparent;
                    color: #6b7280;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.15s;
                }
                
                .jive-action-btn:hover { background: #2d2f36; color: #e5e7eb; }
                .jive-action-btn svg { width: 18px; height: 18px; stroke: currentColor; fill: none; stroke-width: 1.5; }
                
                .jive-action-btn.active { background: #ef4444; color: #fff; }
                .jive-action-btn.active:hover { background: #dc2626; }
                
                .jive-send-btn {
                    width: 32px;
                    height: 32px;
                    border-radius: 6px;
                    border: none;
                    background: #6366f1;
                    color: #fff;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.15s;
                }
                
                .jive-send-btn:hover { background: #4f46e5; }
                .jive-send-btn:disabled { background: #374151; cursor: not-allowed; }
                .jive-send-btn svg { width: 16px; height: 16px; fill: currentColor; }
                
                /* Footer hint */
                .jive-footer-hint {
                    text-align: center;
                    padding-top: 12px;
                    font-size: 11px;
                    color: #4b5563;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 6px;
                }
                
                .jive-footer-hint a { 
                    color: #818cf8; 
                    text-decoration: none; 
                    font-weight: 500;
                    display: inline-flex;
                    align-items: center;
                    gap: 4px;
                }
                .jive-footer-hint a:hover { color: #a5b4fc; }
                
                .jive-footer-logo {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 14px;
                    height: 14px;
                    background: linear-gradient(135deg, #6366f1, #8b5cf6);
                    border-radius: 3px;
                    font-size: 8px;
                    color: #fff;
                }
                
                /* Token Usage Styles */
                .jive-usage-section {
                    padding: 12px 16px;
                    border-top: 1px solid #2d3748;
                }
                
                .jive-usage-title {
                    font-size: 11px;
                    text-transform: uppercase;
                    color: #9ca3af;
                    margin-bottom: 8px;
                    font-weight: 600;
                    letter-spacing: 0.5px;
                    display: flex;
                    justify-content: space-between;
                }
                
                .jive-usage-item {
                    margin-bottom: 8px;
                }
                
                .jive-usage-label {
                    display: flex;
                    justify-content: space-between;
                    font-size: 11px;
                    color: #d1d5db;
                    margin-bottom: 4px;
                }
                
                .jive-usage-bar {
                    height: 6px;
                    background: #374151;
                    border-radius: 3px;
                    overflow: hidden;
                }
                
                .jive-usage-fill {
                    height: 100%;
                    border-radius: 3px;
                    transition: width 0.5s ease;
                }
                
                .jive-usage-fill.green { background: #10b981; }
                .jive-usage-fill.yellow { background: #f59e0b; }
                .jive-usage-fill.red { background: #ef4444; }
                
                .jive.light .jive-usage-section { border-top-color: #e5e7eb; }
                .jive.light .jive-usage-title { color: #6b7280; }
                .jive.light .jive-usage-label { color: #374151; }
                .jive.light .jive-usage-bar { background: #e5e7eb; }
                
                /* Hidden file input */
                #contextFileInput { display: none; }
            </style>
            
            <div class="jive ${this.theme === 'light' ? 'light' : ''}" id="jiveContainer">
                <!-- Sidebar -->
                <aside class="jive-sidebar">
                    <div class="jive-sidebar-header">
                        <div class="jive-brand">
                            <div class="jive-logo">A</div>
                            <div class="jive-brand-text">
                                <span class="jive-title">Jive</span>
                                <span class="jive-subtitle">by Ambibuzz</span>
                            </div>
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <button class="jive-new-btn" onclick="jiveChat.newChat()" title="New chat">
                                <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                            </button>
                            <button class="jive-new-btn" onclick="this.closest('.jive').querySelector('.jive-sidebar').classList.remove('open')" title="Close history">
                                <svg viewBox="0 0 24 24"><line stroke="currentColor" stroke-width="2" x1="18" y1="6" x2="6" y2="18"/><line stroke="currentColor" stroke-width="2" x1="6" y1="6" x2="18" y2="18"/></svg>
                            </button>
                        </div>
                    </div>
                    
                    <!-- Chat History -->
                    <div class="jive-history" id="historyList">
                        <div class="jive-history-title">
                            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                            Recent Chats
                        </div>
                        <div class="jive-history-empty">
                            <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                            <p>No conversations yet</p>
                            <p style="font-size:11px;margin-top:4px;">Start a new chat to begin</p>
                        </div>
                    </div>
                    

                    
                    <!-- Token Usage -->
                    <div id="tokenUsageDisplay">
                        ${this.getUsageInfo()}
                    </div>
                    
                    <!-- User Profile -->
                    <div class="jive-user-section">
                        <div class="jive-user-profile">
                            <div class="jive-user-avatar">${user.charAt(0).toUpperCase()}</div>
                            <div class="jive-user-info">
                                <span class="jive-user-name">${this.esc(user)}</span>
                                <span class="jive-user-email">${this.esc(userEmail)}</span>
                            </div>
                        </div>
                    </div>
                </aside>
                
                <!-- Main Content -->
                <main class="jive-main">
                    <header class="jive-header">
                        <button class="jive-header-btn" onclick="this.closest('.jive').querySelector('.jive-sidebar').classList.toggle('open')" title="Toggle History" style="margin-right: auto;">
                            <svg viewBox="0 0 24 24"><line stroke="currentColor" stroke-width="2" x1="3" y1="12" x2="21" y2="12"/><line stroke="currentColor" stroke-width="2" x1="3" y1="6" x2="21" y2="6"/><line stroke="currentColor" stroke-width="2" x1="3" y1="18" x2="21" y2="18"/></svg>
                            History
                        </button>
                        <button class="jive-header-btn jive-theme-toggle" onclick="jiveChat.toggleTheme()" title="Toggle theme">
                            ${this.theme === 'dark' ? `
                                <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                                Light
                            ` : `
                                <svg viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
                                Dark
                            `}
                        </button>
                        <a href="/app/jive-config" class="jive-header-btn" title="Settings">
                            <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                            Settings
                        </a>
                        <button class="jive-header-btn jive-maximize-btn" onclick="window.toggleMaximizeJiveChat && window.toggleMaximizeJiveChat()" title="Maximize" style="margin-left: 4px; border-color: transparent; padding: 6px;">
                            <svg viewBox="0 0 24 24"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
                        </button>
                        <button class="jive-header-btn" onclick="window.toggleJiveChat && window.toggleJiveChat()" title="Close chat" style="margin-left: 4px; border-color: transparent; padding: 6px;">
                            <svg viewBox="0 0 24 24"><line stroke="currentColor" stroke-width="2" x1="18" y1="6" x2="6" y2="18"/><line stroke="currentColor" stroke-width="2" x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                    </header>
                    
                    <div class="jive-chat" id="chatArea">
                        ${this.getWelcome()}
                    </div>
                    
                    <div class="jive-input-area">
                        <div class="jive-input-container">
                            <div class="jive-context-bar" id="contextBar">
                                <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                                <span id="contextInfo">0 files loaded</span>
                                <button class="jive-context-clear" onclick="jiveChat.clearContext()">×</button>
                            </div>
                            
                            <div class="jive-input-box">
                                <div class="jive-input-top">
                                    <!-- Mode Selector Dropdown -->
                                    <div class="jive-mode-select">
                                        <button class="jive-mode-btn" onclick="jiveChat.toggleModeDropdown()">
                                            <span class="icon" style="background:${m.color}">${m.icon}</span>
                                            ${m.label}
                                            <span class="arrow">▾</span>
                                        </button>
                                        <div class="jive-mode-dropdown" id="modeDropdown">
                                            ${modes.map((mode) => `
                                            <div class="jive-mode-option ${this.normalizeMode(this.currentMode) === mode.agent_key ? 'active' : ''}" data-mode="${mode.agent_key}">
                                                <span class="icon" style="background:${mode.color}">${mode.icon}</span>
                                                <div class="info"><strong>${mode.label}</strong><span>${mode.hint || 'Open this mode'}</span></div>
                                            </div>
                                            `).join('')}
                                        </div>
                                    </div>
                                    
                                    <div class="jive-model-badge">${model}</div>
                                    ${this.getModeAuxiliaryControls(m)}

                                    ${m.supports_context ? `
                                    <label class="jive-context-toggle" title="Use the currently open page as context for this mode">
                                        <input type="checkbox" id="contextAwareToggle" ${this.contextAware ? 'checked' : ''} onchange="jiveChat.toggleContextAware(this.checked)">
                                        <span>Context aware</span>
                                    </label>
                                    ` : ''}
                                    
                                    ${m.supports_context && m.agent_key !== 'helpdesk' && m.agent_key !== 'rag' && doctypes.length > 0 ? `
                                    <div class="jive-doctypes-info" title="${doctypes.join(', ')}">
                                        <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                                        ${doctypes.length} source${doctypes.length > 1 ? 's' : ''}
                                    </div>
                                    ` : ''}
                                </div>
                                
                                <div class="jive-input-main">
                                    <textarea id="jiveInput" placeholder="${m.hint}..." rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();jiveChat.send()}" oninput="jiveChat.autoResize(this)"></textarea>
                                    
                                    <div class="jive-input-actions">
                                        ${m.supports_upload && enableUpload ? `
                                        <label class="jive-action-btn" title="Upload context file">
                                            <input type="file" id="contextFileInput" accept=".pdf,.docx,.doc,.csv,.txt,.md,.json" onchange="jiveChat.uploadContext(event)"/>
                                            <svg viewBox="0 0 24 24"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                                        </label>
                                        ` : ''}
                                        
                                        ${enableVoice ? `
                                        <button class="jive-action-btn ${this.isRecording ? 'active' : ''}" id="voiceBtn" onclick="jiveChat.toggleVoice()" title="Voice input">
                                            <svg viewBox="0 0 24 24"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/></svg>
                                        </button>
                                        ` : ''}
                                        
                                        <button class="jive-send-btn" onclick="jiveChat.send()" title="Send">
                                            <svg viewBox="0 0 24 24"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
                                        </button>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="jive-footer-hint">
                                <span>Powered by</span>
                                <a href="https://ambibuzz.com" target="_blank" title="Visit Ambibuzz">
                                    <span class="jive-footer-logo">A</span>
                                    Ambibuzz
                                </a>
                            </div>
                        </div>
                    </div>
                </main>
            </div>
        `;

        this.updateContextBar();
    }

    getWelcome() {
        const welcomeTitle = this.config?.welcome_title || 'What would you like to know?';
        const welcomeMessage = this.config?.welcome_message || '';
        const showSuggestions = this.config?.show_suggestions !== false;

        const currentView = this.getDisplayContext();
        const currentLabel = currentView.label && currentView.label !== 'current view' ? currentView.label : 'the page you are viewing';
        const mode = this.getModeMeta(this.currentMode);
        const modeWelcome = {
            query: this.contextAware
                ? { title: 'What would you like to explore?', desc: 'Ask questions about ' + currentLabel, suggestions: ['Summarize this page', 'Explain the important fields', 'What stands out here?'] }
                : { title: welcomeTitle, desc: welcomeMessage || 'Ask questions about your ERPNext data', suggestions: ['Show recent Sales Invoices', 'Total revenue this month', 'List pending orders'] },
            helpdesk: { title: 'How can I help?', desc: 'Get guidance on ERPNext features and workflows', suggestions: ['How to create a Sales Invoice?', 'Setup user permissions', 'Stock reconciliation process'] },
            hd_tickets: { title: 'Which tickets should I check?', desc: 'Ask about ticket status, lists, updates, and customer activity', suggestions: ['Show my open tickets', 'Create a ticket'] },
            agent: { title: 'What should I do?', desc: 'I can create, update, and manage documents for you', suggestions: ['Create a new Item', 'Update customer details', 'Submit pending invoices'] },
            insights: { title: 'What would you like to visualize?', desc: 'Create charts, dashboards, and reports in Frappe Insights', suggestions: ['Create a sales chart by month', 'Show revenue by customer', 'Build a dashboard for orders'] },
            rag: { title: 'What should I look up?', desc: 'Ask questions about your uploaded documents', suggestions: ['Summarize the attached documents', 'Find the policy about approvals', 'What does the knowledge base say?'] }
        };
        const w = modeWelcome[mode.agent_key] || {
            title: mode.label || welcomeTitle,
            desc: mode.hint || welcomeMessage || 'Ask a question to get started',
            suggestions: mode.agent_key ? [`Ask the ${mode.label || mode.agent_key} agent`, `What can ${mode.label || mode.agent_key} do?`, `Give me an example`] : []
        };

        return `
            <div class="jive-welcome">
                <div class="jive-welcome-icon">A</div>
                <h1>${w.title}</h1>
                <p>${w.desc}</p>
                ${showSuggestions ? `
                <div class="jive-suggestions">
                    ${w.suggestions.map(s => `<button class="jive-suggestion" onclick="jiveChat.useSuggestion('${this.esc(s)}')">${s}</button>`).join('')}
                </div>
                ` : ''}
                <div class="jive-welcome-badge">
                    <svg viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
                    Built by Ambibuzz Technologies
                </div>
            </div>
        `;
    }

    getUsageInfo() {
        if (!this.config || !this.config.use_jive_core || !this.config.token_usage) return '';
        const u = this.config.token_usage;

        const renderBar = (label, data) => {
            if (!data || data.unlimited) return '';
            const limit = data.limit || 0;
            const current = data.current || 0;
            if (limit <= 0) return '';

            const pct = Math.min((current / limit) * 100, 100);
            let color = 'green';
            if (pct >= 90) color = 'red';
            else if (pct >= 70) color = 'yellow';

            const formatNum = (n) => {
                if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
                return n;
            };

            return `
                <div class="jive-usage-item">
                    <div class="jive-usage-label">
                        <span>${label}</span>
                        <span>${formatNum(current)} / ${formatNum(limit)}</span>
                    </div>
                    <div class="jive-usage-bar" title="${pct.toFixed(1)}%">
                        <div class="jive-usage-fill ${color}" style="width: ${pct}%"></div>
                    </div>
                </div>
            `;
        };

        const dailyHtml = renderBar('Daily Usage', u.daily);
        const monthlyHtml = renderBar('Monthly Usage', u.monthly);

        if (!dailyHtml && !monthlyHtml) return '';

        return `
            <div class="jive-usage-section">
                <div class="jive-usage-title">
                    <span>Token Usage</span>
                </div>
                ${dailyHtml}
                ${monthlyHtml}
            </div>
        `;
    }

    getModeAuxiliaryControls(mode) {
        return '';
    }

    updateUsageDisplay() {
        const el = document.getElementById('tokenUsageDisplay');
        if (el) {
            el.innerHTML = this.getUsageInfo();
        }
    }









    bindEvents() {
        // Mode dropdown options
        document.querySelectorAll('.jive-mode-option').forEach(opt => {
            opt.addEventListener('click', () => {
                this.switchMode(opt.dataset.mode);
                this.closeModeDropdown();
            });
        });

        // Close dropdown on outside click
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.jive-mode-select')) {
                this.closeModeDropdown();
            }
        });
    }

    toggleModeDropdown() {
        const dropdown = document.getElementById('modeDropdown');
        if (dropdown) {
            this.modeOpen = !this.modeOpen;
            dropdown.classList.toggle('open', this.modeOpen);
        }
    }

    closeModeDropdown() {
        const dropdown = document.getElementById('modeDropdown');
        if (dropdown) {
            this.modeOpen = false;
            dropdown.classList.remove('open');
        }
    }

    toggleTheme() {
        this.theme = this.theme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('jive_theme', this.theme);

        const container = document.getElementById('jiveContainer');
        if (container) {
            container.classList.toggle('light', this.theme === 'light');
        }

        // Update the theme toggle button
        const toggleBtn = document.querySelector('.jive-theme-toggle');
        if (toggleBtn) {
            toggleBtn.innerHTML = this.theme === 'dark' ? `
                <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                Light
            ` : `
                <svg viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
                Dark
            `;
        }
    }

    switchMode(mode) {
        mode = this.normalizeMode(mode);
        if (mode === 'context') {
            this.contextAware = true;
            localStorage.setItem('jive_context_aware', '1');
            mode = 'query';
            const checkbox = document.getElementById('contextAwareToggle');
            if (checkbox) checkbox.checked = true;
            if (this.currentMode === mode) {
                this.updateContextBar();
                if (!this.conversationId && (!this.messages || this.messages.length === 0)) {
                    const chatArea = document.getElementById('chatArea');
                    if (chatArea) {
                        chatArea.innerHTML = this.getWelcome();
                    }
                }
                return;
            }
        }
        if (!this.isModeAllowed(mode)) return;

        const targetMeta = this.getModeMeta(mode);
        const currentMeta = this.getModeMeta(this.currentMode);

        if (!targetMeta.supports_context) {
            this.queryContextAwarePreference = this.contextAware;
            this.contextAware = false;
        } else if (!currentMeta.supports_context && targetMeta.supports_context) {
            const stored = localStorage.getItem('jive_context_aware');
            this.contextAware = stored === null ? true : stored === '1';
            this.queryContextAwarePreference = this.contextAware;
        }
        if (this.currentMode === mode) return;
        this.currentMode = mode;
        this.render();
        this.bindEvents();

        // Restore messages if there's an active conversation
        if (this.messages && this.messages.length > 0) {
            this.renderMessages();
        }

        this.renderHistory();
    }

    newChat() {
        this.conversationId = null;
        this.messages = [];
        this.sessionId = this.generateSessionId();
        this.contextFiles = [];
        this.refreshActiveViewContext(true);
        document.getElementById('chatArea').innerHTML = this.getWelcome();
        this.updateContextBar();
        this.renderHistory();
    }

    toggleContextAware(checked) {
        if (!this.getModeMeta(this.currentMode).supports_context) {
            this.contextAware = false;
            return;
        }
        this.contextAware = !!checked;
        this.queryContextAwarePreference = this.contextAware;
        localStorage.setItem('jive_context_aware', this.contextAware ? '1' : '0');
        this.refreshActiveViewContext(true);
        this.updateContextBar();

        if (!this.conversationId && (!this.messages || this.messages.length === 0)) {
            const chatArea = document.getElementById('chatArea');
            if (chatArea) {
                chatArea.innerHTML = this.getWelcome();
            }
        }
    }

    bindRouteEvents() {
        if (this.routeEventsBound) return;
        if (!frappe.router || typeof frappe.router.on !== 'function') return;

        this.routeEventsBound = true;
        frappe.router.on('change', () => {
            this.refreshActiveViewContext(true);
        });
    }

    bindPageContextObserver() {
        if (this.pageContextObserver) return;
        if (typeof MutationObserver === 'undefined' || !document.body) return;

        try {
            this.pageContextObserver = new MutationObserver((mutations) => {
                const route = this.getCurrentRoute();
                const routeType = (route[0] || '').toLowerCase();
                if (!['page', 'dashboard-view', 'workspace', 'workspaces'].includes(routeType) && !window.cur_page?.page) {
                    return;
                }

                const pageRoot = this.getPageRootElement(window.cur_page?.page || window.cur_list?.page || window.cur_page?.page);
                if (pageRoot && Array.isArray(mutations) && mutations.length) {
                    const relevant = mutations.some((mutation) => {
                        const target = mutation && mutation.target;
                        const chatContainer = this.container || null;
                        if (chatContainer && target && typeof chatContainer.contains === 'function' && chatContainer.contains(target)) return false;
                        if (target && typeof target.contains === 'function' && pageRoot.contains(target)) return true;
                        if (mutation && mutation.addedNodes && mutation.addedNodes.length) {
                            return Array.from(mutation.addedNodes).some((node) => node && node.nodeType === 1 && pageRoot.contains(node) && !(chatContainer && chatContainer.contains(node)));
                        }
                        return false;
                    });
                    if (!relevant) return;
                }

                this.schedulePageContextRefresh();
            });
            this.pageContextObserver.observe(document.body, {
                subtree: true,
                childList: true,
                characterData: true,
            });
        } catch (e) {
            this.pageContextObserver = null;
        }
    }

    schedulePageContextRefresh(delay = 220) {
        clearTimeout(this.pageContextRefreshTimer);
        this.pageContextRefreshTimer = setTimeout(() => {
            this.refreshActiveViewContext(false);
        }, delay);
    }

    buildContextPlaceholder(route) {
        const safeRoute = Array.isArray(route) ? route : [];
        const routeType = (safeRoute[0] || '').toLowerCase();
        const label = routeType === 'form'
            ? 'Reading the current form...'
            : routeType === 'list'
                ? 'Reading the current list...'
                : routeType === 'dashboard-view'
                    ? 'Reading the dashboard...'
                : routeType === 'workspace' || routeType === 'workspaces'
                    ? 'Reading the current workspace...'
                    : 'Reading the current view...';

        return {
            route: safeRoute,
            source_type: 'loading',
            label: label,
        };
    }

    isContextReadyForRoute(context, route) {
        const safeRoute = Array.isArray(route) ? route : [];
        const routeType = (safeRoute[0] || '').toLowerCase();

        if (routeType === 'form') {
            const frm = window.cur_frm;
            if (!frm || !frm.doc) return false;

            const doctype = frm.doctype || safeRoute[1] || frm.doc.doctype;
            const name = frm.doc.name || safeRoute[2] || '';
            if (safeRoute[1] && doctype && String(doctype) !== String(safeRoute[1])) return false;
            if (safeRoute[2] && name && String(name) !== String(safeRoute[2])) return false;
            return context && context.source_type === 'form' && context.doctype === doctype && (!safeRoute[2] || context.name === name);
        }

        if (routeType === 'list') {
            const listView = window.cur_list;
            if (!listView) return false;

            const doctype = listView.doctype || safeRoute[1];
            if (safeRoute[1] && doctype && String(doctype) !== String(safeRoute[1])) return false;
            return context && context.source_type === 'list' && context.doctype === doctype;
        }

        if (routeType === 'workspace' || routeType === 'workspaces') {
            return context && context.source_type === 'workspace';
        }

        if (routeType === 'dashboard-view') {
            return context && context.source_type === 'page' && context.page_kind === 'dashboard';
        }

        if (routeType === 'page' || (window.cur_page && window.cur_page.page)) {
            return context && context.source_type === 'page';
        }

        return !!context;
    }

    refreshActiveViewContext(forceRender = false, attempt = 0, targetRouteKey = null) {
        const currentRoute = this.getCurrentRoute();
        const currentRouteKey = currentRoute.join('::');
        const expectedRouteKey = targetRouteKey || currentRouteKey;

        if (attempt === 0) {
            clearTimeout(this.routeChangeTimer);
            this.pendingContextRouteKey = expectedRouteKey;
            this.activeViewContext = this.buildContextPlaceholder(currentRoute);
            if (forceRender && this.currentMode === 'query' && this.contextAware) {
                this.updateContextBar();
                if (!this.conversationId && (!this.messages || this.messages.length === 0)) {
                    const chatArea = document.getElementById('chatArea');
                    if (chatArea) {
                        chatArea.innerHTML = this.getWelcome();
                    }
                }
            }
        }

        if (currentRouteKey !== expectedRouteKey) return;

        const context = this.getCurrentViewContext();
        if (!this.isContextReadyForRoute(context, currentRoute)) {
            if (attempt < 20) {
                this.routeChangeTimer = setTimeout(() => {
                    this.refreshActiveViewContext(forceRender, attempt + 1, expectedRouteKey);
                }, 120);
            }
            return;
        }

        const routeType = (currentRoute[0] || '').toLowerCase();
        if (['page', 'dashboard-view', 'workspace', 'workspaces'].includes(routeType) && this.isSparsePageContext(context) && attempt < 20) {
            this.routeChangeTimer = setTimeout(() => {
                this.refreshActiveViewContext(forceRender, attempt + 1, expectedRouteKey);
            }, 150);
            return;
        }

        this.activeViewContext = context;

        if (forceRender && this.currentMode === 'query' && this.contextAware) {
            this.updateContextBar();
            if (!this.conversationId && (!this.messages || this.messages.length === 0)) {
                const chatArea = document.getElementById('chatArea');
                if (chatArea) {
                    chatArea.innerHTML = this.getWelcome();
                }
            }
        }
    }

    getDisplayContext() {
        return this.activeViewContext || this.getCurrentViewContext();
    }

    async waitForContextHydration(maxAttempts = 12, delayMs = 120) {
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
            const context = this.getDisplayContext();
            if (!this.isSparsePageContext(context)) {
                return context;
            }
            await new Promise((resolve) => setTimeout(resolve, delayMs));
        }
        return this.getDisplayContext();
    }

    useSuggestion(text) {
        const input = document.getElementById('jiveInput');
        if (input) {
            input.value = text;
            this.autoResize(input);
            input.focus();
        }
    }

    splitFollowupSuggestions(content) {
        const raw = content || '';
        const startToken = '[[FOLLOWUP_SUGGESTIONS]]';
        const endToken = '[[/FOLLOWUP_SUGGESTIONS]]';
        const startIdx = raw.lastIndexOf(startToken);
        const endIdx = raw.lastIndexOf(endToken);

        if (startIdx === -1 || endIdx === -1 || endIdx <= startIdx) {
            return { content: raw, suggestions: [] };
        }

        const jsonText = raw.slice(startIdx + startToken.length, endIdx).trim();
        const visible = (raw.slice(0, startIdx) + raw.slice(endIdx + endToken.length)).trim();

        try {
            const parsed = JSON.parse(jsonText);
            const list = Array.isArray(parsed) ? parsed : (parsed && Array.isArray(parsed.suggestions) ? parsed.suggestions : []);
            const suggestions = [];
            const seen = new Set();

            for (const item of list) {
                if (typeof item !== 'string') continue;
                let text = item.replace(/\s+/g, ' ').trim();
                if (!text) continue;
                if (!text.endsWith('?')) text += '?';
                const normalized = text.toLowerCase();
                if (seen.has(normalized)) continue;
                seen.add(normalized);
                suggestions.push(text);
            }

            return { content: visible || raw, suggestions };
        } catch (e) {
            return { content: visible || raw, suggestions: [] };
        }
    }

    autoResize(el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 150) + 'px';
    }

    // Load conversations from server
    async loadConversations() {
        try {
            const r = await frappe.call({
                method: 'ampower_jive.api.get_user_conversations',
                freeze: false
            });
            if (r?.message && !r.message.error) {
                this.conversations = r.message.conversations || [];
                this.renderHistory();
            }
        } catch (e) { }
    }

    renderHistory() {
        const container = document.getElementById('historyList');
        if (!container) return;

        if (!this.conversations.length) {
            container.innerHTML = `
                <div class="jive-history-title">
                    <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                    Recent Chats
                </div>
                <div class="jive-history-empty">
                    <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                    <p>No conversations yet</p>
                    <p style="font-size:11px;margin-top:4px;">Start a new chat to begin</p>
                </div>
            `;
            return;
        }

        // Group by date
        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        const formatDate = (dateStr) => {
            const d = new Date(dateStr);
            if (d.toDateString() === today.toDateString()) return 'Today';
            if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        };

        container.innerHTML = `
            <div class="jive-history-title">
                <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                Recent Chats
            </div>
            ${this.conversations.slice(0, 30).map(c => {
            const title = c.title || 'New conversation';
            const shortTitle = title.length > 35 ? title.substring(0, 35) + '...' : title;
            const mode = c.mode || 'query';
            const modeMeta = this.getModeMeta(mode);
            const icon = modeMeta.icon || '⬡';
            return `
                    <div class="jive-history-item ${c.name === this.conversationId ? 'active' : ''}" data-id="${c.name}">
                        <div class="jive-history-icon ${mode}" style="color:${modeMeta.color || '#6366f1'}" onclick="jiveChat.loadConversation('${c.name}')">${icon}</div>
                        <div class="jive-history-content" onclick="jiveChat.loadConversation('${c.name}')">
                            <div class="jive-history-text">${this.esc(shortTitle)}</div>
                            <div class="jive-history-meta">${formatDate(c.modified || c.creation)}</div>
                        </div>
                        <button class="jive-history-delete" onclick="event.stopPropagation(); jiveChat.confirmDelete('${c.name}', '${this.esc(shortTitle).replace(/'/g, "\\'")}');" title="Delete conversation">
                            <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
                        </button>
                    </div>
                `;
        }).join('')}
        `;
    }

    async loadConversation(id) {
        try {
            const r = await frappe.call({
                method: 'ampower_jive.api.get_conversation_history',
                args: { conversation_id: id }
            });

            if (r?.message && !r.message.error) {
                this.conversationId = id;
                // Switch to conversation's mode
                if (r.message.mode === 'context') {
                    this.currentMode = this.getDefaultMode();
                    this.contextAware = true;
                    this.queryContextAwarePreference = true;
                    localStorage.setItem('jive_context_aware', '1');
                    this.render();
                    this.bindEvents();
                } else if (r.message.mode && r.message.mode !== this.currentMode) {
                    const targetMode = this.isModeAllowed(r.message.mode) ? r.message.mode : this.getDefaultMode();
                    if (r.message.mode === 'helpdesk') {
                        this.contextAware = false;
                    } else if (r.message.mode === 'query' && this.currentMode === 'helpdesk') {
                        const stored = localStorage.getItem('jive_context_aware');
                        this.contextAware = stored === null ? true : stored === '1';
                        this.queryContextAwarePreference = this.contextAware;
                    }
                    this.currentMode = targetMode;
                    this.render();
                    this.bindEvents();
                }
                this.messages = r.message.messages || [];
                this.renderMessages();
                this.renderHistory();
            }
        } catch (e) {
            frappe.show_alert({ message: 'Failed to load conversation', indicator: 'red' });
        }
    }

    confirmDelete(id, title) {
        // Create and show confirmation dialog
        const overlay = document.createElement('div');
        overlay.className = 'jive-confirm-overlay';
        overlay.id = 'deleteConfirmOverlay';
        overlay.innerHTML = `
            <div class="jive-confirm-dialog">
                <div class="jive-confirm-icon">
                    <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </div>
                <div class="jive-confirm-title">Delete conversation?</div>
                <div class="jive-confirm-text">"${title}" will be permanently deleted. This action cannot be undone.</div>
                <div class="jive-confirm-buttons">
                    <button class="jive-confirm-btn cancel" onclick="jiveChat.closeDeleteConfirm()">Cancel</button>
                    <button class="jive-confirm-btn delete" onclick="jiveChat.deleteConversation('${id}')">Delete</button>
                </div>
            </div>
        `;

        // Close on overlay click
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) this.closeDeleteConfirm();
        });

        // Close on Escape key
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                this.closeDeleteConfirm();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        document.body.appendChild(overlay);
    }

    closeDeleteConfirm() {
        const overlay = document.getElementById('deleteConfirmOverlay');
        if (overlay) {
            overlay.style.animation = 'fadeIn 0.15s ease-out reverse';
            setTimeout(() => overlay.remove(), 150);
        }
    }

    async deleteConversation(id) {
        this.closeDeleteConfirm();

        try {
            const r = await frappe.call({
                method: 'ampower_jive.api.clear_conversation',
                args: { conversation_id: id }
            });

            if (r?.message && !r.message.error) {
                // Remove from local list
                this.conversations = this.conversations.filter(c => c.name !== id);

                // If we deleted the current conversation, reset
                if (this.conversationId === id) {
                    this.conversationId = null;
                    this.messages = [];
                    document.getElementById('chatArea').innerHTML = this.getWelcome();
                }

                // Update UI
                this.renderHistory();
                frappe.show_alert({ message: 'Conversation deleted', indicator: 'green' });
            } else {
                frappe.show_alert({ message: r.message?.message || 'Failed to delete', indicator: 'red' });
            }
        } catch (e) {
            frappe.show_alert({ message: 'Failed to delete conversation', indicator: 'red' });
        }
    }

    async send() {
        const input = document.getElementById('jiveInput');
        const msg = input.value.trim();
        if (!msg || this.isLoading) return;

        input.value = '';
        this.autoResize(input);

        this.messages.push({ role: 'user', content: msg });
        this.renderMessages();

        // Show mode-specific initial status
        const modeMeta = this.getModeMeta(this.currentMode);
        let currentViewContext = this.getDisplayContext();
        let isContextAwareRequest = this.contextAware && !!modeMeta.supports_context;
        const contextRouteType = (currentViewContext?.route?.[0] || '').toLowerCase();
        if (isContextAwareRequest && this.isSparsePageContext(currentViewContext) && ['page', 'dashboard-view', 'workspace', 'workspaces'].includes(contextRouteType)) {
            currentViewContext = await this.waitForContextHydration();
            isContextAwareRequest = this.contextAware && !!modeMeta.supports_context;
        }
        this.showTyping(isContextAwareRequest ? 'Reading the current view...' : (modeMeta.status_message || 'Thinking...'));
        this.isLoading = true;

        // For helpdesk mode, simulate progressive status updates
        let statusTimer = null;
        if (this.normalizeMode(this.currentMode) === 'helpdesk' && this.config.enable_gif_generation) {
            statusTimer = setTimeout(() => {
                this.updateTypingStatus('Creating visual guide...');
            }, 2000);
        } else if (isContextAwareRequest) {
            statusTimer = setTimeout(() => {
                this.updateTypingStatus('Reading the current view...');
            }, 1200);
        } else if (this.normalizeMode(this.currentMode) === 'agent') {
            statusTimer = setTimeout(() => {
                this.updateTypingStatus('Planning actions...');
            }, 1500);
        }

        try {
            const contextPayload = isContextAwareRequest ? JSON.stringify(currentViewContext) : null;
            const r = await frappe.call({
                method: 'ampower_jive.api.chat',
                args: {
                    message: msg,
                    conversation_id: this.conversationId,
                    mode: this.currentMode,
                    session_id: this.sessionId,
                    context_aware: isContextAwareRequest ? 1 : 0,
                    context_payload: contextPayload,
                    portal_access: this.portalAccess ? 1 : 0
                },
                freeze: false,
                async: true,
                timeout: 90  // 90 seconds timeout for complex queries
            });

            // Clear status timer
            if (statusTimer) clearTimeout(statusTimer);
            this.hideTyping();

            if (r?.message) {
                if (r.message.error) {
                    this.messages.push({ role: 'assistant', content: r.message.message || 'An error occurred' });
                    this.renderMessages();
                } else {
                    this.conversationId = r.message.conversation_id;

                    // Check if agent mode needs approval
                    if (r.message.needs_approval && r.message.plan) {
                        this.pendingPlan = r.message.plan;
                        this.messages.push({
                            role: 'assistant',
                            content: r.message.response || 'I have analyzed your request.',
                            plan: r.message.plan,
                            needs_approval: true
                        });
                        this.renderMessages();
                        this.renderPlanApproval(r.message.plan);
                    } else {
                        // Include gif_url if present (for helpdesk mode)
                        const msgData = { role: 'assistant', content: r.message.response };
                        if (Array.isArray(r.message.suggestions) && r.message.suggestions.length > 0) {
                            msgData.suggestions = r.message.suggestions;
                        }
                        if (r.message.gif_url) {
                            msgData.gif_url = r.message.gif_url;
                        }
                        // Include chart render data if present (for insights mode)
                        if (r.message.chart_render_data && r.message.chart_render_data.length > 0) {
                            msgData.chart_render_data = r.message.chart_render_data;
                        }
                        if (r.message.created_urls && r.message.created_urls.length > 0) {
                            msgData.created_urls = r.message.created_urls;
                        }
                        this.messages.push(msgData);
                        this.renderMessages();
                    }
                    // Refresh history to show new conversation with title
                    this.loadConversations();

                    // Update token usage if returned
                    if (r.message.token_usage) {
                        console.log("JiveChat: Received token usage update", r.message.token_usage);
                        this.config.token_usage = r.message.token_usage;
                        this.updateUsageDisplay();
                    } else {
                        console.log("JiveChat: No token usage in response");
                    }
                }
            }
        } catch (e) {
            if (statusTimer) clearTimeout(statusTimer);
            this.hideTyping();

            // Provide more helpful error message
            let errorMsg = 'Failed to get response. Please try again.';
            if (e?.message?.includes('timeout') || e?.message?.includes('Timeout')) {
                errorMsg = '⏱️ Request timed out. Please try a simpler or more specific query.';
            } else if (e?.exc_type === 'ValidationError') {
                errorMsg = '⚠️ Validation error: ' + (e?.message || 'Please check your input.');
            }

            this.messages.push({ role: 'assistant', content: errorMsg });
            this.renderMessages();
            console.error('Jive chat error:', e);
        }

        this.isLoading = false;
    }

    renderMessages() {
        const chat = document.getElementById('chatArea');
        if (!chat) return;

        const user = frappe.session.user_fullname || frappe.session.user;
        const currentContext = this.getDisplayContext();
        const canDraftFormComment = this.contextAware && currentContext && currentContext.source_type === 'form';

        chat.innerHTML = `
            <div class="jive-messages">
                ${this.messages.map((m, idx) => {
                    const parsed = this.splitFollowupSuggestions(m.content);
                    const messageText = parsed.content;
                    const suggestions = Array.isArray(m.suggestions) && m.suggestions.length ? m.suggestions : (parsed.suggestions || []);

                    return `
                    <div class="jive-msg ${m.role}">
                        <div class="jive-msg-avatar">${m.role === 'user' ? user.charAt(0).toUpperCase() : 'A'}</div>
                        <div class="jive-msg-content">
                            <div class="jive-msg-text">${this.formatText(messageText)}</div>
                            ${m.gif_url ? `
                                <div class="jive-msg-gif">
                                    <div class="jive-gif-header">
                                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                                            <circle cx="8.5" cy="8.5" r="1.5"/>
                                            <polyline points="21 15 16 10 5 21"/>
                                        </svg>
                                        <span>Visual Guide</span>
                                    </div>
                                    <img src="${m.gif_url}" alt="Helpdesk Guide" class="jive-gif-image" loading="lazy"/>
                                </div>
                            ` : ''}
                            ${m.chart_render_data && m.chart_render_data.length > 0 ?
                                m.chart_render_data.map((chart, cidx) => this.renderInlineChart(chart, idx, cidx)).join('')
                                : ''}
                            ${suggestions.length ? `
                                <div class="jive-suggestions">
                                    ${suggestions.map(s => `<button class="jive-suggestion" onclick="jiveChat.useSuggestion('${this.esc(s)}')">${this.esc(s)}</button>`).join('')}
                                </div>
                            ` : ''}
                            ${m.role === 'assistant' && !m.needs_approval ? `
                                <div class="jive-msg-feedback" id="feedback-${idx}">
                                    ${m.feedback_submitted ? `
                                        <div class="jive-feedback-thanks">Thank you for your feedback!</div>
                                    ` : m.feedback_open ? `
                                        <div class="jive-feedback-form">
                                            <input type="text" id="feedback-comment-${idx}" placeholder="${m.feedback_open === 'Like' ? 'Glad it was helpful! Any comments?' : 'What went wrong?'}" class="jive-feedback-input" onkeydown="if(event.key==='Enter') jiveChat.submitFeedback(${idx})"/>
                                            <button onclick="jiveChat.submitFeedback(${idx})" class="jive-feedback-submit">Submit</button>
                                            <button onclick="jiveChat.cancelFeedback(${idx})" class="jive-feedback-cancel">Cancel</button>
                                        </div>
                                    ` : `
                                        <button class="jive-feedback-btn like ${m.feedback === 'Like' ? 'active' : ''}" onclick="jiveChat.openFeedback(${idx}, 'Like')" title="Helpful">
                                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
                                        </button>
                                        <button class="jive-feedback-btn dislike ${m.feedback === 'Dislike' ? 'active' : ''}" onclick="jiveChat.openFeedback(${idx}, 'Dislike')" title="Not Helpful">
                                            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>
                                        </button>
                                        ${canDraftFormComment ? `
                                            <button class="jive-feedback-btn comment" onclick="jiveChat.copyResponseToFormComment(${idx})" title="Copy to form comment box">
                                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                                                    <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>
                                                </svg>
                                            </button>
                                        ` : ''}
                                    `}
                                </div>
                            ` : ''}
                        </div>
                    </div>
                    `;
                }).join('')}
            </div>
        `;

        // Initialize any charts that need canvas rendering
        this.initializeCharts();

        chat.scrollTop = chat.scrollHeight;
    }

    renderInlineChart(chartData, msgIdx, chartIdx) {
        if (!chartData || !chartData.data) return '';

        const data = chartData.data;
        const chartId = `jive-chart-${msgIdx}-${chartIdx}`;
        const chartType = (data.type || 'bar').toLowerCase();
        const title = chartData.title || 'Chart';
        const url = chartData.url || '';
        const workbookUrl = chartData.workbook_url || url;

        // Prepare data for rendering
        const labels = data.labels || [];
        const values = data.values || [];

        if (labels.length === 0 || values.length === 0) {
            return '';
        }

        // Calculate max value for scaling
        const maxValue = Math.max(...values.map(v => Number(v) || 0));

        // Generate chart HTML based on type
        let chartHtml = '';

        if (chartType === 'number') {
            // Single number display
            const value = values[0] || 0;
            const formattedValue = this.formatChartNumber(value);
            chartHtml = `
                <div class="jive-inline-number">
                    <div class="jive-number-value">${formattedValue}</div>
                    <div class="jive-number-label">${labels[0] || title}</div>
                </div>
            `;
        } else if (chartType === 'donut' || chartType === 'pie') {
            // Donut/Pie chart
            chartHtml = this.renderDonutChart(labels, values, chartId);
        } else {
            // Bar chart (default)
            chartHtml = this.renderBarChart(labels, values, maxValue, chartId);
        }

        return `
            <div class="jive-inline-chart" data-chart-id="${chartId}">
                <div class="jive-chart-header">
                    <div class="jive-chart-icon">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                            <polyline points="8 17 12 11 16 15 20 9"/>
                        </svg>
                    </div>
                    <span class="jive-chart-title">${this.esc(title)}</span>
                    <a href="${url}" target="_blank" class="jive-chart-link" title="Open in Insights">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
                            <polyline points="15 3 21 3 21 9"/>
                            <line x1="10" y1="14" x2="21" y2="3"/>
                        </svg>
                    </a>
                </div>
                <div class="jive-chart-body">
                    ${chartHtml}
                </div>
            </div>
        `;
    }

    renderBarChart(labels, values, maxValue, chartId) {
        const colors = ['#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899', '#f43f5e', '#f97316', '#eab308'];
        const barCount = Math.min(labels.length, 8);

        return `
            <div class="jive-bar-chart">
                ${labels.slice(0, barCount).map((label, i) => {
            const value = values[i] || 0;
            const pct = maxValue > 0 ? (value / maxValue * 100) : 0;
            const color = colors[i % colors.length];
            const formattedValue = this.formatChartNumber(value);
            return `
                        <div class="jive-bar-row">
                            <div class="jive-bar-label" title="${this.esc(label)}">${this.esc(String(label).substring(0, 15))}${String(label).length > 15 ? '...' : ''}</div>
                            <div class="jive-bar-track">
                                <div class="jive-bar-fill" style="width: ${pct}%; background: ${color};"></div>
                            </div>
                            <div class="jive-bar-value">${formattedValue}</div>
                        </div>
                    `;
        }).join('')}
            </div>
        `;
    }

    renderDonutChart(labels, values, chartId) {
        const colors = ['#6366f1', '#8b5cf6', '#a855f7', '#d946ef', '#ec4899', '#f43f5e', '#f97316', '#eab308'];
        const total = values.reduce((a, b) => Number(a) + Number(b), 0);

        // Calculate percentages and segments
        let cumulative = 0;
        const segments = labels.slice(0, 6).map((label, i) => {
            const value = Number(values[i]) || 0;
            const pct = total > 0 ? (value / total * 100) : 0;
            const startPct = cumulative;
            cumulative += pct;
            return { label, value, pct, startPct, color: colors[i % colors.length] };
        });

        // Build SVG donut
        const size = 100;
        const strokeWidth = 20;
        const radius = (size - strokeWidth) / 2;
        const circumference = 2 * Math.PI * radius;
        const center = size / 2;

        let currentOffset = 0;
        const paths = segments.map((seg, i) => {
            const dashLength = (seg.pct / 100) * circumference;
            const gap = circumference - dashLength;
            const offset = -currentOffset + circumference / 4; // Start from top
            currentOffset += dashLength;
            return `<circle cx="${center}" cy="${center}" r="${radius}" fill="none" stroke="${seg.color}" stroke-width="${strokeWidth}" stroke-dasharray="${dashLength} ${gap}" stroke-dashoffset="${offset}" />`;
        }).join('');

        return `
            <div class="jive-donut-chart">
                <svg viewBox="0 0 ${size} ${size}" class="jive-donut-svg">
                    ${paths}
                    <circle cx="${center}" cy="${center}" r="${radius - strokeWidth / 2}" fill="#1a1b2e"/>
                </svg>
                <div class="jive-donut-legend">
                    ${segments.map(seg => `
                        <div class="jive-legend-item">
                            <span class="jive-legend-dot" style="background: ${seg.color};"></span>
                            <span class="jive-legend-label">${this.esc(String(seg.label).substring(0, 12))}</span>
                            <span class="jive-legend-value">${seg.pct.toFixed(1)}%</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    formatChartNumber(value) {
        const num = Number(value) || 0;
        if (Math.abs(num) >= 1000000) {
            return (num / 1000000).toFixed(2) + 'M';
        } else if (Math.abs(num) >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        } else if (Number.isInteger(num)) {
            return num.toLocaleString();
        } else {
            return num.toFixed(2);
        }
    }

    initializeCharts() {
        // Placeholder for any charts that need canvas/JS initialization
        // Currently using pure CSS/SVG charts which don't need initialization
    }

    openFeedback(idx, type) {
        if (this.messages[idx].feedback_submitted) return;
        this.messages[idx].feedback_open = type;
        this.renderMessages();
        setTimeout(() => {
            const input = document.getElementById(`feedback-comment-${idx}`);
            if (input) input.focus();
        }, 50);
    }

    cancelFeedback(idx) {
        this.messages[idx].feedback_open = null;
        this.renderMessages();
    }

    buildCommentDraftHtml(responseText) {
        const content = (responseText || '').replace(/\r\n/g, '\n').trim();
        if (!content) return '';

        const escapeHtml = (value) => this.esc(String(value || ''));
        const toParagraphs = (text) => {
            const parts = String(text || '')
                .split(/\n{2,}/)
                .map(part => part.replace(/\n/g, '<br>').trim())
                .filter(Boolean);

            if (!parts.length) return '';

            if (parts.length === 1) {
                const single = parts[0];
                const hasMultipleSentences = /[.!?]\s+[A-Z0-9(]/.test(single) && single.length > 180;
                if (hasMultipleSentences) {
                    const spaced = single.replace(/([.!?])\s+(?=[A-Z0-9(])/g, '$1<br><br>');
                    return `<p>${spaced}</p>`;
                }
                return `<p>${single}</p>`;
            }

            return parts.map(part => `<p>${part}</p>`).join('');
        };

        const sourceUser = escapeHtml(frappe.session.user || 'frappe.session.user');
        const commentSource = `<p>~Commented by: ${sourceUser}  ~source: Jive</p>`;
        return `${toParagraphs(escapeHtml(content))}${commentSource}`;
    }

    copyResponseToFormComment(idx) {
        const context = this.getDisplayContext();
        if (!(this.contextAware && context && context.source_type === 'form')) {
            frappe.show_alert({ message: 'Open a form with context aware mode enabled to add a comment.', indicator: 'orange' });
            return;
        }

        const frm = window.cur_frm;
        const commentBox = frm?.comment_box;
        if (!commentBox || typeof commentBox.set_value !== 'function') {
            frappe.show_alert({ message: 'The form comment box is not ready yet.', indicator: 'orange' });
            return;
        }

        const parsed = this.splitFollowupSuggestions(this.messages[idx]?.content || '');
        const draftHtml = this.buildCommentDraftHtml(parsed.content || this.messages[idx]?.content || '');
        if (!draftHtml) return;

        let finalValue = draftHtml;
        try {
            const existing = commentBox.quill && commentBox.quill.root ? (commentBox.quill.root.innerHTML || '').trim() : '';
            if (existing) {
                finalValue = `${existing}<p><br></p>${draftHtml}`;
            }
        } catch (e) { }

        if (typeof commentBox.set_formatted_input === 'function') {
            commentBox.set_formatted_input(finalValue);
        } else {
            commentBox.set_value(finalValue);
        }

        try {
            if (commentBox.$input && typeof commentBox.$input.focus === 'function') {
                commentBox.$input.focus();
            } else if (typeof commentBox.focus === 'function') {
                commentBox.focus();
            }
        } catch (e) { }

        setTimeout(() => {
            try {
                if (commentBox.button && typeof commentBox.button.trigger === 'function') {
                    commentBox.button.trigger('click');
                    frappe.show_alert({ message: 'Response added as a comment.', indicator: 'green' });
                } else if (commentBox.button && typeof commentBox.button[0]?.click === 'function') {
                    commentBox.button[0].click();
                    frappe.show_alert({ message: 'Response added as a comment.', indicator: 'green' });
                } else if (typeof commentBox.submit === 'function') {
                    commentBox.submit();
                    frappe.show_alert({ message: 'Response added as a comment.', indicator: 'green' });
                }
            } catch (e) {
                frappe.show_alert({ message: 'Response copied, but comment could not be submitted.', indicator: 'orange' });
            }
        }, 0);
    }

    submitFeedback(idx) {
        if (this.messages[idx].feedback_submitted) return;
        
        const type = this.messages[idx].feedback_open;
        if (!type) return;
        
        const input = document.getElementById(`feedback-comment-${idx}`);
        const comment = input ? input.value.trim() : '';
        
        // Update local UI state
        this.messages[idx].feedback = type;
        this.messages[idx].feedback_submitted = true;
        this.messages[idx].feedback_open = null;
        this.renderMessages();
        
        // Use a snippet of the message content to identify it on the core side
        const contentSnippet = (this.messages[idx].content || "").substring(0, 100);
        
        // Send to backend
        frappe.call({
            method: 'ampower_jive.api.submit_chat_message_feedback',
            args: {
                conversation_id: this.conversationId,
                feedback: type,
                comment: comment,
                message_idx: idx,
                response_snippet: contentSnippet
            },
            callback: (r) => {
                if (r.message && !r.message.error) {
                    // Success is silent for UX, standard frappe alert if configured
                } else {
                    frappe.show_alert({ message: r.message?.message || 'Failed to submit feedback', indicator: 'red' });
                    // Revert UI on failure
                    this.messages[idx].feedback = null;
                    this.messages[idx].feedback_submitted = false;
                    this.renderMessages();
                }
            }
        });
    }

    showTyping(statusText = null) {
        const chat = document.getElementById('chatArea');
        if (!chat) return;

        const existing = chat.querySelector('.jive-messages');
        if (existing) {
            // Remove existing indicator if present
            const oldIndicator = document.getElementById('typingIndicator');
            if (oldIndicator) oldIndicator.remove();

            const status = statusText || 'Thinking...';
            existing.innerHTML += `
                <div class="jive-msg assistant" id="typingIndicator">
                    <div class="jive-msg-avatar">A</div>
                    <div class="jive-msg-content">
                        <div class="jive-status-indicator">
                            <div class="jive-status-spinner"></div>
                            <span class="jive-status-text">${status}</span>
                        </div>
                    </div>
                </div>
            `;
            chat.scrollTop = chat.scrollHeight;
        }
    }

    updateTypingStatus(statusText) {
        const statusEl = document.querySelector('.jive-status-text');
        if (statusEl) {
            statusEl.textContent = statusText;
        } else {
            this.showTyping(statusText);
        }
    }

    hideTyping() {
        const typing = document.getElementById('typingIndicator');
        if (typing) typing.remove();
    }

    renderPlanApproval(plan) {
        const chat = document.getElementById('chatArea');
        if (!chat) return;

        const existing = chat.querySelector('.jive-messages');
        if (existing) {
            const planHtml = `
                <div class="jive-plan-approval" id="planApproval">
                    <div class="jive-plan-header">
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M9 12l2 2 4-4"/>
                            <circle cx="12" cy="12" r="10"/>
                        </svg>
                        <span>Review Planned Actions</span>
                    </div>
                    <div class="jive-plan-actions">
                        ${plan.map((p, i) => `
                            <div class="jive-plan-action">
                                <div class="jive-plan-action-header">
                                    <span class="jive-plan-action-badge ${p.action}">${p.action.toUpperCase()}</span>
                                    <span class="jive-plan-action-doctype">${p.doctype}${p.name ? ` - ${p.name}` : ''}</span>
                                </div>
                                <div class="jive-plan-action-desc">${this.esc(p.description)}</div>
                                ${p.data ? `
                                    <div class="jive-plan-action-data">
                                        <div class="jive-plan-data-title">Fields to set:</div>
                                        ${Object.entries(p.data).slice(0, 10).map(([k, v]) => `
                                            <div class="jive-plan-data-item">
                                                <span class="jive-plan-data-key">${this.esc(k)}:</span>
                                                <span class="jive-plan-data-value">${this.formatPlanValue(v)}</span>
                                            </div>
                                        `).join('')}
                                        ${Object.keys(p.data).length > 10 ? '<div class="jive-plan-data-more">...and more fields</div>' : ''}
                                    </div>
                                ` : ''}
                            </div>
                        `).join('')}
                    </div>
                    <div class="jive-plan-warning">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                            <line x1="12" y1="9" x2="12" y2="13"/>
                            <line x1="12" y1="17" x2="12.01" y2="17"/>
                        </svg>
                        <span>These actions will modify your data. Please review carefully before approving.</span>
                    </div>
                    <div class="jive-plan-buttons">
                        <button class="jive-plan-btn reject" onclick="window.jiveChat.rejectPlan()">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                                <line x1="18" y1="6" x2="6" y2="18"/>
                                <line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                            Cancel
                        </button>
                        <button class="jive-plan-btn approve" onclick="window.jiveChat.approvePlan()">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="20 6 9 17 4 12"/>
                            </svg>
                            Approve & Execute
                        </button>
                    </div>
                </div>
            `;
            existing.innerHTML += planHtml;
            chat.scrollTop = chat.scrollHeight;
        }
    }

    async approvePlan() {
        if (!this.pendingPlan || !this.conversationId) {
            frappe.show_alert({ message: 'No pending plan to approve', indicator: 'orange' });
            return;
        }

        const approvalEl = document.getElementById('planApproval');
        if (approvalEl) {
            approvalEl.innerHTML = `
                <div class="jive-plan-executing">
                    <div class="jive-plan-spinner"></div>
                    <span>Executing plan...</span>
                </div>
            `;
        }

        try {
            const r = await frappe.call({
                method: 'ampower_jive.api.approve_plan',
                args: { conversation_id: this.conversationId }
            });

            if (r?.message) {
                if (r.message.error) {
                    this.messages.push({
                        role: 'assistant',
                        content: `❌ Execution failed: ${r.message.message}\n\nDetails:\n${JSON.stringify(r.message.results || [], null, 2)}`
                    });
                } else {
                    const results = r.message.results || [];
                    const successCount = results.filter(r => r.success).length;
                    const failCount = results.length - successCount;

                    let summary = `✅ **Execution Complete**\n\n`;
                    summary += `- Successful: ${successCount}\n`;
                    if (failCount > 0) summary += `- Failed: ${failCount}\n`;
                    summary += `\n**Results:**\n`;
                    results.forEach((res, i) => {
                        if (res.success) {
                            summary += `${i + 1}. ✓ ${res.message}${res.name ? ` (${res.name})` : ''}\n`;
                        } else {
                            summary += `${i + 1}. ✗ Error: ${res.error}\n`;
                        }
                    });

                    this.messages.push({ role: 'assistant', content: summary });
                }
            }
        } catch (e) {
            this.messages.push({ role: 'assistant', content: `❌ Failed to execute plan: ${e.message || 'Unknown error'}` });
        }

        this.pendingPlan = null;
        if (approvalEl) approvalEl.remove();
        this.renderMessages();
    }

    async rejectPlan() {
        if (!this.conversationId) return;

        try {
            await frappe.call({
                method: 'ampower_jive.api.reject_plan',
                args: { conversation_id: this.conversationId }
            });
        } catch (e) {
            console.error('Failed to reject plan:', e);
        }

        this.pendingPlan = null;
        const approvalEl = document.getElementById('planApproval');
        if (approvalEl) approvalEl.remove();

        this.messages.push({ role: 'assistant', content: '🚫 Operation cancelled. Let me know if you need anything else.' });
        this.renderMessages();
    }

    formatText(text) {
        if (!text) return '';
        // First escape HTML, then apply formatting
        let formatted = this.esc(text);
        // Code blocks
        formatted = formatted.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        // Markdown headings -> keep the title without leaking hashes
        formatted = formatted.replace(/^#{1,6}\s+(.+)$/gm, '<strong>$1</strong>');
        // Markdown horizontal rules
        formatted = formatted.replace(/^\s*---\s*$/gm, '<hr class="jive-divider">');
        // Inline code
        formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
        // Bold
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        // Markdown links [text](url) - convert to clickable HTML links
        formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" class="jive-link">$1</a>');
        // Plain URLs - make clickable
        formatted = formatted.replace(/(https?:\/\/[^\s<]+)/g, (match) => {
            // Don't double-wrap URLs that are already in links
            if (formatted.indexOf('href="' + match) !== -1) return match;
            return '<a href="' + match + '" target="_blank" class="jive-link">' + match + '</a>';
        });
        // Line breaks
        formatted = formatted.replace(/\n/g, '<br>');
        return formatted;
    }

    formatPlanValue(value) {
        if (value === null || value === undefined) return '';
        const text = typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
        return this.esc(text).replace(/\n/g, '<br>');
    }

    esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // Context file handling

    getCurrentRoute() {
        try {
            let route = frappe.get_route ? frappe.get_route() : [];

            if (Array.isArray(route) && route.length === 1) {
                return ['page', route[0]];
            }

            return Array.isArray(route) ? route : [];
        } catch (e) {
            return [];
        }
    }

    safeClone(value) {
        try {
            return JSON.parse(JSON.stringify(value));
        } catch (e) {
            return value || {};
        }
    }

    isVisibleElement(el) {
        try {
            return !!(el && el.getClientRects && el.getClientRects().length);
        } catch (e) {
            return false;
        }
    }

    slugToCamel(value) {
        return (value || '')
            .replace(/[_-]+([a-z0-9])/gi, (_, chr) => String(chr).toUpperCase())
            .replace(/^[A-Z]/, chr => chr.toLowerCase());
    }

    normalizePageKey(value) {
        return (value || '').toString().trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    }

    getPageRootElement(pageObj) {
        const candidates = [
            pageObj?.main?.[0],
            pageObj?.wrapper?.[0],
            pageObj?.$page?.[0],
            pageObj?.page?.wrapper?.[0],
            window.cur_page?.page?.main?.[0],
            window.cur_page?.page?.wrapper?.[0],
            document.body,
        ];
        return candidates.find(el => el && el.nodeType === 1) || null;
    }

    getElementLabel(el) {
        try {
            if (!el) return '';
            const attrLabel = el.getAttribute('aria-label') || el.getAttribute('data-label') || el.getAttribute('title');
            if (attrLabel) return attrLabel.trim();
            if (el.placeholder) return String(el.placeholder).trim();
            if (el.labels && el.labels.length) {
                for (const labelNode of Array.from(el.labels)) {
                    const text = (labelNode && labelNode.textContent ? labelNode.textContent : '').replace(/\s+/g, ' ').trim();
                    if (text) return text;
                }
            }
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
                for (const id of labelledBy.split(/\s+/)) {
                    const node = document.getElementById(id);
                    const text = (node && node.textContent ? node.textContent : '').replace(/\s+/g, ' ').trim();
                    if (text) return text;
                }
            }
            const closestLabel = el.closest('label');
            if (closestLabel && closestLabel.textContent) {
                const text = closestLabel.textContent.replace(/\s+/g, ' ').trim();
                if (text) return text;
            }
            let parent = el.parentElement;
            for (let depth = 0; depth < 3 && parent; depth += 1, parent = parent.parentElement) {
                const nodes = parent.querySelectorAll('label, legend, th, caption, summary, button, a');
                for (const node of nodes) {
                    if (!node || node === el || !this.isVisibleElement(node)) continue;
                    const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
                    if (text && text.length <= 80) {
                        return text;
                    }
                }
            }
            return '';
        } catch (e) {
            return '';
        }
    }

    collectVisibleControls(rootEl) {
        try {
            if (!rootEl) return [];
            const controls = [];
            const nodes = rootEl.querySelectorAll('input, select, textarea');
            nodes.forEach((el) => {
                if (!this.isVisibleElement(el)) return;
                const type = (el.type || el.tagName || '').toLowerCase();
                if (['button', 'submit', 'reset', 'hidden', 'file'].includes(type)) return;
                const label = this.getElementLabel(el) || el.name || el.id || '';
                const value = type === 'checkbox' ? !!el.checked : (el.value ?? '');
                controls.push({
                    fieldname: el.name || el.id || label || null,
                    label: label || el.name || el.id || 'control',
                    fieldtype: el.tagName === 'SELECT' ? 'Select' : (type === 'textarea' ? 'Text' : (type === 'checkbox' ? 'Check' : 'Data')),
                    value: this.safeClone(value),
                });
            });
            return controls.slice(0, 20);
        } catch (e) {
            return [];
        }
    }

    collectObjectControls(pageObject) {
        try {
            if (!pageObject || typeof pageObject !== 'object') return [];

            const controls = [];
            const seen = new Set();
            const visit = (key, value, depth = 0) => {
                if (!value || depth > 1) return;
                if (typeof value !== 'object') return;
                if (typeof value.get_value !== 'function' || !value.df) return;

                const df = value.df || {};
                const fieldname = df.fieldname || key || null;
                const label = df.label || fieldname || key || 'control';
                const fieldtype = df.fieldtype || 'Data';
                const dedupeKey = [fieldname || '', label || '', fieldtype || ''].join('|');
                if (seen.has(dedupeKey)) return;
                seen.add(dedupeKey);

                controls.push({
                    fieldname: fieldname,
                    label: label,
                    fieldtype: fieldtype,
                    options: ['Link', 'Select', 'Table', 'Dynamic Link'].includes(fieldtype) ? df.options || null : null,
                    value: this.safeClone(value.get_value()),
                    source: 'object',
                    key: key,
                });
            };

            Object.entries(pageObject).forEach(([key, value]) => {
                visit(key, value, 0);

                if (value && typeof value === 'object') {
                    if (value.fields_dict && typeof value.fields_dict === 'object') {
                        Object.entries(value.fields_dict).forEach(([childKey, childValue]) => visit(childKey, childValue, 1));
                    }
                    if (value.controls && typeof value.controls === 'object') {
                        Object.entries(value.controls).forEach(([childKey, childValue]) => visit(childKey, childValue, 1));
                    }
                    if (value.filter_fields && typeof value.filter_fields === 'object') {
                        Object.entries(value.filter_fields).forEach(([childKey, childValue]) => visit(childKey, childValue, 1));
                    }
                }
            });

            return controls.slice(0, 20);
        } catch (e) {
            return [];
        }
    }

    collectVisibleText(rootEl) {
        try {
            if (!rootEl) return [];
            const seen = new Set();
            const items = [];
            const pushText = (value) => {
                const text = (value || '').replace(/\s+/g, ' ').trim();
                if (!text || text.length < 2) return;
                const key = text.toLowerCase();
                if (seen.has(key)) return;
                seen.add(key);
                items.push(text);
            };

            if (typeof rootEl.innerText === 'string') {
                rootEl.innerText.split(/\n+/).forEach(pushText);
            }

            if (!items.length) {
                const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_ELEMENT);
                while (walker.nextNode()) {
                    const el = walker.currentNode;
                    if (!this.isVisibleElement(el)) continue;
                    const tag = (el.tagName || '').toUpperCase();
                    if (!['H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'P', 'LI', 'TD', 'TH', 'LABEL', 'BUTTON', 'A', 'SUMMARY', 'LEGEND', 'CAPTION', 'STRONG', 'EM', 'SMALL'].includes(tag) && el.childElementCount > 0) {
                        continue;
                    }
                    pushText(el.textContent || '');
                }
            }

            return items;
        } catch (e) {
            return [];
        }
    }

    summarizeChartSeriesData(series) {
        const data = Array.isArray(series?.data) ? series.data : [];
        const sample = data.slice(0, 6).map((item) => {
            if (item && typeof item === 'object' && !Array.isArray(item)) {
                const compact = {};
                ['name', 'value', 'label', 'id', 'date'].forEach((key) => {
                    if (item[key] !== undefined) compact[key] = this.safeClone(item[key]);
                });
                if (Object.keys(compact).length) return compact;
            }
            return this.safeClone(item);
        });
        return {
            name: series?.name || '',
            type: series?.type || '',
            data_points: data.length,
            sample: sample,
        };
    }

    summarizeEChartsOption(option) {
        if (!option || typeof option !== 'object') return null;
        const titles = [];
        const titleData = Array.isArray(option.title) ? option.title : (option.title ? [option.title] : []);
        titleData.forEach((item) => {
            if (item && item.text) titles.push(item.text);
        });
        const xAxis = Array.isArray(option.xAxis) ? option.xAxis[0] : option.xAxis;
        const yAxis = Array.isArray(option.yAxis) ? option.yAxis[0] : option.yAxis;
        const series = Array.isArray(option.series) ? option.series.slice(0, 6).map(series => this.summarizeChartSeriesData(series)) : [];
        return {
            title: titles.length ? titles : null,
            chart_type: series[0]?.type || '',
            x_axis: xAxis?.type || xAxis?.name || '',
            y_axis: yAxis?.type || yAxis?.name || '',
            legend: Array.isArray(option.legend) ? option.legend.length : !!option.legend,
            series: series,
        };
    }

    summarizeChartLikeValue(value, fallbackLabel = '') {
        try {
            if (!value) return null;

            if (typeof value.getOption === 'function') {
                return {
                    label: fallbackLabel,
                    engine: 'echarts',
                    ...this.summarizeEChartsOption(value.getOption()),
                };
            }

            if (value.data && typeof value.data === 'object') {
                const data = value.data;
                const summary = {
                    label: fallbackLabel,
                    engine: 'frappe_chart_or_custom',
                };
                if (Array.isArray(data.labels)) summary.labels = data.labels.slice(0, 12);
                if (Array.isArray(data.datasets)) {
                    summary.datasets = data.datasets.slice(0, 6).map(dataset => ({
                        name: dataset?.name || dataset?.label || '',
                        values: Array.isArray(dataset?.values) ? dataset.values.slice(0, 12) : [],
                    }));
                }
                if (Array.isArray(data) && data.length) {
                    summary.sample = data.slice(0, 6);
                }
                return summary;
            }

            if (Array.isArray(value)) {
                return { label: fallbackLabel, sample: value.slice(0, 8) };
            }

            if (typeof value === 'object') {
                const keys = Object.keys(value).filter(key => !String(key).startsWith('_')).slice(0, 20);
                const summary = { label: fallbackLabel, keys: keys };
                ['title', 'name', 'label', 'type', 'status', 'value'].forEach((key) => {
                    if (value[key] !== undefined) summary[key] = this.safeClone(value[key]);
                });
                return summary;
            }
        } catch (e) {
            return { label: fallbackLabel, error: String(e) };
        }
        return null;
    }

    normalizeSnapshotText(value) {
        return (value || '').toString().replace(/\s+/g, ' ').trim();
    }

    isLikelySummaryValue(text) {
        const value = this.normalizeSnapshotText(text);
        if (!value) return false;
        if (/^(?:n\/a|na|none|nil|—|–|-|unknown)$/i.test(value)) return true;
        if (/^[₹$€£]?\s*-?\d[\d,]*(?:\.\d+)?%?$/.test(value)) return true;
        if (/^-?\d+(?:\.\d+)?%$/.test(value)) return true;
        if (/^\d+\s+of\s+\d+(\s+\w+)?$/i.test(value)) return true;
        if (/^(?:healthy|warning|critical|good|bad|low|high|open|closed)$/i.test(value)) return true;
        return false;
    }

    isLikelySummaryTitle(text) {
        const value = this.normalizeSnapshotText(text);
        if (!value || value.length > 90) return false;
        if (this.isLikelySummaryValue(value)) return false;
        if (/^[\d\s.,:%₹$€£()+\-]+$/.test(value)) return false;
        if (/^(?:from|to|refresh|help|operations|finance|p&l|begin typing for results|no new notifications)$/i.test(value)) return false;
        return /[A-Za-z]/.test(value);
    }

    isLikelySummaryDetail(text) {
        const value = this.normalizeSnapshotText(text);
        if (!value) return false;
        if (this.isLikelySummaryTitle(value) || this.isLikelySummaryValue(value)) return false;
        if (value.length < 8) return false;
        return /[A-Za-z]/.test(value);
    }

    collectSummaryCards(rootEl) {
        try {
            if (!rootEl) return [];

            const candidates = [];
            const seen = new Set();
            const nodes = rootEl.querySelectorAll('section, article, aside, li, div, button');
            nodes.forEach((el) => {
                try {
                    if (!el || el === rootEl || !this.isVisibleElement(el)) return;
                    if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes((el.tagName || '').toUpperCase())) return;

                    const rawLines = this.normalizeSnapshotText(el.innerText || el.textContent || '')
                        .split(/\n+/)
                        .map(line => this.normalizeSnapshotText(line))
                        .filter(Boolean);

                    if (rawLines.length < 3 || rawLines.length > 16) return;

                    const cleanedLines = [];
                    const lineSeen = new Set();
                    rawLines.forEach((line) => {
                        const normalized = this.normalizeSnapshotText(line);
                        if (!normalized) return;
                        const dedupeKey = normalized.toLowerCase();
                        if (lineSeen.has(dedupeKey)) return;
                        lineSeen.add(dedupeKey);
                        if (/^[^\w₹$€£0-9A-Za-z]+$/.test(normalized)) return;
                        cleanedLines.push(normalized);
                    });

                    if (cleanedLines.length < 3 || cleanedLines.length > 14) return;

                    const titleIndex = cleanedLines.findIndex(line => this.isLikelySummaryTitle(line));
                    if (titleIndex === -1) return;

                    let valueIndex = -1;
                    for (let i = titleIndex + 1; i < cleanedLines.length; i += 1) {
                        if (this.isLikelySummaryValue(cleanedLines[i])) {
                            valueIndex = i;
                            break;
                        }
                    }
                    if (valueIndex === -1) return;

                    const title = cleanedLines[titleIndex];
                    const value = cleanedLines[valueIndex];
                    const detailLines = [];
                    let trend = '';
                    let status = '';

                    cleanedLines.forEach((line, index) => {
                        if (index === titleIndex || index === valueIndex) return;
                        if (/^[→↑↓↔↗↘↙]+\s*\d/.test(line) || /^→/.test(line)) {
                            if (!trend) trend = line;
                            return;
                        }
                        if (/^(healthy|warning|critical|good|bad|low|high)$/i.test(line)) {
                            if (!status) status = line;
                            return;
                        }
                        if (this.isLikelySummaryDetail(line)) {
                            detailLines.push(line);
                        }
                    });

                    const detail = detailLines.slice(0, 3).join(' ');
                    const signature = [title, value, trend, status, detail.slice(0, 120)].join('|').toLowerCase();
                    if (seen.has(signature)) return;
                    seen.add(signature);

                    candidates.push({
                        title,
                        value,
                        trend: trend || null,
                        status: status || null,
                        detail: detail || null,
                        lines: cleanedLines.slice(0, 8),
                    });
                } catch (e) { }
            });

            return candidates.slice(0, 24);
        } catch (e) {
            return [];
        }
    }

    collectWidgetGroupSummaries(group, groupName = '') {
        try {
            if (!group) return [];
            const widgets = group.widgets_list || group.widgets || [];
            const entries = [];
            widgets.forEach((widget, idx) => {
                if (!widget) return;
                const config = typeof widget.get_config === 'function' ? widget.get_config() : {};
                const summary = {
                    widget_group: groupName,
                    index: idx,
                    name: config.name || widget.name || `widget_${idx}`,
                    label: config.label || widget.label || widget.name || `Widget ${idx}`,
                    hidden: !!config.hidden || !!widget.hidden,
                    width: config.width || widget.width || null,
                };
                if (widget.dashboard_chart) {
                    summary.chart = this.summarizeChartLikeValue(widget.dashboard_chart, summary.label);
                } else if (widget.data) {
                    summary.chart = this.summarizeChartLikeValue(widget, summary.label);
                }
                if (config) {
                    summary.config = this.safeClone(config);
                }
                entries.push(summary);
            });
            return entries;
        } catch (e) {
            return [];
        }
    }

    collectChartSummaries(rootEl, candidateObject) {
        const summaries = [];
        const seen = new Set();

        const addSummary = (label, summary) => {
            if (!summary) return;
            const key = JSON.stringify([label || '', summary.chart_type || summary.engine || '', summary.title || summary.label || '']);
            if (seen.has(key)) return;
            seen.add(key);
            summaries.push(summary);
        };

        const maybePushChart = (label, chart) => {
            const summary = this.summarizeChartLikeValue(chart, label);
            addSummary(label, summary);
        };

        if (candidateObject && typeof candidateObject === 'object') {
            const charts = candidateObject.charts;
            if (charts && typeof charts === 'object') {
                Object.entries(charts).forEach(([label, chart]) => maybePushChart(label, chart));
            }

            if (candidateObject.chart_group) {
                this.collectWidgetGroupSummaries(candidateObject.chart_group, 'chart_group').forEach((item) => {
                    addSummary(item.label || item.name || 'chart_group', item.chart || item);
                });
            }
            if (candidateObject.number_card_group) {
                this.collectWidgetGroupSummaries(candidateObject.number_card_group, 'number_card_group').forEach((item) => {
                    addSummary(item.label || item.name || 'number_card_group', item);
                });
            }

            ['dashboard_chart', 'chart', 'charts', 'chart_group', 'number_card_group', 'chart_widget', 'dashboard'].forEach((key) => {
                const value = candidateObject[key];
                if (!value) return;
                if (Array.isArray(value)) {
                    value.slice(0, 8).forEach((item, idx) => maybePushChart(`${key}[${idx}]`, item));
                } else if (typeof value === 'object') {
                    maybePushChart(key, value);
                }
            });
        }

        if (rootEl && window.echarts && typeof window.echarts.getInstanceByDom === 'function') {
            const chartNodes = rootEl.querySelectorAll('canvas');
            chartNodes.forEach((node, index) => {
                try {
                    const instance = window.echarts.getInstanceByDom(node);
                    if (instance) {
                        maybePushChart(`dom:${index}`, instance);
                    }
                } catch (e) { }
            });
        }

        return summaries.slice(0, 12);
    }

    isSparsePageContext(context) {
        try {
            if (!context || typeof context !== 'object') return true;
            if (context.source_type === 'loading') return true;

            const snapshot = context.page_snapshot || context.dashboard_snapshot || {};
            const controls = Array.isArray(snapshot.controls) ? snapshot.controls : (Array.isArray(context.page_controls) ? context.page_controls : []);
            const visibleText = Array.isArray(snapshot.visible_text) ? snapshot.visible_text : (Array.isArray(context.page_visible_text) ? context.page_visible_text : []);
            const charts = Array.isArray(snapshot.charts) ? snapshot.charts : (Array.isArray(context.page_charts) ? context.page_charts : []);
            const summaryCards = Array.isArray(snapshot.summary_cards) ? snapshot.summary_cards : (Array.isArray(context.page_summary_cards) ? context.page_summary_cards : []);
            const fieldValues = context.page_field_values || snapshot.page_field_values || {};

            if (controls.length || visibleText.length || charts.length || summaryCards.length) return false;
            if (fieldValues && typeof fieldValues === 'object' && Object.keys(fieldValues).length) return false;
            if (snapshot.summary || snapshot.metrics || snapshot.kpis || snapshot.dashboard_data || snapshot.data || snapshot.summary_cards) return false;
            return true;
        } catch (e) {
            return true;
        }
    }

    buildObjectPathCandidates(pageName) {
        const normalized = this.normalizePageKey(pageName);
        const underscore = normalized;
        const camel = this.slugToCamel(normalized);
        const direct = (pageName || '').toString().trim();
        const parts = direct.split('-').filter(Boolean);
        const namespace = parts.length > 1 ? parts[0] : normalized;
        const namespaceCamel = this.slugToCamel(namespace);
        const base = parts.length > 1 ? parts.slice(0, -1).join('-') : direct;
        const baseKey = this.normalizePageKey(base);
        const baseCamel = this.slugToCamel(baseKey);

        const paths = [
            ['window', direct],
            ['window', underscore],
            ['window', camel],
            ['window', namespace, 'dashboard'],
            ['window', namespaceCamel, 'dashboard'],
            ['frappe', underscore],
            ['frappe', camel],
            ['frappe', namespace, 'dashboard'],
            ['frappe', namespaceCamel, 'dashboard'],
            ['window', baseKey],
            ['window', baseCamel],
            ['frappe', baseKey],
            ['frappe', baseCamel],
        ];

        if (normalized.endsWith('_dashboard')) {
            const baseDash = normalized.replace(/_dashboard$/, '');
            paths.push(['window', baseDash]);
            paths.push(['window', this.slugToCamel(baseDash)]);
            paths.push(['window', baseDash, 'dashboard']);
            paths.push(['frappe', baseDash]);
            paths.push(['frappe', this.slugToCamel(baseDash)]);
            paths.push(['frappe', baseDash, 'dashboard']);
        }

        return paths;
    }

    resolveObjectPath(pathParts) {
        try {
            let current = window;
            for (const part of pathParts) {
                if (!current) return null;
                current = current[part];
            }
            return current || null;
        } catch (e) {
            return null;
        }
    }

    findDashboardObject(pageName) {
        const candidates = this.buildObjectPathCandidates(pageName);
        for (const parts of candidates) {
            const obj = this.resolveObjectPath(parts);
            if (obj) return obj;
        }
        return null;
    }

    getPageSnapshot(pageObj, pageName = '', candidateObject = null) {
        try {
            const page = pageObj || window.cur_page?.page || null;
            const rootEl = this.getPageRootElement(page);
            const pageObject = candidateObject || this.findDashboardObject(pageName) || page || null;
            const objectControls = this.collectObjectControls(pageObject);
            const domControls = this.collectVisibleControls(rootEl);
            const controlMap = new Map();
            [...objectControls, ...domControls].forEach((control) => {
                if (!control) return;
                const key = [control.fieldname || '', control.label || '', control.fieldtype || ''].join('|');
                if (!controlMap.has(key) || control.source === 'object') {
                    controlMap.set(key, control);
                }
            });
            const pageControls = Array.from(controlMap.values());
            const visibleText = this.collectVisibleText(rootEl);
            const charts = this.collectChartSummaries(rootEl, pageObject);
            const summaryCards = this.collectSummaryCards(rootEl);

            let explicitSnapshot = null;
            const snapshotMethods = [
                pageObject?.get_context_snapshot,
                pageObject?.getContextSnapshot,
                pageObject?.get_dashboard_snapshot,
                pageObject?.getDashboardContext,
                pageObject?.get_context_data,
            ];
            for (const method of snapshotMethods) {
                if (typeof method === 'function') {
                    try {
                        explicitSnapshot = method.call(pageObject, {
                            page_name: pageName,
                            page: page,
                            root: rootEl,
                        });
                        break;
                    } catch (e) { }
                }
            }

            if (explicitSnapshot && typeof explicitSnapshot === 'object') {
                return {
                    kind: explicitSnapshot.kind || (charts.length ? 'dashboard' : 'page'),
                    source: 'explicit_hook',
                    ...this.safeClone(explicitSnapshot),
                };
            }

            const dashboardLike = !!(charts.length || summaryCards.length || pageObject?.charts || pageObject?.summary_cards || pageObject?.filters || pageObject?.lastData || pageObject?.dashboard_data || pageObject?.data || pageObject?.render_dashboard);
            const state = {
                kind: dashboardLike ? 'dashboard' : 'page',
                source: pageObject && pageObject !== page ? 'heuristic_object' : 'dom',
                page_name: pageName || page?.page_name || page?.name || '',
                title: page?.title || page?.page_title || pageName || '',
                controls: pageControls,
                visible_text: visibleText,
                charts: charts,
                summary_cards: summaryCards,
            };

            const objectStateKeys = ['filters', 'filter_values', 'selected_filters', 'lastData', 'dashboard_data', 'data', 'kpis', 'summary', 'metrics'];
            objectStateKeys.forEach((key) => {
                const value = pageObject && pageObject[key];
                if (value === undefined || value === null) return;
                state[key] = this.safeClone(value);
            });

            if (pageObject && typeof pageObject === 'object' && Array.isArray(pageObject.number_cards)) {
                state.number_cards = this.safeClone(pageObject.number_cards.slice(0, 12));
            }

            if (pageObject && typeof pageObject === 'object' && Array.isArray(pageObject.cards) && !state.summary_cards.length) {
                state.summary_cards = this.safeClone(pageObject.cards.slice(0, 12));
            }

            if (pageControls.length && !state.controls.length) {
                state.controls = pageControls;
            }

            return state;
        } catch (e) {
            return {
                kind: 'page',
                source: 'error',
                error: String(e),
                controls: [],
                visible_text: [],
                charts: [],
            };
        }
    }

    getListFilters(listView) {
        try {
            if (!listView) return [];
            const filterArea = listView.filter_area;
            if (filterArea && typeof filterArea.get === 'function') {
                const filters = filterArea.get();
                return Array.isArray(filters) ? this.safeClone(filters) : this.safeClone(filters || []);
            }
            if (Array.isArray(listView.filters)) {
                return this.safeClone(listView.filters);
            }
        } catch (e) {
            return [];
        }
        return [];
    }

    getPageFieldSnapshot(pageObj, pageName = '') {
        try {
            const page = pageObj || window.cur_page?.page || null;
            const ignoreTypes = new Set(['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Fold']);
            const fieldMap = new Map();
            const values = {};

            const addControl = (fieldname, control, source) => {
                if (!control || typeof control.get_value !== 'function') return;
                const df = control.df || {};
                const resolvedFieldname = df.fieldname || fieldname;
                const fieldtype = df.fieldtype || '';
                if (!resolvedFieldname || ignoreTypes.has(fieldtype)) return;

                const value = this.safeClone(control.get_value());
                fieldMap.set(resolvedFieldname, {
                    fieldname: resolvedFieldname,
                    label: df.label || resolvedFieldname,
                    fieldtype: fieldtype,
                    options: ['Link', 'Select', 'Table', 'Dynamic Link'].includes(fieldtype) ? df.options || null : null,
                    value: value,
                    source: source,
                });
                values[resolvedFieldname] = value;
            };

            if (page?.fields_dict) {
                Object.entries(page.fields_dict).forEach(([fallbackKey, control]) => {
                    addControl(fallbackKey, control, 'page_toolbar');
                });
            }

            const customPageKey = (pageName || page?.page_name || page?.name || '').replace(/-/g, '_');
            const customPageInstance =
                (customPageKey && window.frappe && window.frappe[customPageKey]) ||
                (customPageKey && window[customPageKey]) ||
                null;

            if (customPageInstance && typeof customPageInstance === 'object') {
                Object.entries(customPageInstance).forEach(([key, value]) => {
                    if (!value || typeof value.get_value !== 'function' || !value.df) return;
                    addControl(key, value, 'custom_page');
                });
            }

            const fields = Array.from(fieldMap.values());
            const sourceValues = typeof page?.get_form_values === 'function' ? page.get_form_values() : {};
            const mergedValues = this.safeClone(sourceValues || {});
            Object.keys(values).forEach((key) => {
                mergedValues[key] = values[key];
            });

            return {
                field_count: fields.length,
                value_count: mergedValues && typeof mergedValues === 'object' ? Object.keys(mergedValues).length : 0,
                fields: this.safeClone(fields),
                values: mergedValues,
            };
        } catch (e) {
            return { field_count: 0, value_count: 0, fields: [], values: {} };
        }
    }


    getCurrentViewContext() {
        const route = this.getCurrentRoute();
        const routeType = (route[0] || '').toLowerCase();
        const context = {
            route: route,
            source_type: 'unknown',
            label: 'current view',
        };

        if (routeType === 'form' && window.cur_frm) {
            const frm = window.cur_frm;
            const doc = frm.doc || {};
            const doctype = frm.doctype || route[1] || doc.doctype;
            const name = doc.name || route[2] || '';
            const titleField = frm.meta?.title_field || null;
            const titleCandidates = [
                titleField,
                'title',
                'subject',
                'item_name',
                'customer_name',
                'full_name',
                'company_name',
                'name'
            ];
            let titleValue = '';
            for (const fieldname of titleCandidates) {
                if (fieldname && doc[fieldname] !== undefined && doc[fieldname] !== null && doc[fieldname] !== '') {
                    titleValue = doc[fieldname];
                    break;
                }
            }
            const fields = (frm.meta?.fields || [])
                .filter(field => field && field.fieldname && !['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Fold'].includes(field.fieldtype))
                .slice(0, 60)
                .map(field => ({
                    fieldname: field.fieldname,
                    label: field.label || field.fieldname,
                    fieldtype: field.fieldtype,
                    reqd: !!field.reqd,
                    read_only: !!field.read_only,
                    options: ['Link', 'Select', 'Table'].includes(field.fieldtype) ? field.options || null : null,
                }));

            context.source_type = 'form';
            context.doctype = doctype;
            context.name = name;
            context.label = name ? (doctype + ' ' + name) : (doctype || 'current form');
            context.title_field = titleField;
            context.title = titleValue || name || doctype || context.label;
            context.document_title = context.title;
            context.is_dirty = typeof frm.is_dirty === 'function' ? frm.is_dirty() : !!frm.is_dirty;
            context.current_doc = this.safeClone(doc);
            context.meta = {
                doctype: doctype,
                name: name,
                fields: fields,
                field_count: fields.length,
                title_field: titleField,
                title_value: context.title,
            };
            return context;
        }

        if (routeType === 'list' && window.cur_list) {
            const listView = window.cur_list;
            const doctype = listView.doctype || route[1];
            const meta = doctype && frappe.get_meta ? frappe.get_meta(doctype) : null;
            const fields = (meta?.fields || [])
                .filter(field => field && field.fieldname && !['Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button', 'Fold', 'Table', 'Table MultiSelect'].includes(field.fieldtype))
                .slice(0, 20)
                .map(field => field.fieldname);

            const filters = this.getListFilters(listView);
            context.source_type = 'list';
            context.doctype = doctype;
            context.label = doctype ? (doctype + ' list') : 'current list';
            context.filters = filters;
            context.fields = fields;
            context.page_length = listView.page_length || listView.pageLength || 20;
            context.current_filters = filters;
            context.visible_fields = fields;
            return context;
        }

        if ((routeType === 'dashboard-view' || (window.cur_list && window.cur_list.view_name === 'Dashboard')) && window.cur_list) {
            const dashboardView = window.cur_list;
            const doctype = dashboardView.doctype || route[1] || '';
            const dashboardSnapshot = this.getPageSnapshot(dashboardView.page || window.cur_page?.page, doctype, dashboardView);
            context.source_type = 'page';
            context.doctype = doctype;
            context.label = doctype ? (doctype + ' dashboard') : 'dashboard';
            context.page_name = doctype || 'dashboard';
            context.page_kind = 'dashboard';
            context.dashboard_snapshot = dashboardSnapshot;
            context.page_snapshot = dashboardSnapshot;
            context.page_source = dashboardSnapshot.source || 'dashboard_view';
            context.page_controls = dashboardSnapshot.controls || [];
            context.page_visible_text = dashboardSnapshot.visible_text || [];
            context.page_charts = dashboardSnapshot.charts || [];
            context.page_summary_cards = dashboardSnapshot.summary_cards || [];
            context.page_fields = dashboardSnapshot.controls || [];
            context.page_field_count = (dashboardSnapshot.controls || []).length;
            context.page_field_values = {};
            (dashboardSnapshot.controls || []).forEach((item) => {
                if (item && item.fieldname) {
                    context.page_field_values[item.fieldname] = item.value;
                }
            });
            context.page_field_value_count = Object.keys(context.page_field_values || {}).length;
            context.page_summary_card_count = (dashboardSnapshot.summary_cards || []).length;
            return context;
        }

        if (routeType === 'query-report' || routeType === 'report-view' || routeType === 'report') {
            const reportName = route[1] || window.cur_page?.page?.title || window.cur_page?.page?.page_title || '';
            const reportSnapshot = this.getPageSnapshot(window.cur_page?.page, reportName);
            context.source_type = 'page';
            context.page_kind = 'report';
            context.report_name = reportName;
            context.page_name = reportName || 'report';
            context.label = reportName ? (reportName + ' report') : 'current report';
            context.page_snapshot = reportSnapshot;
            context.page_source = reportSnapshot.source || 'report_view';
            context.page_controls = reportSnapshot.controls || [];
            context.page_visible_text = reportSnapshot.visible_text || [];
            context.page_charts = reportSnapshot.charts || [];
            context.page_summary_cards = reportSnapshot.summary_cards || [];
            context.page_fields = reportSnapshot.controls || [];
            context.page_field_count = (reportSnapshot.controls || []).length;
            context.page_field_values = {};
            (reportSnapshot.controls || []).forEach((item) => {
                if (item && item.fieldname) {
                    context.page_field_values[item.fieldname] = item.value;
                }
            });
            context.page_field_value_count = Object.keys(context.page_field_values || {}).length;
            context.page_summary_card_count = (reportSnapshot.summary_cards || []).length;
            return context;
        }

        if (routeType === 'workspace' || routeType === 'workspaces') {
            const workspaceName = route[1] || route[2] || '';
            context.source_type = 'workspace';
            context.workspace_name = workspaceName;
            context.label = workspaceName || 'current workspace';
            return context;
        }

        if (routeType === 'page' || (window.cur_page && window.cur_page.page && window.cur_page.page.name)) {
            const pageName = routeType === 'page' ? (route[1] || route[0]) : window.cur_page.page.name;
            const title = window.cur_page?.page?.title || pageName;
            const pageSnapshot = this.getPageSnapshot(window.cur_page?.page, pageName);
            context.source_type = 'page';
            context.page_name = pageName;
            context.label = title + ' page';
            context.page_snapshot = pageSnapshot;
            context.page_kind = pageSnapshot.kind || (pageSnapshot.charts?.length ? 'dashboard' : 'page');
            context.page_source = pageSnapshot.source || '';
            context.page_controls = pageSnapshot.controls || [];
            context.page_visible_text = pageSnapshot.visible_text || [];
            context.page_charts = pageSnapshot.charts || [];
            context.page_summary_cards = pageSnapshot.summary_cards || [];
            if (pageSnapshot.controls) {
                context.page_fields = pageSnapshot.controls;
                context.page_field_count = pageSnapshot.controls.length;
                context.page_field_values = {};
                (pageSnapshot.controls || []).forEach((item) => {
                    if (item && item.fieldname) {
                        context.page_field_values[item.fieldname] = item.value;
                    }
                });
                context.page_field_value_count = Object.keys(context.page_field_values || {}).length;
            }
            context.page_summary_card_count = (pageSnapshot.summary_cards || []).length;
            return context;
        }

        if (route.length) {
            context.label = route.join(' / ');
        }

        return context;
    }

    async loadContextFiles() {
        if (!this.getModeMeta(this.currentMode).supports_upload) {
            this.contextFiles = [];
            this.updateContextBar();
            return;
        }

        try {
            const r = await frappe.call({
                method: 'ampower_jive.api.get_helpdesk_context',
                args: { session_id: this.sessionId },
                freeze: false
            });
            if (r?.message && !r.message.error) {
                this.contextFiles = r.message.context_files || [];
                this.updateContextBar();
            }
        } catch (e) { }
    }

    async uploadContext(e) {
        if (!this.config.enable_file_upload || !this.getModeMeta(this.currentMode).supports_upload) return;

        const file = e.target?.files?.[0];
        if (!file) return;

        const exts = ['.pdf', '.docx', '.doc', '.csv', '.txt', '.md', '.json'];
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!exts.includes(ext)) {
            frappe.show_alert({ message: `Unsupported file: ${ext}`, indicator: 'orange' });
            e.target.value = '';
            return;
        }

        frappe.show_alert({ message: `Uploading ${file.name}...`, indicator: 'blue' });

        try {
            const fd = new FormData();
            fd.append('file', file);
            fd.append('is_private', '1');
            fd.append('folder', 'Home');

            const up = await fetch('/api/method/upload_file', {
                method: 'POST',
                body: fd,
                headers: { 'X-Frappe-CSRF-Token': frappe.csrf_token }
            });
            const res = await up.json();

            if (!res.message?.file_url) throw new Error('Upload failed');

            const r = await frappe.call({
                method: 'ampower_jive.api.upload_helpdesk_context',
                args: { file_url: res.message.file_url, file_name: res.message.name, session_id: this.sessionId }
            });

            if (r?.message && !r.message.error) {
                frappe.show_alert({ message: `${file.name} ready!`, indicator: 'green' });
                await this.loadContextFiles();
            } else {
                frappe.show_alert({ message: r.message?.message || 'Failed to process file', indicator: 'red' });
            }
        } catch (err) {
            frappe.show_alert({ message: `Failed to upload ${file.name}`, indicator: 'red' });
        }

        e.target.value = '';
    }

    async clearContext() {
        if (!this.getModeMeta(this.currentMode).supports_upload || !this.contextFiles.length) return;

        try {
            await frappe.call({
                method: 'ampower_jive.api.clear_helpdesk_context',
                args: { session_id: this.sessionId }
            });
            this.contextFiles = [];
            this.updateContextBar();
            frappe.show_alert({ message: 'Context cleared', indicator: 'green' });
        } catch (e) {
            frappe.show_alert({ message: 'Failed to clear', indicator: 'red' });
        }
    }

    updateContextBar() {
        const bar = document.getElementById('contextBar');
        const info = document.getElementById('contextInfo');
        const clearBtn = document.querySelector('.jive-context-clear');

        if (!bar || !info) return;

        if (this.getModeMeta(this.currentMode).supports_upload && this.contextFiles.length > 0) {
            bar.classList.add('visible');
            const total = this.contextFiles.reduce((s, f) => s + (f.char_count || 0), 0);
            const chars = total > 1000 ? Math.round(total / 1000) + 'k' : total;
            const names = this.contextFiles.map(f => f.file_name || f.file_url?.split('/').pop() || 'file').slice(0, 2);
            const more = this.contextFiles.length > 2 ? ` +${this.contextFiles.length - 2}` : '';
            info.textContent = `📎 ${names.join(', ')}${more} · ${chars} chars`;
            if (clearBtn) clearBtn.style.display = '';
            return;
        }

        if (this.getModeMeta(this.currentMode).supports_context && this.contextAware) {
            const context = this.getDisplayContext();
            if (this.normalizeMode(this.currentMode) === 'rag' && context.source_type !== 'form') {
                bar.classList.remove('visible');
                if (clearBtn) clearBtn.style.display = '';
                return;
            }
            let details = 'Open a form, list, workspace, or any page to capture context';
            if (context.source_type === 'loading' && context.label) {
                details = context.label;
            } else if (context.source_type === 'form' && context.doctype) {
                details = context.doctype + (context.name ? ' · ' + context.name : '');
            } else if (context.source_type === 'list' && context.doctype) {
                details = context.doctype + ' list';
                if (context.filters && context.filters.length) {
                    details += ' · ' + context.filters.length + ' filter' + (context.filters.length === 1 ? '' : 's');
                }
            } else if (context.source_type === 'workspace' && context.workspace_name) {
                details = context.workspace_name;
            } else if ((context.source_type === 'dashboard' || context.page_kind === 'dashboard') && context.doctype) {
                details = context.doctype + ' dashboard';
            } else if (context.source_type === 'dashboard' || context.page_kind === 'dashboard') {
                details = 'dashboard';
            } else if (context.label) {
                details = context.label;
            }

            bar.classList.add('visible');
            info.textContent = 'Context: ' + details;
            if (clearBtn) clearBtn.style.display = 'none';
            return;
        }

        bar.classList.remove('visible');
        if (clearBtn) clearBtn.style.display = '';
        info.textContent = '0 files loaded';
    }
}
