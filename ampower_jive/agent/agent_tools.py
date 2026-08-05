"""
Agent Mode Tools
Tools for R/W operations that require user approval.
Includes validation tools for Frappe/ERPNext constraints.
"""

import frappe
from frappe import _
from langchain_core.tools import tool
from typing import Dict, Any, List
import json


def _log_agent_error(title: str, error_msg: str):
    """Log agent errors locally and to Jive Core."""
    # Local log
    full_traceback = frappe.get_traceback()
    frappe.log_error(f"{title}: {error_msg}\n{full_traceback}", title)
    
    # Jive Core log
    try:
        from ampower_jive.utils.interaction_logger import InteractionLogger
        logger = InteractionLogger("agent_mode")
        logger.log(
            status="error",
            error=Exception(f"{title}: {error_msg}"),
            error_traceback=full_traceback,
            request_data={"tool_error": title}
        )
    except Exception:
        pass


@tool
def get_document_fields(doctype: str) -> str:
    """
    Retrieves the fields of a given Frappe DocType including mandatory fields,
    link options, and field types. Use this FIRST before planning any operation.
    
    Args:
        doctype: The name of the DocType (e.g., "Item", "Sales Order")
    
    Returns:
        JSON string with field information including which fields are mandatory.
    """
    try:
        if not frappe.has_permission(doctype, "read"):
            return json.dumps({"success": False, "error": f"No permission to read {doctype}"})
        
        meta = frappe.get_meta(doctype)
        fields_info = []
        mandatory_fields = []
        
        for field in meta.fields:
            field_data = {
                "fieldname": field.fieldname,
                "label": field.label,
                "fieldtype": field.fieldtype,
                "reqd": bool(field.reqd),
                "read_only": bool(field.read_only),
                "default": field.default,
            }
            
            # Add options for Link and Select fields
            if field.fieldtype == "Link" and field.options:
                field_data["options"] = field.options
                field_data["description"] = f"Links to {field.options}"
            elif field.fieldtype == "Select" and field.options:
                field_data["options"] = field.options.split("\n")
            
            fields_info.append(field_data)
            
            if field.reqd:
                mandatory_fields.append({
                    "fieldname": field.fieldname,
                    "label": field.label or field.fieldname,
                    "fieldtype": field.fieldtype
                })
        
        # Check if doctype is submittable
        is_submittable = meta.is_submittable
        
        # Get naming series if exists
        naming_series = None
        autoname = meta.autoname
        if autoname and "naming_series" in autoname:
            ns_field = meta.get_field("naming_series")
            if ns_field and ns_field.options:
                naming_series = ns_field.options.split("\n")
        
        return json.dumps({
            "success": True,
            "doctype": doctype,
            "is_submittable": is_submittable,
            "naming_series": naming_series,
            "mandatory_fields": mandatory_fields,
            "all_fields": fields_info
        }, indent=2)
        
    except Exception as e:
        _log_agent_error("Agent Tool Error", f"get_document_fields error: {e}")
        return json.dumps({"success": False, "error": str(e), "traceback": frappe.get_traceback()})


@tool
def validate_link_field(doctype: str, value: str) -> str:
    """
    Validates that a linked document exists.
    Use this to verify that link field values are valid before planning.
    
    Args:
        doctype: The DocType to check (e.g., "Customer", "Item")
        value: The document name/ID to validate
    
    Returns:
        JSON string indicating if the document exists.
    """
    try:
        exists = frappe.db.exists(doctype, value)
        if exists:
            # Get some info about the document
            doc_title = frappe.db.get_value(doctype, value, "name")
            return json.dumps({
                "success": True,
                "exists": True,
                "doctype": doctype,
                "name": value,
                "message": f"{doctype} '{value}' exists"
            })
        else:
            # Suggest similar documents
            similar = frappe.db.sql(f"""
                SELECT name FROM `tab{doctype}` 
                WHERE name LIKE %s 
                LIMIT 5
            """, (f"%{value}%",), as_dict=True)
            
            suggestions = [s.name for s in similar] if similar else []
            
            return json.dumps({
                "success": True,
                "exists": False,
                "doctype": doctype,
                "name": value,
                "message": f"{doctype} '{value}' does NOT exist",
                "suggestions": suggestions
            })
    except Exception as e:
        _log_agent_error("Agent Tool Error", f"validate_link_field error: {e}")
        return json.dumps({"success": False, "error": str(e), "traceback": frappe.get_traceback()})


