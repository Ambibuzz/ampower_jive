/**
 * AmPower Jive - Floating Chat Button
 * A beautifully crafted chat button with smooth animations
 * By Ambibuzz Technologies LLP
 */

(function() {
    'use strict';
    
    let buttonCreated = false;
    let container = null;
    let fabVisibilityObserver = null;
    
    const showButton = () => {
        if (container) container.style.display = 'flex';
    };
    
    const hideButton = () => {
        if (container) container.style.display = 'none';
    };
    
    const checkVisibility = () => {
        // Keep the FAB hidden whenever the floating window is visible
        const chatWin = document.getElementById('jive-floating-window');
        if (!chatWin || chatWin.style.display === 'none') {
            showButton();
        } else {
            hideButton();
        }
    };
    
    const init = () => {
        if (typeof frappe === 'undefined') {
            setTimeout(init, 100);
            return;
        }
        
        frappe.call({
            method: 'ampower_jive.api.get_jive_config',
            async: true,
            callback: (r) => {
                const config = r?.message || {};
                const isActive = config.active;
                const setupRequired = config.setup_required;
                const hasAccess = config.has_access;  // Can USE Jive (has Jive User role)
                const isAdmin = config.is_admin;       // Can CONFIGURE Jive (System Manager)
                
                // Determine button state based on permissions and config
                // States: 'active', 'setup', 'disabled', 'disabled_user', 'admin_no_access'
                let buttonState = 'active';
                
                // Check permissions and global enabled status
                if (!hasAccess && !isAdmin) {
                    // User has no access and is not admin
                    return;
                }
                
                if (!isActive) {
                    // Jive is globally disabled via 'Ampower Jive Enabled ?'
                        return;
                }
                
                if (isAdmin && !hasAccess) {
                    // Admin without Jive User role - can configure but not use
                    if (setupRequired) {
                        buttonState = 'setup';
                    } else {
                        // Jive is active but admin doesn't have Jive User role
                        buttonState = 'admin_no_access';
                    }
                } else if (hasAccess) {
                    // User has Jive User role
                    if (setupRequired && isAdmin) {
                        buttonState = 'setup';
                    } else {
                        buttonState = 'active';
                    }
                }
                
                // Create button with appropriate state
                createButton(buttonState);
                checkVisibility();
            },
            error: () => {
                // On error, still show button for System Managers to configure
                if (frappe.user_roles && frappe.user_roles.includes('System Manager')) {
                    createButton('setup');
                    checkVisibility();
                }
            }
        });
    };
    
    const createButton = (state = 'active') => {
        if (buttonCreated) return;
        buttonCreated = true;
        
        // State can be: 'active', 'setup', 'disabled', 'disabled_user', 'admin_no_access'
        const isSetup = state === 'setup';
        const isDisabled = state === 'disabled';
        const isDisabledUser = state === 'disabled_user';
        const isAdminNoAccess = state === 'admin_no_access';
        const isActive = state === 'active';
        
        const css = document.createElement('style');
        css.textContent = `
            /* Maximized state styles */
            #jive-floating-window.jive-maximized {
                bottom: 0 !important;
                right: 0 !important;
                width: 100vw !important;
                height: 100vh !important;
                max-height: 100vh !important;
                max-width: 100vw !important;
                border-radius: 0 !important;
                box-shadow: none !important;
                z-index: 100000 !important;
            }
            
            #jive-floating-window.jive-maximized .jive {
                border-radius: 0;
                box-shadow: none;
                height: 100vh;
            }
            
            #jive-floating-window.jive-maximized .jive-sidebar {
                position: relative;
                transform: translateX(0);
                box-shadow: none;
                width: 275px;
                padding-left: 15px;
            }
            
            #jive-floating-window.jive-maximized .jive-new-btn[title="Close history"],
            #jive-floating-window.jive-maximized .jive-header-btn[title="Toggle History"] {
                display: none !important;
            }

            body.jive-desk-hidden .navbar,
            body.jive-desk-hidden #body,
            body.jive-desk-hidden .page-container,
            body.jive-desk-hidden footer,
            body.jive-desk-hidden .modal-backdrop,
            body.jive-desk-hidden #sidebar {
                display: none !important;
            }
            
            body.jive-desk-hidden {
                overflow: hidden !important;
            }

            @keyframes jive-float {
                0%, 100% { transform: translateY(0px); }
                50% { transform: translateY(-6px); }
            }
            @keyframes jive-pulse-ring {
                0% { transform: scale(1); opacity: 0.8; }
                100% { transform: scale(1.5); opacity: 0; }
            }
            @keyframes jive-bounce-in {
                0% { transform: scale(0) rotate(-45deg); opacity: 0; }
                50% { transform: scale(1.1) rotate(5deg); }
                70% { transform: scale(0.95) rotate(-2deg); }
                100% { transform: scale(1) rotate(0deg); opacity: 1; }
            }
            @keyframes jive-tooltip-in {
                0% { opacity: 0; transform: translateX(10px) scale(0.9); }
                100% { opacity: 1; transform: translateX(0) scale(1); }
            }
            @keyframes jive-shimmer {
                0% { background-position: -200% center; }
                100% { background-position: 200% center; }
            }
            
            #jive-fab-container {
                position: fixed;
                bottom: 28px;
                right: 28px;
                z-index: 99999;
                display: flex;
                align-items: center;
                gap: 16px;
                pointer-events: none;
            }
            
            #jive-fab {
                position: relative;
                width: 60px;
                height: 60px;
                border-radius: 20px;
                background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a855f7 100%);
                border: none;
                cursor: pointer;
                box-shadow: 
                    0 4px 15px rgba(99, 102, 241, 0.4),
                    0 8px 30px rgba(139, 92, 246, 0.3),
                    inset 0 1px 1px rgba(255,255,255,0.2);
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                animation: jive-bounce-in 0.6s ease-out, jive-float 3s ease-in-out 1s infinite;
                overflow: hidden;
                pointer-events: auto;
            }
            
            #jive-fab::before {
                content: '';
                position: absolute;
                inset: 0;
                border-radius: 20px;
                background: linear-gradient(90deg, 
                    transparent 0%, 
                    rgba(255,255,255,0.2) 50%, 
                    transparent 100%);
                background-size: 200% 100%;
                opacity: 0;
                transition: opacity 0.3s;
            }
            
            #jive-fab:hover::before {
                opacity: 1;
                animation: jive-shimmer 1.5s infinite;
            }
            
            #jive-fab:hover {
                transform: scale(1.1) rotate(-5deg);
                box-shadow: 
                    0 8px 25px rgba(99, 102, 241, 0.5),
                    0 12px 40px rgba(139, 92, 246, 0.4);
                border-radius: 24px;
            }
            
            #jive-fab:active {
                transform: scale(0.95);
                transition: transform 0.1s;
            }
            
            #jive-fab-pulse {
                position: absolute;
                inset: 0;
                border-radius: 20px;
                border: 2px solid rgba(139, 92, 246, 0.6);
                animation: jive-pulse-ring 2s ease-out infinite;
                pointer-events: none;
            }
            
            #jive-fab-logo {
                width: 28px;
                height: 28px;
                background: rgba(255,255,255,0.2);
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                font-weight: 700;
                color: white;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                z-index: 1;
                text-shadow: 0 1px 2px rgba(0,0,0,0.2);
            }
            
            #jive-fab:hover #jive-fab-logo {
                transform: scale(1.1);
            }
            
            #jive-tooltip {
                background: linear-gradient(135deg, #1e1e42 0%, #2d2d6d 100%);
                padding: 14px 18px;
                border-radius: 16px;
                box-shadow: 
                    0 10px 40px rgba(0,0,0,0.3),
                    0 2px 10px rgba(99, 102, 241, 0.2),
                    inset 0 1px 1px rgba(255,255,255,0.05);
                max-width: 240px;
                opacity: 0;
                pointer-events: none;
                transform: translateX(10px);
                transition: all 0.3s ease;
                border: 1px solid rgba(99, 102, 241, 0.2);
            }
            
            #jive-tooltip.show {
                opacity: 1;
                transform: translateX(0);
                animation: jive-tooltip-in 0.4s ease-out;
                pointer-events: auto;
            }
            
            #jive-tooltip-header {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 8px;
            }
            
            #jive-tooltip-avatar {
                width: 32px;
                height: 32px;
                border-radius: 10px;
                background: linear-gradient(135deg, #6366f1, #a855f7);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 14px;
                font-weight: 700;
                color: white;
            }
            
            #jive-tooltip-info {
                display: flex;
                flex-direction: column;
            }
            
            #jive-tooltip-name {
                font-weight: 700;
                font-size: 14px;
                color: #f1f5f9;
                letter-spacing: -0.3px;
            }
            
            #jive-tooltip-brand {
                font-size: 10px;
                color: #6b7280;
            }
            
            #jive-tooltip-status {
                display: flex;
                align-items: center;
                gap: 6px;
                font-size: 11px;
                color: #10b981;
                margin-bottom: 8px;
            }
            
            #jive-tooltip-status::before {
                content: '';
                width: 6px;
                height: 6px;
                background: #10b981;
                border-radius: 50%;
                animation: jive-pulse-ring 1.5s infinite;
            }
            
            #jive-tooltip-text {
                font-size: 13px;
                color: #94a3b8;
                line-height: 1.5;
            }
            
            #jive-tooltip-cta {
                margin-top: 12px;
                padding: 8px 14px;
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                border-radius: 8px;
                font-size: 12px;
                font-weight: 600;
                color: white;
                display: inline-flex;
                align-items: center;
                gap: 6px;
                transition: all 0.2s;
            }
            
            #jive-tooltip:hover #jive-tooltip-cta {
                transform: translateX(4px);
            }
            
            #jive-badge {
                position: absolute;
                top: -4px;
                right: -4px;
                width: 18px;
                height: 18px;
                background: #ef4444;
                border-radius: 50%;
                border: 3px solid #0a0a1a;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 10px;
                font-weight: 700;
                color: white;
                opacity: 0;
                transform: scale(0);
                transition: all 0.3s ease;
            }
            
            #jive-badge.show {
                opacity: 1;
                transform: scale(1);
            }
        `;
        document.head.appendChild(css);
        
        container = document.createElement('div');
        container.id = 'jive-fab-container';
        
        // Define tooltip content based on state
        let tooltipContent, buttonStyle, pulseStyle, logoIcon, clickAction;
        
        if (isSetup) {
            // Setup Required - Orange (Admin only)
            tooltipContent = `
                <div id="jive-tooltip-header">
                    <div id="jive-tooltip-avatar" style="background: linear-gradient(135deg, #f59e0b, #d97706);">⚙</div>
                    <div id="jive-tooltip-info">
                        <div id="jive-tooltip-name">Jive AI</div>
                        <div id="jive-tooltip-brand">by Ambibuzz</div>
                    </div>
                </div>
                <div id="jive-tooltip-status" style="color: #f59e0b;">Setup Required</div>
                <div id="jive-tooltip-text">Configure your API key in Jive Config to start using the AI assistant.</div>
                <div id="jive-tooltip-cta" style="background: linear-gradient(135deg, #f59e0b, #d97706);">
                    Configure Now
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M5 12h14M12 5l7 7-7 7"/>
                    </svg>
                </div>
            `;
            buttonStyle = 'background: linear-gradient(135deg, #f59e0b 0%, #d97706 50%, #b45309 100%);';
            pulseStyle = 'border-color: rgba(245, 158, 11, 0.6);';
            logoIcon = '⚙';
            clickAction = '/app/jive-config';
        } else if (isDisabled) {
            // Disabled - Red (Admin can enable)
            tooltipContent = `
                <div id="jive-tooltip-header">
                    <div id="jive-tooltip-avatar" style="background: linear-gradient(135deg, #ef4444, #dc2626);">A</div>
                    <div id="jive-tooltip-info">
                        <div id="jive-tooltip-name">Jive AI</div>
                        <div id="jive-tooltip-brand">by Ambibuzz</div>
                    </div>
                </div>
                <div id="jive-tooltip-status" style="color: #ef4444;">Disabled</div>
                <div id="jive-tooltip-text">Jive AI is currently disabled. Enable it in Jive Config to start chatting.</div>
                <div id="jive-tooltip-cta" style="background: linear-gradient(135deg, #ef4444, #dc2626);">
                    Enable Jive
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M5 12h14M12 5l7 7-7 7"/>
                    </svg>
                </div>
            `;
            buttonStyle = 'background: linear-gradient(135deg, #ef4444 0%, #dc2626 50%, #b91c1c 100%);';
            pulseStyle = 'border-color: rgba(239, 68, 68, 0.6);';
            logoIcon = 'A';
            clickAction = '/app/jive-config';
        } else if (isDisabledUser) {
            // Disabled - Gray (Regular user, can't enable)
            tooltipContent = `
                <div id="jive-tooltip-header">
                    <div id="jive-tooltip-avatar" style="background: linear-gradient(135deg, #6b7280, #4b5563);">A</div>
                    <div id="jive-tooltip-info">
                        <div id="jive-tooltip-name">Jive AI</div>
                        <div id="jive-tooltip-brand">by Ambibuzz</div>
                    </div>
                </div>
                <div id="jive-tooltip-status" style="color: #6b7280;">Currently Unavailable</div>
                <div id="jive-tooltip-text">Jive AI is currently disabled by your administrator. Please check back later.</div>
            `;
            buttonStyle = 'background: linear-gradient(135deg, #6b7280 0%, #4b5563 50%, #374151 100%); cursor: not-allowed;';
            pulseStyle = 'border-color: rgba(107, 114, 128, 0.6);';
            logoIcon = 'A';
            clickAction = null; // No action for disabled user
        } else if (isAdminNoAccess) {
            // Admin can configure but doesn't have Jive User role - Blue
            tooltipContent = `
                <div id="jive-tooltip-header">
                    <div id="jive-tooltip-avatar" style="background: linear-gradient(135deg, #3b82f6, #1d4ed8);">⚙</div>
                    <div id="jive-tooltip-info">
                        <div id="jive-tooltip-name">Jive AI</div>
                        <div id="jive-tooltip-brand">by Ambibuzz</div>
                    </div>
                </div>
                <div id="jive-tooltip-status" style="color: #3b82f6;">Admin Access Only</div>
                <div id="jive-tooltip-text">You can configure Jive, but need "Jive User" role to use the chat. Assign yourself the role in User settings.</div>
                <div id="jive-tooltip-cta" style="background: linear-gradient(135deg, #3b82f6, #1d4ed8);">
                    Open Config
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M5 12h14M12 5l7 7-7 7"/>
                    </svg>
                </div>
            `;
            buttonStyle = 'background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 50%, #1e40af 100%);';
            pulseStyle = 'border-color: rgba(59, 130, 246, 0.6);';
            logoIcon = '⚙';
            clickAction = '/app/jive-config';
        } else {
            // Active - Purple
            tooltipContent = `
                <div id="jive-tooltip-header">
                    <div id="jive-tooltip-avatar">A</div>
                    <div id="jive-tooltip-info">
                        <div id="jive-tooltip-name">Jive AI</div>
                        <div id="jive-tooltip-brand">by Ambibuzz</div>
                    </div>
                </div>
                <div id="jive-tooltip-status">Online</div>
                <div id="jive-tooltip-text">Your intelligent assistant for ERPNext. Ask questions, query data, or get help!</div>
                <div id="jive-tooltip-cta">
                    Start chatting
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M5 12h14M12 5l7 7-7 7"/>
                    </svg>
                </div>
            `;
            buttonStyle = '';
            pulseStyle = '';
            logoIcon = 'A';
            clickAction = 'open_widget';
        }
        
        container.innerHTML = `
            <div id="jive-tooltip">${tooltipContent}</div>
            <button id="jive-fab" aria-label="Open Jive AI Assistant by Ambibuzz" ${buttonStyle ? `style="${buttonStyle}"` : ''}>
                <div id="jive-fab-pulse" ${pulseStyle ? `style="${pulseStyle}"` : ''}></div>
                <div id="jive-fab-logo">${logoIcon}</div>
                <div id="jive-badge"></div>
            </button>
        `;
        document.body.appendChild(container);
        
        const btn = document.getElementById('jive-fab');
        const tooltip = document.getElementById('jive-tooltip');
        
        // Show tooltip after delay
        setTimeout(() => {
            tooltip.classList.add('show');
            setTimeout(() => tooltip.classList.remove('show'), 6000);
        }, 2500);
        
        container.addEventListener('mouseenter', () => tooltip.classList.add('show'));
        container.addEventListener('mouseleave', () => tooltip.classList.remove('show'));
        btn.addEventListener('click', () => {
            if (!clickAction) {
                // No action for this state (e.g., disabled_user)
                return;
            }
            btn.style.transform = 'scale(0.9)';
            setTimeout(() => {
                if (clickAction === 'open_widget') {
                    btn.style.transform = '';
                    let chatWin = document.getElementById('jive-floating-window');
                    if (!chatWin) {
                        chatWin = document.createElement('div');
                        chatWin.id = 'jive-floating-window';
                        Object.assign(chatWin.style, {
                            position: 'fixed',
                            bottom: '100px',
                            right: '28px',
                            width: '400px',
                            height: '80vh',
                            maxHeight: '800px',
                            maxWidth: 'calc(100vw - 56px)', // Make responsive
                            zIndex: '99998',
                            display: 'none',
                            opacity: '0',
                            transition: 'opacity 0.2s ease, transform 0.2s ease',
                            transform: 'translateY(20px)',
                            borderRadius: '16px',
                            boxShadow: '0 10px 40px rgba(0,0,0,0.3)',
                            overflow: 'hidden'
                        });
                        document.body.appendChild(chatWin);

                        if (window.MutationObserver && !fabVisibilityObserver) {
                            fabVisibilityObserver = new MutationObserver(() => checkVisibility());
                            fabVisibilityObserver.observe(chatWin, { attributes: true, attributeFilter: ['style', 'class'] });
                        }

                        const initJive = (retries = 5) => {
                            if (window.JiveChat) {
                                window.jiveChat = new window.JiveChat(chatWin);
                                return;
                            }

                            if (retries === 0) {
                                chatWin.innerHTML = '<div style="padding: 20px; color: white;">JiveChat failed to load. Please refresh.</div>';
                                return;
                            }

                            console.warn("JiveChat not loaded yet, retrying...");
                            setTimeout(() => initJive(retries - 1), 100);
                        };

                        initJive();
                    }
                    
                    if (!window.toggleJiveChat) {
                        window.toggleJiveChat = () => {
                            let chatWin = document.getElementById('jive-floating-window');
                            let fabBtn = document.getElementById('jive-fab-container');
                            
                            if (!chatWin) return;
                            
                            if (chatWin.style.display === 'none') {
                                chatWin.style.display = 'block';
                                chatWin.style.pointerEvents = 'auto'; // Ensure clicks work correctly when visible
                                void chatWin.offsetWidth; // Trigger reflow
                                chatWin.style.opacity = '1';
                                chatWin.style.transform = 'translateY(0)';

                                if (window.jiveChat && typeof window.jiveChat.newChat === 'function') {
                                    window.jiveChat.newChat();
                                }
                                
                                // Hide FAB
                                if (fabBtn) {
                                    fabBtn.style.transition = 'opacity 0.2s';
                                    fabBtn.style.opacity = '0';
                                    fabBtn.style.pointerEvents = 'none';
                                    setTimeout(() => fabBtn.style.display = 'none', 200);
                                }
                                checkVisibility();
                            } else {
                                // If maximized, restore desk first
                                if (window.jiveChatMaximized) {
                                    chatWin.classList.remove('jive-maximized');
                                    document.body.classList.remove('jive-desk-hidden');
                                    window.jiveChatMaximized = false;
                                    // Update the maximize/minimize button icon
                                    const maxBtn = chatWin.querySelector('.jive-maximize-btn');
                                    if (maxBtn) {
                                        maxBtn.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
                                        maxBtn.title = 'Maximize';
                                    }
                                }
                                
                                chatWin.style.pointerEvents = 'none'; // Prevent any lingering clicks
                                chatWin.style.opacity = '0';
                                chatWin.style.transform = 'translateY(20px)';
                                setTimeout(() => chatWin.style.display = 'none', 200);
                                
                                // Show FAB
                                if (fabBtn) {
                                    fabBtn.style.display = 'flex';
                                    void fabBtn.offsetWidth;
                                    fabBtn.style.opacity = '1';
                                    fabBtn.style.pointerEvents = 'none'; // Keep container unclickable, relying on its children having auto
                                }
                                checkVisibility();
                            }
                        };
                    }
                    
                    // Maximize: expand floating window to full screen, hide desk
                    if (!window.maximizeJiveChat) {
                        window.maximizeJiveChat = () => {
                            let chatWin = document.getElementById('jive-floating-window');
                            if (!chatWin) return;
                            
                            chatWin.classList.add('jive-maximized');
                            document.body.classList.add('jive-desk-hidden');
                            window.jiveChatMaximized = true;
                            
                            // Update button to show minimize icon
                            const maxBtn = chatWin.querySelector('.jive-maximize-btn');
                            if (maxBtn) {
                                maxBtn.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
                                maxBtn.title = 'Minimize to floating window';
                            }
                        };
                    }
                    
                    // Minimize: restore floating window, show desk, keep chat open
                    if (!window.minimizeJiveChat) {
                        window.minimizeJiveChat = () => {
                            let chatWin = document.getElementById('jive-floating-window');
                            if (!chatWin) return;
                            
                            chatWin.classList.remove('jive-maximized');
                            document.body.classList.remove('jive-desk-hidden');
                            window.jiveChatMaximized = false;
                            
                            // Update button to show maximize icon
                            const maxBtn = chatWin.querySelector('.jive-maximize-btn');
                            if (maxBtn) {
                                maxBtn.innerHTML = '<svg viewBox="0 0 24 24"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
                                maxBtn.title = 'Maximize';
                            }
                        };
                    }
                    
                    // Toggle maximize/minimize
                    if (!window.toggleMaximizeJiveChat) {
                        window.toggleMaximizeJiveChat = () => {
                            if (window.jiveChatMaximized) {
                                window.minimizeJiveChat();
                            } else {
                                window.maximizeJiveChat();
                            }
                        };
                    }
                    
                    window.toggleJiveChat();
                } else {
                    window.location.href = clickAction;
                }
            }, 150);
        });
    };
    
    document.readyState === 'loading' 
        ? document.addEventListener('DOMContentLoaded', init) 
        : init();
})();
