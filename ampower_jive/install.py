"""
AmPower Jive Installation Hooks
Creates necessary configurations on app install.
"""

import frappe
from frappe import _
from ampower_jive.utils.config_defaults import apply_default_jive_config


def create_jive_user_role():
    """Create the Jive User role if it doesn't exist."""
    try:
        if not frappe.db.exists("Role", "Jive User"):
            role = frappe.new_doc("Role")
            role.role_name = "Jive User"
            role.desk_access = 1
            role.is_custom = 0
            role.disabled = 0
            role.save(ignore_permissions=True)
            frappe.db.commit()
            print("✓ Jive User role created successfully")
        else:
            print("✓ Jive User role already exists")
    except Exception as e:
        frappe.log_error(f"Jive User role creation error: {e}", "Jive Install Error")
        print(f"⚠ Could not create Jive User role: {e}")


def after_install():
    """
    Run after the app is installed.
    Creates the Jive Config singleton and Jive User role.
    """
    # Create Jive User role first
    create_jive_user_role()
    
    try:
        # Check if Jive Config already exists
        if not frappe.db.exists("Jive Config", "Jive Config"):
            # Create the singleton
            doc = frappe.new_doc("Jive Config")
            apply_default_jive_config(doc)
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            
            print("✓ Jive Config created successfully")
            print("  → Configure your OpenAI API key in Jive Config to get started")
            print("  → Grant 'Jive User' role to users who should have access to Jive")
        else:
            print("✓ Jive Config already exists")
            
    except Exception as e:
        frappe.log_error(f"Jive Config creation error: {e}", "Jive Install Error")
        print(f"⚠ Could not create Jive Config: {e}")
