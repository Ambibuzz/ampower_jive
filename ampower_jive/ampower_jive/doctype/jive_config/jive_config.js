// Copyright (c) 2025, Ambibuzz Technologies LLP and contributors
// For license information, please see license.txt

const HD_TICKETS_FIELDS = [
    'enable_hd_tickets',
    'hd_tickets_model_section',
    'hd_tickets_model',
    'hd_tickets_system_prompt_section',
    'hd_tickets_system_prompt'
];

function applyHelpdeskDependencyState(frm, helpdeskInstalled) {
    HD_TICKETS_FIELDS.forEach((fieldname) => {
        frm.set_df_property(fieldname, 'hidden', !helpdeskInstalled);
    });

    if (!helpdeskInstalled && frm.doc.enable_hd_tickets) {
        frm.set_value('enable_hd_tickets', 0);
    }
}

frappe.ui.form.on("Jive Config", {
    refresh(frm) {
        const ragMode = (frm.doc.rag_pipeline_mode || "").toLowerCase();
        const userSpecificMode = /user\s*specific|customer\s*specific|customer.*vdb|customer_vdb|\bvdb\b/.test(ragMode);

        frappe.call({
            method: 'ampower_jive.api.check_helpdesk_installed',
            callback: function (r) {
                applyHelpdeskDependencyState(frm, !!(r.message && r.message.installed));
            },
            error: function () {
                applyHelpdeskDependencyState(frm, false);
            }
        });

        // Add Test Connection button when Jive Core is enabled
        if (frm.doc.use_jive_core && frm.doc.jive_core_url && frm.doc.jive_core_api_key) {
            frm.add_custom_button(__('Test Connection'), function () {
                frappe.show_alert({
                    message: __('Testing connection to Jive Core...'),
                    indicator: 'blue'
                });

                frappe.call({
                    method: 'ampower_jive.utils.config_provider.test_jive_core_connection',
                    freeze: true,
                    freeze_message: __('Testing connection...'),
                    callback: function (r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('Successfully connected to Jive Core!'),
                                indicator: 'green'
                            });
                            frm.set_value('jive_core_connection_status', 'Connected');
                            frm.reload_doc();
                        } else {
                            frappe.show_alert({
                                message: __('Connection failed: ') + (r.message ? r.message.message : 'Unknown error'),
                                indicator: 'red'
                            }, 5);
                            frm.set_value('jive_core_connection_status', 'Error');
                        }
                    },
                    error: function () {
                        frappe.show_alert({
                            message: __('Connection test failed'),
                            indicator: 'red'
                        }, 5);
                        frm.set_value('jive_core_connection_status', 'Error');
                    }
                });
            }, __('Jive Core'));
        }

        frm.add_custom_button(userSpecificMode ? __("Process User Specific RAG") : __("Process RAG Documents"), function () {
            frappe.call({
                method: "ampower_jive.api.enqueue_rag_index_build",
                freeze: true,
                freeze_message: userSpecificMode ? __("Queuing user-specific RAG processing...") : __("Queuing RAG document processing..."),
                callback: function (r) {
                    if (r.message && r.message.success) {
                        frappe.show_alert({
                            message: userSpecificMode ? __("User-specific RAG processing queued.") : __("RAG processing queued."),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    } else {
                        frappe.msgprint({
                            title: __("RAG Processing"),
                            message: (r.message && r.message.message) || __("Unable to queue RAG processing."),
                            indicator: "red"
                        });
                    }
                },
                error: function () {
                    frappe.msgprint({
                        title: __("RAG Processing"),
                        message: __("Unable to queue RAG processing."),
                        indicator: "red"
                    });
                }
            });
        }, __("RAG"));

        if (userSpecificMode) {
            frm.add_custom_button(__("Open Vector Databases"), function () {
                frappe.set_route("List", "Jive Vector Data Base");
            }, __("RAG"));
        }
    },

    use_jive_core(frm) {
        // Clear connection status when toggling
        if (!frm.doc.use_jive_core) {
            frm.set_value('jive_core_connection_status', '');
        }
    },

    rag_pipeline_mode(frm) {
        frm.refresh();
    }
});
