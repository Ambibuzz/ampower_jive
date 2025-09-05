frappe.pages['mcp-dashboard'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'MCP Dashboard',
        single_column: true
    });

    frappe.dom.set_style(`
        .mcp-interface { padding: 20px; background: #f8f9fa; min-height: 600px; }
        .mcp-card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .mcp-tabs { display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 1px solid #e9ecef; }
        .mcp-tab { padding: 10px 20px; cursor: pointer; border: none; background: none; border-bottom: 2px solid transparent; font-weight: 500; color: #6c757d; }
        .mcp-tab.active { color: #007bff; border-bottom-color: #007bff; }
        .mcp-tab:hover { color: #007bff; }
        .mcp-form-group { margin-bottom: 15px; }
        .mcp-form-group label { display: block; margin-bottom: 5px; font-weight: 500; color: #495057; }
        .mcp-form-group input, .mcp-form-group select, .mcp-form-group textarea {
            width: 100%; padding: 8px 12px; border: 1px solid #ced4da; border-radius: 4px; font-size: 14px;
        }
        .mcp-btn { background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: 500; margin-right: 10px; }
        .mcp-btn:hover { background: #0056b3; }
        .mcp-btn:disabled { background: #6c757d; cursor: not-allowed; }
        .mcp-btn.secondary { background: #6c757d; }
        .mcp-btn.secondary:hover { background: #545b62; }
        .mcp-result { 
            background: #f8f9fa; 
            border: 1px solid #e9ecef; 
            border-radius: 4px; 
            padding: 15px; 
            font-size: 14px; 
            line-height: 1.5;
            max-height: 500px; 
            overflow-y: auto; 
        }
        .mcp-result h1, .mcp-result h2, .mcp-result h3, .mcp-result h4, .mcp-result h5, .mcp-result h6 {
            margin-top: 1rem;
            margin-bottom: 0.5rem;
        }
        .mcp-result p { margin-bottom: 1rem; }
        .mcp-result ul, .mcp-result ol { margin-bottom: 1rem; padding-left: 1.5rem; }
        .mcp-result li { margin-bottom: 0.25rem; }
        .mcp-result code { 
            background: #e9ecef; 
            padding: 2px 4px; 
            border-radius: 3px; 
            font-family: 'Monaco', 'Consolas', monospace;
            font-size: 0.9em;
        }
        .mcp-result pre { 
            background: #f1f3f4; 
            padding: 1rem; 
            border-radius: 4px; 
            overflow-x: auto; 
            margin-bottom: 1rem;
        }
        .mcp-result pre code { 
            background: none; 
            padding: 0; 
        }
        .mcp-result blockquote {
            border-left: 4px solid #007bff;
            margin: 1rem 0;
            padding-left: 1rem;
            color: #6c757d;
        }
        .mcp-result table {
            border-collapse: collapse;
            width: 100%;
            margin-bottom: 1rem;
        }
        .mcp-result th, .mcp-result td {
            border: 1px solid #dee2e6;
            padding: 0.5rem;
            text-align: left;
        }
        .mcp-result th {
            background-color: #f8f9fa;
            font-weight: bold;
        }
        .mcp-error { background: #f8d7da; border-color: #f5c6cb; color: #721c24; }
        .mcp-success { background: #d1edff; border-color: #bee5eb; color: #0c5460; }
        
        #gdrive-loader-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0;
            width: 100vw; height: 100vh;
            background: rgba(0, 0, 0, 0.5);
            z-index: 9999;
            align-items: center;
            justify-content: center;
        }
        
        .loader-content {
            background: white;
            padding: 30px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #007bff;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        @media (max-width: 968px) { 
            .mcp-tabs { flex-wrap: wrap; }
        }

        .mcp-feedback {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }

        .mcp-feedback button {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 5px;
            border: none;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            font-weight: 500;
            transition: background 0.3s ease;
        }

        .mcp-feedback .like-btn {
            background: #28a745;
            color: white;
        }

        .mcp-feedback .like-btn:hover {
            background: #218838;
        }

        .mcp-feedback .dislike-btn {
            background: #dc3545;
            color: white;
        }

        .mcp-feedback .dislike-btn:hover {
            background: #c82333;
        }



        [data-tab="gdrive"], 
            #tab-gdrive {
                display: none !important;
    `);

    new MCPInterface(page);
};

