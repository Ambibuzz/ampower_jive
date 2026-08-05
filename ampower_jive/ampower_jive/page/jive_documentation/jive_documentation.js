frappe.pages["jive-documentation"].on_page_load = function (wrapper) {
    wrapper.classList.add("jive");

    frappe.ui.make_app_page({
        parent: wrapper,
        title: "",
        single_column: true,
    });

    $(wrapper).find(".layout-main-section").html(frappe.render_template("jive_documentation", {}));

    const $container = $(wrapper).find(".jive-docs-container");
    const $detail = $container.find("#jive-docs-detail-view");
    const $nav = $container.find(".jive-nav");

    const sectionOrder = [
        { key: "overview", label: "Start Here", hint: "What Jive does and how to begin", icon: "1" },
        { key: "access", label: "Access", hint: "Roles and permissions", icon: "2" },
        { key: "setup", label: "Configure", hint: "Jive Config and first-time setup", icon: "3" },
        { key: "usage", label: "Use Jive", hint: "Modes, prompts, and good habits", icon: "4" },
        { key: "hd-tickets", label: "HD Tickets", hint: "Ticket status, updates, and portal support", icon: "5" },
        { key: "rag", label: "RAG", hint: "Files, knowledge base, and processing", icon: "6" },
        { key: "troubleshooting", label: "Troubleshooting", hint: "Common fixes and checks", icon: "7" },
        { key: "open-source", label: "Open Source", hint: "Code map, customization, and license", icon: "8" },
    ];

    const sections = {
        overview: {
            eyebrow: "Overview",
            title: "AmPower Jive setup and usage guide",
            lead:
                "AmPower Jive is a conversational AI layer for Frappe and ERPNext. It can answer data questions, guide users through workflows, create and modify documents with approval, generate charts, and search knowledge base with local RAG.",
            chips: ["Open source", "ERPNext", "Jive User", "Context aware", "Jive Core optional"],
            blocks: [
                {
                    type: "cards",
                    items: [
                        {
                            title: "What users can do",
                            items: [
                                "Ask ERPNext questions in natural language.",
                                "Get guided help for setup and everyday tasks.",
                                "Use Agent mode to create or update documents with approval.",
                                "Create visual summaries in Insights mode.",
                                "Search uploaded documents and knowledge base with RAG.",
                            ],
                        },
                        {
                            title: "What the installer creates",
                            items: [
                                "A Jive User role for chat access.",
                                "A Jive Config singleton for site-wide settings.",
                                "A safe disabled-by-default launch state.",
                                "The floating Jive launcher and chat UI.",
                            ],
                        },
                        {
                            title: "Recommended first launch",
                            ordered: true,
                            items: [
                                "Open Jive Config and add either an OpenAI key or Jive Core details.",
                                "Limit Included DocTypes to the data you actually want exposed.",
                                "Assign Jive User to the people who should chat with Jive.",
                                "Enable the app, refresh the desk, and test one prompt.",
                            ],
                        },
                    ],
                },
                {
                    type: "callout",
                    tone: "highlight",
                    title: "Safe default",
                    text: "The app ships disabled so you can configure it before users see the launcher. Keep it off until your API, access, and data source settings are ready.",
                },
            ],
        },
        access: {
            eyebrow: "Roles and access",
            title: "Who can use Jive and who can configure it",
            lead:
                "Access is intentionally split between using the chat and managing the site-wide settings. That keeps normal users safe while still letting admins prepare the module.",
            chips: ["Jive User", "Website User", "System Manager", "Administrator", "Jive Admin fixture"],
            blocks: [
                {
                    type: "table",
                    columns: ["Role", "What it can do", "Notes"],
                    rows: [
                        ["Administrator", "Always passes the access check.", "Useful for debugging and first-time setup."],
                        ["Jive User", "Can use Jive chat and the built-in modes.", "This is the role normal users need."],
                        ["Website User", "Can use the website helpdesk page after login.", "No Jive User role is needed for that page."],
                        ["System Manager", "Can open and maintain Jive Config.", "Can configure the site but still needs Jive User to chat."],
                        ["Jive Admin", "Shipped as a fixture for sites that want a dedicated admin role.", "The code still centers access on Jive User and System Manager."],
                    ],
                },
                {
                    type: "cards",
                    items: [
                        {
                            title: "How to grant access",
                            ordered: true,
                            items: [
                                "Open the User record.",
                                "Add the Jive User role to the people who should chat.",
                                "Add System Manager only to the people who will manage the app.",
                                "Save, clear cache if needed, and reload the desk.",
                            ],
                        },
                        {
                            title: "When a button is missing",
                            items: [
                                "If the launcher is missing, check that Jive is enabled globally.",
                                "If the launcher appears but chat is blocked, check Jive User on the account.",
                                "If the website helpdesk page is needed, make sure the user can log in as a website user.",
                                "If Jive Config is not editable, make sure you are a System Manager.",
                            ],
                        },
                    ],
                },
                {
                    type: "callout",
                    tone: "warning",
                    title: "Access rule to remember",
                    text: "System Manager alone does not grant chat access. To use Jive, the user also needs Jive User.",
                },
            ],
        },
        setup: {
            eyebrow: "First-time setup",
            title: "Configure Jive before you turn it on",
            lead:
                "The Jive Config singleton is the control room for the app. Start with the general switches, then configure the models, data sources, RAG settings, and UI defaults.",
            chips: ["Jive Config", "Allowed DocTypes", "Models", "RAG", "Helpdesk portal"],
            blocks: [
                {
                    type: "table",
                    title: "General controls",
                    columns: ["Field", "Purpose", "Default / note"],
                    rows: [
                        ["Ampower Jive Enabled ?", "Master switch for the whole app.", "Off after install"],
                        ["Enable Voice Input", "Lets users speak prompts instead of typing.", "On"],
                        ["Enable File Upload", "Allows Helpdesk mode uploads.", "On"],
                        ["Enable GIF Generation", "Lets Helpdesk responses include GIF summaries.", "On"],
                        ["Max History Messages", "How much recent conversation is carried forward.", "10"],
                        ["Conversation Retention Days", "How long conversation history stays in storage.", "30"],
                        ["Show Suggestions", "Shows starter prompts on the welcome screen.", "On"],
                        ["Primary Color", "Sets the Jive accent color in the UI.", "#6366f1"],
                    ],
                },
                {
                    type: "table",
                    title: "AI and behavior controls",
                    columns: ["Field", "Purpose", "Default / note"],
                    rows: [
                        ["Data Query Model", "Model used for ERPNext Q&A.", "gpt-4o-mini"],
                        ["Helpdesk Model", "Model used for how-to guidance.", "gpt-4o-mini-search-preview"],
                        ["HD Tickets Model", "Model used for ticket summaries and issue follow-up answers.", "gpt-4o-mini"],
                        ["Agent Model", "Model used for create/update operations.", "gpt-4o-mini"],
                        ["Insights Model", "Model used for chart generation.", "gpt-4o-mini"],
                        ["Temperatures", "Controls how focused or creative the responses are.", "Lower is safer for Agent mode"],
                        ["Agent Require Approval", "Requires a confirmation step before write actions execute.", "Enabled by default"],
                        ["Max Context Window Tokens", "Caps how much page context the assistant will use.", "12000"],
                        ["Context Aware System Prompt", "Advanced prompt for page-aware answers.", "Optional tuning"],
                    ],
                },
                {
                    type: "table",
                    title: "System prompt editors",
                    columns: ["Field", "Where to edit it", "What it controls"],
                    rows: [
                        ["Data Query System Prompt", "Jive Config > AI Models tab", "Base instruction for normal ERPNext data questions."],
                        ["Context Aware System Prompt", "Jive Config > AI Models tab", "Prompt used when the user enables context aware mode."],
                        ["Helpdesk System Prompt", "Jive Config > AI Models tab", "Guidance style for help and setup answers."],
                        ["HD Tickets System Prompt", "Jive Config > AI Models tab", "Optional guidance for ticket-specific replies and workflows."],
                        ["Agent System Prompt", "Jive Config > AI Models tab", "Rules for safe create, update, submit, and cancel actions."],
                        ["Insights System Prompt", "Jive Config > AI Models tab", "Instructions for chart generation and insight writing."],
                    ],
                },
                {
                    type: "table",
                    title: "Security and data scope",
                    columns: ["Field", "Purpose", "Default / note"],
                    rows: [
                        ["Included DocTypes", "Limits which DocTypes can be queried or modified.", "Populate this carefully"],
                        ["Use Jive Core", "Switches config and key lookup to the core service.", "Off"],
                        ["Jive Core URL", "Address of the core instance.", "Required when core is on"],
                        ["Jive Core API Key", "Authenticates the tenant with core.", "Required when core is on"],
                        ["OpenAI API Key", "Local API key when Jive Core is off.", "Hidden when core is enabled"],
                        ["Inference Engine", "Current provider selection.", "OpenAI"],
                    ],
                },
                {
                    type: "table",
                    title: "RAG controls",
                    columns: ["Field", "Purpose", "Default / note"],
                    rows: [
                        ["RAG Pipeline Mode", "Switches between the legacy site-wide index and user-specific routing.", "Legacy Site RAG by default"],
                        ["Default Vector Database", "Optional fallback in user-specific mode.", "Used only when no direct mapping applies"],
                        ["RAG Documents", "Files that should be indexed locally.", "Add and save the document rows"],
                        ["Embedding Model", "Model used to create embeddings.", "text-embedding-3-small"],
                        ["Chunk Size", "How large each chunk should be.", "1200"],
                        ["Chunk Overlap", "How much content overlaps between chunks.", "200"],
                        ["Top K", "How many chunks are retrieved per question.", "5"],
                        ["Processing Status", "Shows if the local index is idle, queued, ready, or failed.", "Monitor after processing"],
                        ["Process RAG Documents", "Queues the indexing job.", "Use after adding or changing documents"],
                    ],
                },
                {
                    type: "table",
                    title: "Website helpdesk controls",
                    columns: ["Field", "Purpose", "Default / note"],
                    rows: [
                        ["Enable HD Tickets", "Shows ticket chat on the website helpdesk page and in desk chat.", "Requires the Helpdesk app"],
                        ["Enable RAG Helpdesk", "Shows Doc Help on the website helpdesk page.", "Off by default"],
                        ["/jive-helpdesk-chat", "Dedicated page for logged-in website users.", "Uses portal-safe chat access"],
                    ],
                },
                {
                    type: "steps",
                    title: "A safe setup order",
                    items: [
                        "Open Jive Config.",
                        "Choose whether the site will use local OpenAI settings or Jive Core.",
                        "Set the allowed DocTypes and the model defaults.",
                        "Turn on the website helpdesk options if portal users should use Jive.",
                        "Add any RAG documents and process them.",
                        "Review the welcome text and primary color.",
                        "Save the document, then enable Jive and test it.",
                    ],
                },
                {
                    type: "callout",
                    tone: "highlight",
                    title: "Brand sync",
                    text: "The default primary color in the app and the docs both follow the same Jive purple-indigo palette. If you customize the color, keep the rest of the gradient family close to it so the launcher and docs still feel like one product.",
                },
            ],
        },
        usage: {
            eyebrow: "Using Jive",
            title: "Pick the right mode for the job",
            lead:
                "The chat UI is mode-driven. Choose the mode that matches the job you want to do, then keep the prompt clear and specific. Data Query, Helpdesk, HD Tickets, Agent, Insights, and RAG all behave differently on purpose.",
            chips: ["Data Query", "Helpdesk", "HD Tickets", "Insights", "RAG", "Context aware"],
            blocks: [
                {
                    type: "cards",
                    items: [
                        {
                            title: "Data Query",
                            items: [
                                "Best for ERPNext data questions and summaries.",
                                "Only sees the DocTypes listed in Included DocTypes.",
                                "Respects Frappe permissions for the current user.",
                                "Try prompts like: 'Show the top customers this month' or 'Summarize unpaid invoices by territory'.",
                            ],
                        },
                        {
                            title: "Helpdesk",
                            items: [
                                "Best for setup guidance and how-to questions.",
                                "Web Search from frappe docs and forums.",
                                "Can generate GIF summaries when GIF generation is enabled.",
                                "Try prompts like: 'How to create a sales order?' or 'How to create a delivery note?'.",
                            ],
                        },
                        {
                            title: "Agent",
                            items: [
                                "Best for document creation and updates.",
                                "The assistant drafts actions first and asks for approval when required.",
                                "Use clear document names and give it enough detail to plan safely.",
                                "Try prompts like: 'Create a draft Sales Order for this customer' or 'Update the delivery note status'.",
                            ],
                        },
                        {
                            title: "HD Tickets",
                            items: [
                                "Best for support ticket questions, follow-ups, and issue tracking.",
                                "Use it to ask about ticket status, recent activity, or what is waiting on action.",
                                "It can also help prepare a new ticket or continue communication on an existing one.",
                                "Try prompts like: 'Show my open tickets' or 'Create a ticket for login issue'.",
                            ],
                        },
                        {
                            title: "Insights",
                            items: [
                                "Best for charts, trends, and visualization requests.",
                                "Requires the Frappe Insights app to be installed on the site.",
                                "Can build charts like bars, lines, donuts, numbers, and tables.",
                                "Try prompts like: 'Create a monthly sales trend chart' or 'Show revenue by customer'.",
                            ],
                        },
                        {
                            title: "RAG",
                            items: [
                                "Best for questions about uploaded documents and tenant knowledge.",
                                "Uses the local RAG index built from the files you process in Jive Config.",
                                "In user-specific mode, each person can be routed to their own linked document set.",
                                "Helpful for SOPs, manuals, policies, and project notes.",
                                "Try prompts like: 'What does the policy say about approval limits?' or 'Summarize the installation guide'.",
                            ],
                        },
                        {
                            title: "Website helpdesk page",
                            items: [
                                "Open `/jive-helpdesk-chat` for a simple website version of Jive.",
                                "This page is for logged-in website users who need help or want to raise issues.",
                                "Depending on setup, it can show Helpdesk, HD Tickets, and Doc Help.",
                                "Use it when you want customers or portal users to ask questions without entering the desk.",
                            ],
                        },
                    ],
                },
                {
                    type: "callout",
                    tone: "info",
                    title: "Context-aware answers",
                    text: "When Jive is opened from a form, list, or workspace that passes page context, it can answer with that screen in mind. Turn on the 'Context aware' checkbox in supported modes to ask about the page you are currently viewing.",
                },
                {
                    type: "cards",
                    items: [
                        {
                            title: "How context aware mode works",
                            items: [
                                "The chat window reads the current page snapshot and sends it as context_payload.",
                                "The context-aware prompt treats that page context as the source of truth.",
                                "It trims irrelevant context using Max Context Window Tokens when the page is too large.",
                                "It still respects Frappe read permissions for the current user.",
                            ],
                        },
                        {
                            title: "Where to use it",
                            items: [
                                "Data Query when you want answers about the open form or list.",
                                "Agent when you want a document action tied to the record you are viewing.",
                                "Insights when the chart request should use the active page context.",
                                "RAG when the question should be grounded in the open document context.",
                            ],
                        },
                        {
                            title: "What to expect",
                            items: [
                                "The toggle label in the chat is 'Context aware'.",
                                "If the current page cannot provide context, Jive will tell you to open a supported view.",
                                "For very large pages, narrow the view or ask about a specific field, row, or linked record.",
                            ],
                        },
                    ],
                },
                {
                    type: "steps",
                    title: "Good habits for better answers",
                    items: [
                        "Ask one task at a time.",
                        "Use exact DocType names when you want structured data.",
                        "Switch modes when the job changes instead of stretching one mode too far.",
                        "Refresh the page after changing settings so the latest config is loaded.",
                        "Keep the allowed data scope tight in production.",
                    ],
                },
            ],
        },
        "hd-tickets": {
            eyebrow: "HD Tickets",
            title: "Work with support tickets in a dedicated mode",
            lead:
                "HD Tickets is for issue tracking and support follow-up. Use it when the question is about ticket status, ticket activity, or creating and continuing support requests instead of asking a general how-to question.",
            chips: ["Ticket status", "Customer activity", "Create ticket", "Portal page", "Helpdesk app required"],
            blocks: [
                {
                    type: "cards",
                    items: [
                        {
                            title: "What this mode is for",
                            items: [
                                "Check open tickets, recent updates, and pending work.",
                                "Ask about a specific ticket and continue with follow-up questions.",
                                "Prepare a new ticket when a user needs to report an issue.",
                                "Keep support questions separate from normal ERPNext how-to guidance.",
                            ],
                        },
                        {
                            title: "Where users will see it",
                            items: [
                                "Inside desk chat when Enable HD Tickets is turned on.",
                                "On `/jive-helpdesk-chat` for logged-in website users.",
                                "Only when the Helpdesk app is installed on the site.",
                            ],
                        },
                        {
                            title: "Examples",
                            items: [
                                "Show my open tickets.",
                                "What changed on ticket HD-TCK-0001?",
                                "Create a ticket for login issue.",
                                "Add an update to this customer issue.",
                            ],
                        },
                    ],
                },
                {
                    type: "table",
                    title: "HD Tickets controls",
                    columns: ["Field", "What it does", "Note"],
                    rows: [
                        ["Enable HD Tickets", "Shows the HD Tickets mode in chat.", "Works in desk chat and the website helpdesk page"],
                        ["HD Tickets Model", "Sets the AI model for ticket summaries and replies.", "Configured in Jive Config"],
                        ["HD Tickets System Prompt", "Lets admins shape ticket-specific response behavior.", "Optional field in Jive Config"],
                    ],
                },
                {
                    type: "steps",
                    title: "Simple setup flow",
                    items: [
                        "Install and enable the Helpdesk app on the site.",
                        "Open Jive Config.",
                        "Turn on Enable HD Tickets.",
                        "Set the HD Tickets model if you want a different default.",
                        "Save the config and refresh the page.",
                        "Open chat and test with a ticket question.",
                    ],
                },
                {
                    type: "callout",
                    tone: "info",
                    title: "When to choose Helpdesk instead",
                    text: "Use Helpdesk for process guidance such as 'how do I do this in ERPNext?'. Use HD Tickets when the conversation is about a real support issue, a ticket list, or an update on a customer problem.",
                },
            ],
        },
        rag: {
            eyebrow: "RAG and files",
            title: "Build a local knowledge base from documents",
            lead:
                "RAG is tenant-side. You add the documents in Jive Config, process them locally, and then ask questions against that index. Jive Core is not required for this flow.",
            chips: ["Local index", "User-specific routing", "Helpdesk uploads", "PDF, DOCX, CSV, TXT, JSON", "Processed locally"],
            blocks: [
                {
                    type: "cards",
                    items: [
                        {
                            title: "Helpdesk file uploads",
                            items: [
                                "Supported upload types are PDF, DOCX, DOC, CSV, TXT, TEXT, MD, MARKDOWN, and JSON.",
                                "The file processor extracts text locally and keeps the current-session context isolated.",
                                "This is a great fit for a guide, policy, release note, or troubleshooting pack.",
                            ],
                        },
                        {
                            title: "Tenant RAG documents",
                            items: [
                                "Add the source files in the RAG Documents table on Jive Config.",
                                "Choose a chunk size, chunk overlap, embedding model, and Top K retrieval value.",
                                "Click Process RAG Documents and wait for the status to become Ready.",
                            ],
                        },
                        {
                            title: "User-specific RAG",
                            items: [
                                "Use this when different users should search different document sets.",
                                "Switch RAG Pipeline Mode to User Specific RAG in Jive Config.",
                                "Create Jive Rag User records and link each one to one or more Jive Vector Data Base records.",
                                "You can also set a default vector database as a fallback.",
                            ],
                        },
                        {
                            title: "When to use it",
                            items: [
                                "Use RAG when the answer lives in your own documents instead of ERPNext records.",
                                "It is ideal for manuals, onboarding docs, SOPs, and internal policy libraries.",
                                "If the answer should come from live data, use Data Query instead.",
                            ],
                        },
                        {
                            title: "Doc Help on the website",
                            items: [
                                "Doc Help is the website version of RAG for logged-in website users.",
                                "It appears on `/jive-helpdesk-chat` only when Enable RAG Helpdesk is turned on.",
                                "The page shows the documents linked to that user when user-specific RAG is active.",
                            ],
                        },
                    ],
                },
                {
                    type: "table",
                    columns: ["Supported file type", "Typical use", "Notes"],
                    rows: [
                        ["PDF", "Policies, manuals, signed documents", "Recommended for final reference material"],
                        ["DOCX / DOC", "Working documents and editable guides", "Tables and paragraphs are extracted"],
                        ["CSV", "Structured reference data", "The first 100 rows are used for context"],
                        ["TXT / TEXT / MD / MARKDOWN", "Simple text or documentation files", "Good for release notes and procedures"],
                        ["JSON", "Structured configs or exports", "Converted to readable text for retrieval"],
                    ],
                },
                {
                    type: "steps",
                    title: "RAG setup flow",
                    items: [
                        "Add the documents to the RAG Documents table.",
                        "Save the Jive Config document.",
                        "Click Process RAG Documents.",
                        "Wait for the status to show Ready.",
                        "Open the chat in RAG mode and ask a document-specific question.",
                    ],
                },
                {
                    type: "steps",
                    title: "User-specific RAG setup flow",
                    items: [
                        "Change RAG Pipeline Mode to User Specific RAG.",
                        "Prepare the needed Jive Vector Data Base records and load their documents.",
                        "Create Jive Rag User mappings for the relevant users.",
                        "Link one or more vector databases to each mapping.",
                        "Set Default Vector Database only if you want a fallback.",
                        "Click Process User Specific RAG and test with the correct user account.",
                    ],
                },
                {
                    type: "callout",
                    tone: "highlight",
                    title: "Important",
                    text: "RAG indexing and document processing stay inside the tenant app. You can run both the site-wide and user-specific flows even when Jive Core is not enabled.",
                },
            ],
        },
        troubleshooting: {
            eyebrow: "Troubleshooting",
            title: "Fix the most common setup and usage issues",
            lead:
                "Most problems come from one of four places: access, missing settings, unsupported files, or an unprocessed data source. Work through the checks below before opening an issue.",
            chips: ["Access", "Config", "Files", "RAG", "Core connection"],
            blocks: [
                {
                    type: "cards",
                    items: [
                        {
                            title: "The launcher does not appear",
                            items: [
                                "Confirm that Ampower Jive Enabled ? is checked.",
                                "Make sure the current user has Jive User or is Administrator.",
                                "Clear cache and reload the desk after changing the config.",
                            ],
                        },
                        {
                            title: "Chat says permission denied",
                            items: [
                                "Add the Jive User role to the user record.",
                                "Remember that System Manager is for configuration, not chat by itself.",
                                "Reopen the app after saving the role change.",
                            ],
                        },
                        {
                            title: "Data Query is too narrow",
                            items: [
                                "Check the Included DocTypes table in Jive Config.",
                                "Add only the DocTypes you want exposed to users.",
                                "Refresh the page so the schema cache updates.",
                            ],
                        },
                        {
                            title: "Helpdesk uploads fail",
                            items: [
                                "Use a supported file type such as PDF, DOCX, CSV, TXT, MD, or JSON.",
                                "Make sure the File document is saved before sending it to the chat.",
                                "Try again after re-uploading the file if it was renamed or moved.",
                            ],
                        },
                        {
                            title: "RAG is not answering well",
                            items: [
                                "Confirm the RAG processing status is Ready.",
                                "Re-check the chunk size, overlap, and Top K values.",
                                "Make sure the source files were added to the RAG Documents table and saved.",
                            ],
                        },
                        {
                            title: "Website helpdesk page is missing modes",
                            items: [
                                "Make sure the user is logged in through the website, not as Guest.",
                                "Turn on Enable HD Tickets or Enable RAG Helpdesk in Jive Config when needed.",
                                "If Doc Help is enabled, confirm the user-specific RAG mapping and linked documents are ready.",
                            ],
                        },
                        {
                            title: "Jive Core connection fails",
                            items: [
                                "Check the Jive Core URL and API key.",
                                "Use the Test Connection button on Jive Config.",
                                "If the site is behind a proxy or firewall, confirm the tenant can reach the core endpoint.",
                            ],
                        },
                    ],
                },
                {
                    type: "callout",
                    tone: "warning",
                    title: "Best recovery step",
                    text: "When in doubt, save the config, clear cache, restart the bench if you changed code or models, and test with a very small prompt first.",
                },
            ],
        },
        "open-source": {
            eyebrow: "Open source notes",
            title: "Where to read, extend, and contribute",
            lead:
                "This page is written for people who want to install Jive and for people who want to understand it well enough to extend it. The codebase is intentionally split into clear parts so you can find the right layer quickly.",
            chips: ["MIT license", "Code map", "Customization", "Contributions"],
            blocks: [
                {
                    type: "cards",
                    items: [
                        {
                            title: "Start with these files",
                            items: [
                                "README.md for the high-level install and feature overview.",
                                "ampower_jive/install.py for the bootstrap defaults and role creation.",
                                "ampower_jive/api.py for permissions, chat routing, and core endpoints.",
                                "ampower_jive/utils/config_provider.py for local versus Jive Core config resolution.",
                                "ampower_jive/utils/file_processor.py for supported Helpdesk file types.",
                                "ampower_jive/ampower_jive/doctype/jive_config/jive_config.json for the actual config schema.",
                            ],
                        },
                        {
                            title: "How to customize the experience",
                            items: [
                                "Change the primary color and welcome copy in Jive Config.",
                                "Adjust the allowed DocTypes before exposing Jive to users.",
                                "Tune the model selections and temperatures for your workflow.",
                                "Keep the docs palette close to the launcher palette so the product feels cohesive.",
                            ],
                        },
                        {
                            title: "Contribution checklist",
                            items: [
                                "Test your change on a fresh site if it affects install or config.",
                                "Update the README when installation or dependencies change.",
                                "Update these docs when a field, mode, or file type changes.",
                                "Keep the public API and permission behavior backwards compatible when possible.",
                            ],
                        },
                    ],
                },
                {
                    type: "code",
                    label: "Common developer path",
                    code:
                        "apps/ampower_jive/\n" +
                        "├── README.md\n" +
                        "├── ampower_jive/install.py\n" +
                        "├── ampower_jive/api.py\n" +
                        "├── ampower_jive/utils/config_provider.py\n" +
                        "├── ampower_jive/utils/file_processor.py\n" +
                        "└── ampower_jive/ampower_jive/doctype/jive_config/jive_config.json",
                },
                {
                    type: "callout",
                    tone: "info",
                    title: "License",
                    text: "The package is published under the MIT license, so it is straightforward to use, fork, and adapt inside your own ERPNext environment.",
                },
            ],
        },
    };

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function renderList(items, ordered) {
        const tag = ordered ? "ol" : "ul";
        const className = ordered ? "jive-steps-list" : "jive-bullet-list";
        const content = (items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
        return `<${tag} class="${className}">${content}</${tag}>`;
    }

    function renderTable(block) {
        const headers = (block.columns || []).map((col) => `<th>${escapeHtml(col)}</th>`).join("");
        const rows = (block.rows || [])
            .map((row) => {
                const cells = (row || []).map((cell) => `<td>${escapeHtml(cell)}</td>`).join("");
                return `<tr>${cells}</tr>`;
            })
            .join("");

        return `
            <div class="jive-table-wrap">
                ${block.title ? `<div class="jive-table-title">${escapeHtml(block.title)}</div>` : ""}
                <table class="jive-table">
                    <thead><tr>${headers}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    function renderCode(block) {
        return `
            <div class="jive-code-shell">
                ${block.label ? `<div class="jive-code-label">${escapeHtml(block.label)}</div>` : ""}
                <pre><code>${escapeHtml(block.code || "")}</code></pre>
            </div>
        `;
    }

    function renderCard(card) {
        const title = card.title ? `<h3>${escapeHtml(card.title)}</h3>` : "";
        const text = card.text ? `<p>${escapeHtml(card.text)}</p>` : "";
        const items = card.items ? renderList(card.items, !!card.ordered) : "";
        const note = card.note ? `<div class="jive-card-note">${escapeHtml(card.note)}</div>` : "";

        return `
            <article class="jive-card">
                ${title}
                ${text}
                ${items}
                ${note}
            </article>
        `;
    }

    function renderBlock(block) {
        if (!block) {
            return "";
        }

        if (block.type === "cards") {
            return `<div class="jive-card-grid">${(block.items || []).map(renderCard).join("")}</div>`;
        }

        if (block.type === "table") {
            return renderTable(block);
        }

        if (block.type === "steps") {
            return `
                <section class="jive-step-section">
                    ${block.title ? `<h3>${escapeHtml(block.title)}</h3>` : ""}
                    ${renderList(block.items || [], true)}
                </section>
            `;
        }

        if (block.type === "code") {
            return renderCode(block);
        }

        if (block.type === "callout") {
            return `
                <div class="jive-callout jive-callout-${escapeHtml(block.tone || "info")}">
                    ${block.title ? `<h4>${escapeHtml(block.title)}</h4>` : ""}
                    ${block.text ? `<p>${escapeHtml(block.text)}</p>` : ""}
                </div>
            `;
        }

        if (block.type === "html") {
            return block.html || "";
        }

        return "";
    }

    function renderSection(section) {
        return `
            <div class="jive-detail-panel animate-fade-in">
                <div class="jive-detail-kicker">${escapeHtml(section.eyebrow || "")}</div>
                <h2 class="jive-detail-title">${escapeHtml(section.title || "")}</h2>
                <p class="jive-detail-lead">${escapeHtml(section.lead || "")}</p>
                <div class="jive-chip-row">
                    ${(section.chips || []).map((chip) => `<span class="jive-chip">${escapeHtml(chip)}</span>`).join("")}
                </div>
                <div class="jive-section-blocks">
                    ${(section.blocks || []).map(renderBlock).join("")}
                </div>
            </div>
        `;
    }

    function renderNavItem(item) {
        return `
            <div class="jive-section" data-section="${escapeHtml(item.key)}">
                <div class="jive-section-icon">${escapeHtml(item.icon)}</div>
                <div class="jive-section-copy">
                    <h3>${escapeHtml(item.label)}</h3>
                    <p>${escapeHtml(item.hint)}</p>
                </div>
            </div>
        `;
    }

    function setActiveSection(sectionKey) {
        const activeKey = sections[sectionKey] ? sectionKey : "overview";
        const section = sections[activeKey];
        $detail.stop(true, true).fadeOut(120, function () {
            $detail.html(renderSection(section)).fadeIn(180);
        });

        $container.find(".jive-section").removeClass("active");
        $container.find(`.jive-section[data-section="${activeKey}"]`).addClass("active");
        closeMobileSidebar();
    }

    function openMobileSidebar() {
        $container.addClass("sidebar-open");
        $container.find(".jive-sidebar-toggle").attr("aria-expanded", "true");
    }

    function closeMobileSidebar() {
        $container.removeClass("sidebar-open");
        $container.find(".jive-sidebar-toggle").attr("aria-expanded", "false");
    }

    $(wrapper).off(".jiveDocs");
    $(window).off("resize.jiveDocs");

    $nav.html(sectionOrder.map(renderNavItem).join(""));

    $(wrapper).on("click.jiveDocs", ".jive-section", function () {
        const sectionKey = $(this).data("section");
        setActiveSection(sectionKey);
    });

    $(wrapper).on("click.jiveDocs", ".jive-sidebar-toggle", function () {
        if ($container.hasClass("sidebar-open")) {
            closeMobileSidebar();
        } else {
            openMobileSidebar();
        }
    });

    $(wrapper).on("click.jiveDocs", ".jive-sidebar-backdrop", function () {
        closeMobileSidebar();
    });

    $(window).on("resize.jiveDocs", function () {
        if (window.innerWidth > 1024) {
            closeMobileSidebar();
        }
    });

    setActiveSection("overview");
};
