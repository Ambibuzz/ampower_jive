"""Targeted override for Helpdesk HD Ticket behavior."""

from __future__ import annotations

import frappe

from helpdesk.helpdesk.doctype.hd_ticket.hd_ticket import HDTicket


class AmPowerHDTicket(HDTicket):
    """Preserve upstream behavior while allowing system-driven communication syncs."""

    def on_communication_update(self, c):
        """Mirror upstream logic but persist via ignore_permissions for callback-driven saves."""
        if c.sent_or_received == "Received":
            if self.has_agent_replied:
                self.status = self.ticket_reopen_status
            else:
                self.status = self.default_open_status
            self.last_customer_response = frappe.utils.now_datetime()

        if c.sent_or_received == "Sent":
            if c.communication_type and c.communication_type == "Automated Message":
                return

            self.first_responded_on = (
                self.first_responded_on or frappe.utils.now_datetime()
            )
            self.last_agent_response = frappe.utils.now_datetime()

            if frappe.db.get_single_value("HD Settings", "auto_update_status"):
                self.status = frappe.db.get_single_value(
                    "HD Settings", "update_status_to"
                )

        self.description = self.description or c.content
        self.save(ignore_permissions=True)