@tool
def validate_document_data(doctype: str, data: Dict[str, Any]) -> str:
    """
    Validates document data against Frappe rules without saving.
    Checks mandatory fields, link fields, and data types.
    
    Args:
        doctype: The DocType
        data: Dictionary of field values to validate
    
    Returns:
        JSON string with validation results and any errors.
    """
    try:
        meta = frappe.get_meta(doctype)
        errors = []
        warnings = []
        
        # Check mandatory fields
        for field in meta.fields:
            if field.reqd and field.fieldname not in data:
                # Skip system fields
                if field.fieldname not in ["name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"]:
                    if not field.default:
                        errors.append(f"Missing mandatory field: {field.label or field.fieldname}")
        
        # Validate field values
        for fieldname, value in data.items():
            field = meta.get_field(fieldname)
            if not field:
                warnings.append(f"Unknown field: {fieldname}")
                continue
            
            if field.read_only:
                warnings.append(f"Field '{fieldname}' is read-only")
            
            # Validate Link fields
            if field.fieldtype == "Link" and value and field.options:
                if not frappe.db.exists(field.options, value):
                    errors.append(f"Invalid {field.label or fieldname}: '{value}' does not exist in {field.options}")
            
            # Validate Select fields
            if field.fieldtype == "Select" and value and field.options:
                valid_options = field.options.split("\n")
                if value not in valid_options:
                    errors.append(f"Invalid {field.label or fieldname}: '{value}' is not a valid option")
            
            # Validate numeric fields
            if field.fieldtype in ["Int", "Float", "Currency", "Percent"]:
                if value is not None and not isinstance(value, (int, float)):
                    try:
                        float(value)
                    except:
                        errors.append(f"Field '{fieldname}' must be a number")
        
        return json.dumps({
            "success": len(errors) == 0,
            "doctype": doctype,
            "errors": errors,
            "warnings": warnings,
            "message": "Validation passed" if not errors else "Validation failed"
        }, indent=2)
        
    except Exception as e:
        _log_agent_error("Agent Tool Error", f"validate_document_data error: {e}")
        return json.dumps({"success": False, "error": str(e), "traceback": frappe.get_traceback()})


@tool
def get_document_info(doctype: str, name: str) -> str:
    """
    Gets information about an existing document including its current state.
    Use this before planning updates, submits, or cancels.
    
    Args:
        doctype: The DocType
        name: The document name/ID
    
    Returns:
        JSON string with document information.
    """
    try:
        if not frappe.db.exists(doctype, name):
            return json.dumps({
                "success": False,
                "error": f"{doctype} '{name}' does not exist"
            })
        
        if not frappe.has_permission(doctype, "read", name):
            return json.dumps({
                "success": False,
                "error": f"No permission to read {doctype} '{name}'"
            })
        
        doc = frappe.get_doc(doctype, name)
        
        # Get key information
        info = {
            "success": True,
            "doctype": doctype,
            "name": doc.name,
            "docstatus": doc.docstatus,
            "status_label": "Draft" if doc.docstatus == 0 else ("Submitted" if doc.docstatus == 1 else "Cancelled"),
            "owner": doc.owner,
            "creation": str(doc.creation),
            "modified": str(doc.modified),
            "modified_by": doc.modified_by
        }
        
        # Add common fields if they exist
        for field in ["title", "customer", "supplier", "company", "posting_date", "status"]:
            if hasattr(doc, field) and getattr(doc, field):
                info[field] = getattr(doc, field)
        
        return json.dumps(info, indent=2, default=str)
        
    except Exception as e:
        _log_agent_error("Agent Tool Error", f"get_document_info error: {e}")
        return json.dumps({"success": False, "error": str(e), "traceback": frappe.get_traceback()})


