// Copyright (c) 2026, Ambibuzz Technologies LLP and contributors
// For license information, please see license.txt

frappe.ui.form.on("Jive Vector Data Base", {
    refresh(frm) {
        frm.add_custom_button(__("Process Vector Database"), function () {
            if (frm.is_new()) {
                frappe.msgprint({
                    title: __("Vector Database Processing"),
                    message: __("Save the vector database before processing it."),
                    indicator: "orange"
                });
                return;
            }

            frappe.call({
                method: "ampower_jive.api.enqueue_vector_database_index_build",
                args: {
                    vector_database_name: frm.doc.name
                },
                freeze: true,
                freeze_message: __("Queuing vector database processing..."),
                callback: function (r) {
                    if (r.message && r.message.success) {
                        frappe.show_alert({
                            message: __("Vector database processing queued."),
                            indicator: "green"
                        });
                        frm.reload_doc();
                    } else {
                        frappe.msgprint({
                            title: __("Vector Database Processing"),
                            message: (r.message && r.message.message) || __("Unable to queue vector database processing."),
                            indicator: "red"
                        });
                    }
                },
                error: function () {
                    frappe.msgprint({
                        title: __("Vector Database Processing"),
                        message: __("Unable to queue vector database processing."),
                        indicator: "red"
                    });
                }
            });
        }, __("RAG"));
    }
});