const storedTime = localStorage.getItem('jive_doc_time');
if (storedTime && Date.now() - storedTime < 20 * 60 * 1000) {
    window.doc_name = localStorage.getItem('jive_doc_name');
} else {
    localStorage.removeItem('jive_doc_name');
    localStorage.removeItem('jive_doc_time');
    window.doc_name = null;
}

function saveDocName(name) {
    window.doc_name = name;
    localStorage.setItem('jive_doc_name', name);
    localStorage.setItem('jive_doc_time', Date.now());
}



class MCPInterface {
    constructor(page) {
        this.page = page;
        this.current_tab = 'question';
        this.init();
    }

    init() {
        this.loadMarkdownLibrary();
        this.render();
        this.bind_events();
    }

    loadMarkdownLibrary() {
        return new Promise((resolve) => {
            if (typeof marked !== 'undefined') {
                resolve();
                return;
            }

            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js';
            script.onload = () => resolve();
            document.head.appendChild(script);
        });
    }

    render() {
        this.page.main.html(`
            <div class="mcp-interface">
                <div class="mcp-card">
                    <h3>MCP Server Interface</h3>
                    <p>Interact with the Model Context Protocol server for Frappe operations and Google Drive</p>
                </div>

                <div class="mcp-tabs">
                    <button class="mcp-tab active" data-tab="question">Ask Question</button>
                    <button class="mcp-tab" data-tab="gdrive">Google Drive</button>
                </div>

                <div class="mcp-content">
                    ${this.render_question_tab()}
                    ${this.render_gdrive_tab()}
                </div>

                <div class="mcp-card">
                    <h4>Results</h4>
                    <div class="mcp-result" id="mcp-result">Ready to execute MCP operations...</div>
                </div>
            </div>

            <div id="gdrive-loader-overlay">
                <div class="loader-content">
                    <div class="spinner"></div>
                    <h4>Processing, please wait...</h4>
                </div>
            </div>
        `);

        this.show_tab('question');
    }

    render_question_tab() {
        return `
            <div class="mcp-card mcp-tab-content" id="tab-question">
                <h4>Ask a Question</h4>
                <div class="mcp-form-group">
                    <label>Your Question</label>
                    <textarea id="user-question" rows="4" placeholder="Enter your question here..." style="resize: vertical;"></textarea>
                </div>
                <button class="mcp-btn" onclick="mcp_interface.ask_question()">Ask Question</button>
                <button class="mcp-btn secondary" onclick="mcp_interface.clear_result()">Clear</button>
            </div>
        `;
    }

    render_gdrive_tab() {
        return `
            <div class="mcp-card mcp-tab-content" id="tab-gdrive" style="display: none;">
                <h4>Communicate with Google Drive File</h4>
                <div class="mcp-form-group">
                    <label>Select File</label>
                    <select id="gdrive-file-selector">
                        <option value="">Select a file...</option>
                    </select>
                </div>
                <div class="mcp-form-group">
                    <label>Your Message</label>
                    <textarea id="gdrive-mcp-prompt" rows="4" placeholder="Enter your message about the file..." style="resize: vertical;"></textarea>
                </div>
                <button class="mcp-btn" onclick="mcp_interface.send_gdrive_prompt()">Send</button>
                <button class="mcp-btn secondary" onclick="mcp_interface.refresh_gdrive_files()">Refresh Files</button>
                <button class="mcp-btn secondary" onclick="mcp_interface.clear_result()">Clear</button>
            </div>
        `;
    }

    bind_events() {
        $(document).on('click', '.mcp-tab', (e) => {
            const tab = $(e.target).data('tab');
            this.show_tab(tab);
        });

        $(document).on('keydown', '#user-question', (e) => {
            if (e.ctrlKey && e.keyCode === 13) {
                this.ask_question();
            }
        });

        $(document).on('keydown', '#gdrive-mcp-prompt', (e) => {
            if (e.ctrlKey && e.keyCode === 13) {
                this.send_gdrive_prompt();
            }
        });

        window.mcp_interface = this;
    }

    show_tab(tab_name) {
        $('.mcp-tab').removeClass('active');
        $(`.mcp-tab[data-tab="${tab_name}"]`).addClass('active');
        $('.mcp-tab-content').hide();
        $(`#tab-${tab_name}`).show();
        this.current_tab = tab_name;

        if (tab_name === 'gdrive' && $('#gdrive-file-selector option').length <= 1) {
            this.list_gdrive_files();
        }
    }

