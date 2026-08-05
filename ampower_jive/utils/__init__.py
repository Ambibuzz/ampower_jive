"""AmPower Jive Utilities"""

try:
    from .gif_generator import generate_helpdesk_gif, generate_simple_gif
except ImportError:
    generate_helpdesk_gif = None
    generate_simple_gif = None

from .token_log_service import TokenLogService

from .file_processor import (
    extract_text_from_file,
    extract_from_file_doc,
    get_supported_extensions,
    is_supported_file
)
