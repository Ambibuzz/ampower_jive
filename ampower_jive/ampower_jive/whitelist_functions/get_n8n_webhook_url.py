import frappe


@frappe.whitelist()
def get_chat_bot_configuration():
    # Load your singleton document
    config_doc = frappe.get_single("Jive Config")
    if not (config_doc):
        frappe.throw("Jive Config document is not available")
    sid = frappe.session.sid
    url = config_doc.get("n8n_webhook_url")
    instance_end_point = config_doc.get("instance_end_point")
    active = config_doc.get("active_jive")
    return {"url": url, "sid": sid, "instance_end_point": instance_end_point, "active": active}