    async ask_question() {
        const question = $('#user-question').val().trim();
        if (!question) {
            frappe.msgprint('Please enter a question');
            return;
        }

        this.show_loading();

        const generateSessionId = () => {
            const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
            let result = '';
            for (let i = 0; i < 32; i++) {
                result += chars.charAt(Math.floor(Math.random() * chars.length));
            }
            return result;
        };

        try {
            const sessionId = generateSessionId();
            const url = await frappe.db.get_single_value('Jive Config', 'n8n_webhook_url');
            if (!url) {
                throw new Error('n8n_webhook_url is not set in Jive Config');
            }
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    chatInput: question,
                    sessionId: sessionId
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const respData = await response.json();

            let data = null;

            if (respData && respData.output) {
                data = respData.output;
            } else if (respData && respData.result) {
                if (respData.result.content && Array.isArray(respData.result.content) && respData.result.content.length > 0) {
                    data = respData.result.content[0].text;
                } else if (respData.result.text) {
                    data = respData.result.text;
                } else {
                    data = respData.result;
                }
            } else {
                data = respData;
            }

            if (!data) {
                throw new Error('No data received from server');
            }

            let parsedData = {};
            let finalData = data;

            try {
                parsedData = typeof data === 'string' ? JSON.parse(data) : data;
                finalData = parsedData.response || parsedData.output || parsedData.text || data;
            } catch (e) {
                finalData = data;
            }

            let feedbackPayload = {
                responseText: finalData,
                tool: parsedData.tool || '',
                prompt: parsedData.prompt || ''
            };

            this.lastFeedbackData = feedbackPayload;
            this.show_result(finalData, 'success');


            console.log("Feedback Payload:", feedbackPayload);

            this.lastFeedbackData = feedbackPayload;

            this.show_result(parsedData.response || data, 'success');

        } catch (err) {
            console.error('Error in ask_question:', err);
            this.show_result(err.message || 'An error occurred while processing your question', 'error');
        }
    }

    async list_gdrive_files() {
        this.show_loading();

        try {
            const response = await frappe.call({
                method: 'ampower_jive.mcp.api.list_gdrive_files'
            });

            this.show_result("Google Drive files loaded successfully.", "success");

            let text = "[]";
            if (response && response.message && response.message.result) {
                if (response.message.result.contents && Array.isArray(response.message.result.contents) && response.message.result.contents.length > 0) {
                    text = response.message.result.contents[0].text || "[]";
                } else if (response.message.result.text) {
                    text = response.message.result.text;
                } else if (typeof response.message.result === 'string') {
                    text = response.message.result;
                }
            }

            const files = JSON.parse(text);
            const dropdown = $('#gdrive-file-selector');
            dropdown.empty();
            dropdown.append('<option value="">Select a file...</option>');

            if (Array.isArray(files)) {
                files.forEach(file => {
                    dropdown.append(
                        `<option value="${file.id}">${file.name} (${file.mimeType})</option>`
                    );
                });
            }

        } catch (err) {
            console.error('Error in list_gdrive_files:', err);
            this.show_result(err.message || 'An error occurred while loading Google Drive files', 'error');
        }
    }

    async refresh_gdrive_files() {
        await this.list_gdrive_files();
    }

    async send_gdrive_prompt() {
        const prompt = $('#gdrive-mcp-prompt').val().trim();
        const file_id = $('#gdrive-file-selector').val();

        if (!file_id) {
            this.show_result("Please select a file first.", "error");
            return;
        }

        if (!prompt) {
            this.show_result("Please enter a message.", "error");
            return;
        }

        this.show_loading();
        this.show_loader();

        try {
            const response = await frappe.call({
                method: 'ampower_jive.mcp.api.chat_with_gdrive_file',
                args: {
                    file_id,
                    prompt
                }
            });

            await this.show_gdrive_result(response.message, 'success');

        } catch (err) {
            console.error('Error in send_gdrive_prompt:', err);
            this.show_result(err.message || 'An error occurred while processing your request', 'error');
        } finally {
            this.hide_loader();
        }
    }

