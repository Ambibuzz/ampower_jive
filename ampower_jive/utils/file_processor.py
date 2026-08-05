"""
File Processor for Helpdesk Context
Extracts text content from various file types (PDF, DOCX, CSV, TXT)
"""

import frappe
import os
import csv
from typing import Optional, Dict, Any, List


def extract_text_from_file(file_path: str) -> Dict[str, Any]:
    """
    Extract text content from a file based on its extension.
    
    Args:
        file_path: Path to the file (can be Frappe file URL like /private/files/doc.pdf)
        
    Returns:
        Dict with 'success', 'content', 'file_type', and optionally 'error'
    """
    try:
        # Get absolute path - handle Frappe file URLs
        abs_path = get_absolute_file_path(file_path)
        
        if not abs_path:
            return {"success": False, "error": f"Could not resolve file path: {file_path}"}
        
        if not os.path.exists(abs_path):
            return {"success": False, "error": f"File not found: {abs_path}"}
        
        # Get file extension
        _, ext = os.path.splitext(abs_path)
        ext = ext.lower()
        
        # Process based on file type
        if ext == '.pdf':
            return extract_from_pdf(abs_path)
        elif ext in ['.docx', '.doc']:
            return extract_from_docx(abs_path)
        elif ext == '.csv':
            return extract_from_csv(abs_path)
        elif ext in ['.txt', '.text', '.md', '.markdown']:
            return extract_from_text(abs_path)
        elif ext == '.json':
            return extract_from_json(abs_path)
        else:
            return {"success": False, "error": f"Unsupported file type: {ext}"}
            
    except Exception as e:
        frappe.log_error(f"File extraction error: {e}", "File Processor Error")
        return {"success": False, "error": str(e)}


def get_absolute_file_path(file_path: str) -> Optional[str]:
    """
    Convert a Frappe file URL to an absolute file system path.
    
    Args:
        file_path: Can be:
            - /private/files/filename.pdf
            - /files/filename.pdf
            - An absolute path
            - A File document name
            
    Returns:
        Absolute file system path or None if not found
    """
    if not file_path:
        return None
    
    # Already an absolute path
    if os.path.isabs(file_path) and os.path.exists(file_path):
        return file_path
    
    site_path = frappe.get_site_path()
    
    # Handle /private/files/ URLs
    if file_path.startswith('/private/files/'):
        abs_path = os.path.join(site_path, file_path.lstrip('/'))
        if os.path.exists(abs_path):
            return abs_path
    
    # Handle /files/ URLs (public files)
    if file_path.startswith('/files/'):
        abs_path = os.path.join(site_path, 'public', file_path.lstrip('/'))
        if os.path.exists(abs_path):
            return abs_path
    
    # Try as relative to site
    abs_path = os.path.join(site_path, file_path.lstrip('/'))
    if os.path.exists(abs_path):
        return abs_path
    
    # Try looking up in File doctype
    try:
        file_doc = frappe.get_doc("File", {"file_url": file_path})
        if file_doc:
            return get_absolute_file_path(file_doc.file_url)
    except:
        pass
    
    return None


def extract_from_pdf(file_path: str) -> Dict[str, Any]:
    """Extract text from PDF file."""
    try:
        from PyPDF2 import PdfReader
        
        reader = PdfReader(file_path)
        text_content = []
        
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_content.append(f"--- Page {i + 1} ---\n{page_text}")
        
        full_text = "\n\n".join(text_content)
        
        return {
            "success": True,
            "content": full_text,
            "file_type": "pdf",
            "page_count": len(reader.pages),
            "char_count": len(full_text)
        }
        
    except Exception as e:
        return {"success": False, "error": f"PDF extraction failed: {str(e)}"}


def extract_from_docx(file_path: str) -> Dict[str, Any]:
    """Extract text from DOCX file."""
    try:
        from docx import Document
        
        doc = Document(file_path)
        paragraphs = []
        
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs.append(para.text)
        
        # Also extract from tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        
        full_text = "\n\n".join(paragraphs)
        
        return {
            "success": True,
            "content": full_text,
            "file_type": "docx",
            "paragraph_count": len(paragraphs),
            "char_count": len(full_text)
        }
        
    except Exception as e:
        return {"success": False, "error": f"DOCX extraction failed: {str(e)}"}


def extract_from_csv(file_path: str) -> Dict[str, Any]:
    """Extract text from CSV file."""
    try:
        rows = []
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            
            if headers:
                rows.append("Headers: " + " | ".join(headers))
                
                for i, row in enumerate(reader):
                    if i >= 100:  # Limit to first 100 rows for context
                        rows.append(f"... and more rows (limited to 100 for context)")
                        break
                    row_text = " | ".join(str(cell) for cell in row)
                    rows.append(row_text)
        
        full_text = "\n".join(rows)
        
        return {
            "success": True,
            "content": full_text,
            "file_type": "csv",
            "row_count": len(rows),
            "char_count": len(full_text)
        }
        
    except Exception as e:
        return {"success": False, "error": f"CSV extraction failed: {str(e)}"}


def extract_from_text(file_path: str) -> Dict[str, Any]:
    """Extract text from plain text file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Limit content size
        max_chars = 50000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n... [Content truncated for context limit]"
        
        return {
            "success": True,
            "content": content,
            "file_type": "text",
            "char_count": len(content)
        }
        
    except Exception as e:
        return {"success": False, "error": f"Text extraction failed: {str(e)}"}


def extract_from_json(file_path: str) -> Dict[str, Any]:
    """Extract text from JSON file."""
    try:
        import json
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Convert JSON to readable text
        content = json.dumps(data, indent=2, ensure_ascii=False)
        
        # Limit content size
        max_chars = 50000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n... [Content truncated for context limit]"
        
        return {
            "success": True,
            "content": content,
            "file_type": "json",
            "char_count": len(content)
        }
        
    except Exception as e:
        return {"success": False, "error": f"JSON extraction failed: {str(e)}"}


def extract_from_file_doc(file_doc_name: str) -> Dict[str, Any]:
    """
    Extract text from a Frappe File document.
    
    Args:
        file_doc_name: Name of the File document
        
    Returns:
        Dict with extraction result
    """
    try:
        file_doc = frappe.get_doc("File", file_doc_name)
        file_url = file_doc.file_url
        
        return extract_text_from_file(file_url)
        
    except frappe.DoesNotExistError:
        return {"success": False, "error": f"File document not found: {file_doc_name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_supported_extensions() -> List[str]:
    """Return list of supported file extensions."""
    return ['.pdf', '.docx', '.doc', '.csv', '.txt', '.text', '.md', '.markdown', '.json']


def is_supported_file(filename: str) -> bool:
    """Check if a file type is supported."""
    _, ext = os.path.splitext(filename)
    return ext.lower() in get_supported_extensions()
