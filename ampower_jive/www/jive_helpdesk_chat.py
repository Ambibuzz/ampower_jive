from urllib.parse import quote_plus

import frappe

login_required = True
no_cache = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.redirect(f"/login?redirect-to={quote_plus(frappe.request.path)}")

    context.title = "Jive Helpdesk"
    context.login_required = True
    context.no_header = 1
    context.no_breadcrumbs = 1
    context.show_sidebar = False
    context.full_width = 1
    context.body_class = "jive-helpdesk-portal-page"
    return context