@tool
def plan_create_document(doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates a plan to create a new document.
    Does NOT perform the creation - generates a plan for user approval.
    
    Args:
        doctype: The DocType to create (e.g., "Item", "Customer")
        data: Dictionary of field values for the new document
    
    Returns:
        Plan dictionary that will be shown to user for approval.
    """
    return {
        "action": "create",
        "doctype": doctype,
        "data": data,
        "description": f"Create new {doctype}",
        "fields_to_set": list(data.keys())
    }


@tool
def plan_update_document(doctype: str, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Creates a plan to update an existing document.
    Does NOT perform the update - generates a plan for user approval.
    
    Args:
        doctype: The DocType
        name: Document name/ID to update
        data: Dictionary of fields to update
    
    Returns:
        Plan dictionary that will be shown to user for approval.
    """
    return {
        "action": "update",
        "doctype": doctype,
        "name": name,
        "data": data,
        "description": f"Update {doctype} {name}",
        "fields_to_set": list(data.keys())
    }


@tool
def plan_submit_document(doctype: str, name: str) -> Dict[str, Any]:
    """
    Creates a plan to submit a document.
    Submitting locks the document and triggers workflows.
    Does NOT perform submission - generates a plan for user approval.
    
    Args:
        doctype: The DocType
        name: Document name/ID to submit
    
    Returns:
        Plan dictionary that will be shown to user for approval.
    """
    return {
        "action": "submit",
        "doctype": doctype,
        "name": name,
        "description": f"Submit {doctype} {name}"
    }


@tool
def plan_cancel_document(doctype: str, name: str) -> Dict[str, Any]:
    """
    Creates a plan to cancel a document.
    Cancelling reverses the transaction and linked documents.
    Does NOT perform cancellation - generates a plan for user approval.
    
    Args:
        doctype: The DocType
        name: Document name/ID to cancel
    
    Returns:
        Plan dictionary that will be shown to user for approval.
    """
    return {
        "action": "cancel",
        "doctype": doctype,
        "name": name,
        "description": f"Cancel {doctype} {name}"
    }


# ============================================================
# Execution Functions (called after user approval)
# ============================================================

def execute_create_document(doctype: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute document creation with full Frappe validation."""
    try:
        # Check permission
        if not frappe.has_permission(doctype, "create"):
            return {"success": False, "error": f"No permission to create {doctype}"}
        
        # Prepare document data
        doc_data = data.copy()
        doc_data["doctype"] = doctype
        
        # Create document - Frappe will validate
        doc = frappe.get_doc(doc_data)
        
        # Insert with full validation (runs validate, before_insert, etc.)
        doc.insert()

        if doctype == "HD Ticket":
            from ampower_jive.hd_tickets.services.ticket_write_service import TicketWriteService

            TicketWriteService().ensure_initial_communication(doc)
        
        frappe.db.commit()
        
        return {
            "success": True, 
            "message": f"{doctype} '{doc.name}' created successfully.",
            "name": doc.name,
            "doctype": doctype
        }
        
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Validation error: {str(e)}", "traceback": frappe.get_traceback()}
    except frappe.PermissionError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Permission denied: {str(e)}", "traceback": frappe.get_traceback()}
    except Exception as e:
        frappe.db.rollback()
        _log_agent_error("Agent Execute Error", f"Create document error: {e}")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def execute_add_comment(ticket_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a planned internal comment on an HD ticket."""
    try:
        from ampower_jive.hd_tickets.services.ticket_write_service import TicketWriteService

        result = TicketWriteService().add_comment(
            ticket_id=ticket_name,
            content=(data or {}).get("content", ""),
        )
        if not result.get("success"):
            frappe.db.rollback()
            return result

        frappe.db.commit()
        return result
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Validation error: {str(e)}", "traceback": frappe.get_traceback()}
    except frappe.PermissionError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Permission denied: {str(e)}", "traceback": frappe.get_traceback()}
    except Exception as e:
        frappe.db.rollback()
        _log_agent_error("Agent Execute Error", f"Add comment error: {e}")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def execute_add_communication(ticket_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a planned communication on an HD ticket."""
    try:
        from ampower_jive.hd_tickets.services.ticket_write_service import TicketWriteService

        result = TicketWriteService().add_communication(
            ticket_id=ticket_name,
            message=(data or {}).get("message", ""),
        )
        if not result.get("success"):
            frappe.db.rollback()
            return result

        frappe.db.commit()
        return result
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Validation error: {str(e)}", "traceback": frappe.get_traceback()}
    except frappe.PermissionError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Permission denied: {str(e)}", "traceback": frappe.get_traceback()}
    except Exception as e:
        frappe.db.rollback()
        _log_agent_error("Agent Execute Error", f"Add communication error: {e}")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def execute_update_document(doctype: str, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute document update with full Frappe validation."""
    try:
        # Check document exists
        if not frappe.db.exists(doctype, name):
            return {"success": False, "error": f"{doctype} '{name}' does not exist"}
        
        # Check permission
        if not frappe.has_permission(doctype, "write", name):
            return {"success": False, "error": f"No permission to update {doctype} '{name}'"}
        
        # Get document
        doc = frappe.get_doc(doctype, name)
        
        # Check if document is editable (not submitted or cancelled)
        if doc.docstatus == 1:
            return {"success": False, "error": f"{doctype} '{name}' is submitted and cannot be edited"}
        if doc.docstatus == 2:
            return {"success": False, "error": f"{doctype} '{name}' is cancelled and cannot be edited"}
        
        # Update fields
        doc.update(data)
        
        # Save with full validation
        doc.save()
        
        frappe.db.commit()
        
        return {
            "success": True,
            "message": f"{doctype} '{name}' updated successfully.",
            "name": name,
            "doctype": doctype,
            "fields_updated": list(data.keys())
        }
        
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Validation error: {str(e)}", "traceback": frappe.get_traceback()}
    except frappe.PermissionError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Permission denied: {str(e)}", "traceback": frappe.get_traceback()}
    except Exception as e:
        frappe.db.rollback()
        _log_agent_error("Agent Execute Error", f"Update document error: {e}")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def execute_submit_document(doctype: str, name: str) -> Dict[str, Any]:
    """Execute document submission with full Frappe validation."""
    try:
        # Check document exists
        if not frappe.db.exists(doctype, name):
            return {"success": False, "error": f"{doctype} '{name}' does not exist"}
        
        # Check permission
        if not frappe.has_permission(doctype, "submit", name):
            return {"success": False, "error": f"No permission to submit {doctype} '{name}'"}
        
        # Get document
        doc = frappe.get_doc(doctype, name)
        
        # Check if document can be submitted
        if doc.docstatus != 0:
            status = "Submitted" if doc.docstatus == 1 else "Cancelled"
            return {"success": False, "error": f"{doctype} '{name}' is already {status}"}
        
        # Submit with full validation (runs validate, on_submit, etc.)
        doc.submit()
        
        frappe.db.commit()
        
        return {
            "success": True,
            "message": f"{doctype} '{name}' submitted successfully.",
            "name": name,
            "doctype": doctype
        }
        
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Validation error: {str(e)}", "traceback": frappe.get_traceback()}
    except frappe.PermissionError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Permission denied: {str(e)}", "traceback": frappe.get_traceback()}
    except Exception as e:
        frappe.db.rollback()
        _log_agent_error("Agent Execute Error", f"Submit document error: {e}")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def execute_cancel_document(doctype: str, name: str) -> Dict[str, Any]:
    """Execute document cancellation with full Frappe validation."""
    try:
        # Check document exists
        if not frappe.db.exists(doctype, name):
            return {"success": False, "error": f"{doctype} '{name}' does not exist"}
        
        # Check permission
        if not frappe.has_permission(doctype, "cancel", name):
            return {"success": False, "error": f"No permission to cancel {doctype} '{name}'"}
        
        # Get document
        doc = frappe.get_doc(doctype, name)
        
        # Check if document can be cancelled
        if doc.docstatus != 1:
            status = "Draft" if doc.docstatus == 0 else "Already Cancelled"
            return {"success": False, "error": f"{doctype} '{name}' is {status} and cannot be cancelled"}
        
        # Cancel with full validation (runs before_cancel, on_cancel, etc.)
        doc.cancel()
        
        frappe.db.commit()
        
        return {
            "success": True,
            "message": f"{doctype} '{name}' cancelled successfully.",
            "name": name,
            "doctype": doctype
        }
        
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Validation error: {str(e)}", "traceback": frappe.get_traceback()}
    except frappe.PermissionError as e:
        frappe.db.rollback()
        return {"success": False, "error": f"Permission denied: {str(e)}", "traceback": frappe.get_traceback()}
    except Exception as e:
        frappe.db.rollback()
        _log_agent_error("Agent Execute Error", f"Cancel document error: {e}")
        return {"success": False, "error": str(e), "traceback": frappe.get_traceback()}


def get_execution_tool(action: str):
    """Get the execution function for an action."""
    tools = {
        "create": execute_create_document,
        "update": execute_update_document,
        "submit": execute_submit_document,
        "cancel": execute_cancel_document,
        "add_comment": execute_add_comment,
        "add_communication": execute_add_communication,
    }
    return tools.get(action)


def execute_planned_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a cached plan item using the correct execution signature."""
    exec_tool = get_execution_tool(action.get("action"))
    if not exec_tool:
        return {
            "success": False,
            "error": f"Unsupported action '{action.get('action')}'",
        }

    action_name = action.get("action")
    if action_name == "create":
        return exec_tool(action.get("doctype"), action.get("data"))
    if action_name == "update":
        return exec_tool(action.get("doctype"), action.get("name"), action.get("data"))
    if action_name in {"add_comment", "add_communication"}:
        return exec_tool(action.get("name"), action.get("data"))
    return exec_tool(action.get("doctype"), action.get("name"))


def get_agent_tools() -> List[Any]:
    """Returns list of agent mode tools for LLM."""
    return [
        get_document_fields,
        validate_link_field,
        validate_document_data,
        get_document_info,
        plan_create_document,
        plan_update_document,
        plan_submit_document,
        plan_cancel_document,
    ]