    async renderMarkdown(content, type = 'success') {
        await this.loadMarkdownLibrary();

        const el = $('#mcp-result');
        el.removeClass('mcp-error mcp-success');
        el.addClass(type === 'error' ? 'mcp-error' : 'mcp-success');

        if (content == null || content === '') {
            content = type === 'error' ? 'An error occurred' : 'No data available';
        }

        const textContent = typeof content === 'object' ? JSON.stringify(content, null, 2) : String(content);

        try {
            if (typeof marked !== 'undefined') {
                marked.setOptions({
                    breaks: true,
                    gfm: true,
                    sanitize: false
                });

                const html = marked.parse(textContent);
                el.html(html);
            } else {
                const html = textContent
                    .replace(/\n\n/g, '</p><p>')
                    .replace(/\n/g, '<br>')
                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                    .replace(/\*(.*?)\*/g, '<em>$1</em>')
                    .replace(/`(.*?)`/g, '<code>$1</code>');

                el.html(`<p>${html}</p>`);
            }
        } catch (e) {
            console.error('Error rendering markdown:', e);
            el.text(textContent);
        }

        if (type === 'success') {
            el.append(`
                <div class="mcp-feedback" id="feedback-buttons">
                    <button class="like-btn" onclick="mcp_interface.handle_feedback('like')">👍 Like</button>
                    <button class="dislike-btn" onclick="mcp_interface.handle_feedback('dislike')">👎 Dislike</button>
                </div>
            `);
        }
    }

    handle_feedback(feedbackType) {
        if (!this.lastFeedbackData) return;

        const logEntry = {
            question: $('#user-question').val().trim(),
            answer: this.lastFeedbackData.responseText || '',
            feedback: feedbackType,
            tool_name: this.lastFeedbackData.tool || ''
        };

        let icon = feedbackType === 'like' ? '👍' : '👎';
        $('#feedback-buttons').replaceWith(`
            <div class="mcp-feedback" id="feedback-comment-section">
                <div>${icon}</div>
                <textarea id="feedback-comment" placeholder="Add your comment..." rows="2" style="flex: 1; border-radius: 4px; border: 1px solid #ccc; padding: 4px;"></textarea>
                <button class="mcp-btn" id="feedback-submit-btn" style="background: #28a745; padding: 4px 8px; font-size: 12px;">Submit</button>
            </div>
        `);

        $('#feedback-submit-btn').on('click', () => {
            const comment = $('#feedback-comment').val().trim();

            frappe.call({
                method: "ampower_jive.ampower_jive.doctype.jive_logs.jive_logs.write_jive_logs",
                args: {
                    user: frappe.session.user,
                    doc_name: window.doc_name || null,
                    logs: JSON.stringify([{ ...logEntry, comment }]),
                    question: logEntry.question,
                    prompt: this.lastFeedbackData.prompt || '',
                    tool_name: logEntry.tool_name,
                    comment: comment
                },
                callback: function(r) {
                    if (r.message?.doc_name) {
                        saveDocName(r.message.doc_name);
                    }
                    $('#feedback-comment-section').html(`<div class="mcp-feedback">${icon} Thank you for your feedback!</div>`);
                }
            });
        });
    }

    show_loading() {
        $('#mcp-result').removeClass('mcp-error mcp-success').text('Loading...');
    }
    show_result(data, type = 'success') {
        this.renderMarkdown(data, type);
    }

    async show_gdrive_result(data, type = 'success') {
        let content = '';

        if (data && typeof data === 'object') {
            if (data.result && data.result.content && Array.isArray(data.result.content) && data.result.content.length > 0 && data.result.content[0].text) {
                try {
                    const parsed = JSON.parse(data.result.content[0].text);
                    content = parsed.response || data.result.content[0].text;
                } catch (e) {
                    content = data.result.content[0].text;
                }
            } else if (data.result && data.result.text) {
                content = data.result.text;
            } else {
                content = JSON.stringify(data, null, 2);
            }
        } else {
            content = String(data || 'No data available');
        }

        await this.renderMarkdown(content, type);
    }

    clear_result() {
        $('#mcp-result').removeClass('mcp-error mcp-success').text('Ready to execute MCP operations...');
    }

    show_loader() {
        $('#gdrive-loader-overlay').css('display', 'flex');
    }

    hide_loader() {
        $('#gdrive-loader-overlay').hide();
    }
}