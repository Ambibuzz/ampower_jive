"""
GIF Generator for Helpdesk Responses
Creates animated GIFs summarizing helpdesk answers using Pillow.
"""

import frappe
import os
import re
import hashlib
from io import BytesIO
from typing import List, Tuple, Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


# Color schemes for different themes
THEMES = {
    "dark": {
        "background": (15, 15, 20),
        "text": (229, 231, 235),
        "accent": (99, 102, 241),
        "highlight": (139, 92, 246),
        "success": (16, 185, 129),
        "step_bg": (31, 41, 55),
        "border": (55, 65, 81),
    },
    "light": {
        "background": (249, 250, 251),
        "text": (31, 41, 55),
        "accent": (79, 70, 229),
        "highlight": (124, 58, 237),
        "success": (5, 150, 105),
        "step_bg": (243, 244, 246),
        "border": (209, 213, 219),
    }
}


def extract_key_points(text: str, max_points: int = 5) -> List[str]:
    """Extract key points from helpdesk response text."""
    points = []
    
    # Try to find numbered steps (1. 2. 3. or 1) 2) 3))
    numbered = re.findall(r'(?:^|\n)\s*(?:\d+[\.\)]\s*)([^\n]+)', text)
    if numbered:
        points.extend([p.strip()[:80] for p in numbered[:max_points]])
    
    # Try to find bullet points (- or *)
    if not points:
        bullets = re.findall(r'(?:^|\n)\s*[-*•]\s*([^\n]+)', text)
        if bullets:
            points.extend([p.strip()[:80] for p in bullets[:max_points]])
    
    # Try to find bold text (**text** or __text__)
    if not points:
        bold = re.findall(r'\*\*([^*]+)\*\*|__([^_]+)__', text)
        for match in bold[:max_points]:
            point = match[0] or match[1]
            if point and len(point) > 10:
                points.append(point.strip()[:80])
    
    # Fallback: split into sentences and take key ones
    if not points:
        sentences = re.split(r'[.!?]\s+', text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 20 and len(sentence) < 100:
                points.append(sentence[:80])
                if len(points) >= max_points:
                    break
    
    # If still no points, create a summary
    if not points:
        words = text.split()
        if len(words) > 10:
            points.append(" ".join(words[:15]) + "...")
        else:
            points.append(text[:80])
    
    return points[:max_points]


def get_font(size: int = 16) -> ImageFont.FreeTypeFont:
    """Get a font, falling back to default if custom fonts aren't available."""
    # Try common system fonts
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except:
                continue
    
    # Fallback to default font
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except:
        return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = " ".join(current_line + [word])
        try:
            bbox = font.getbbox(test_line)
            width = bbox[2] - bbox[0]
        except:
            width = len(test_line) * 8
        
        if width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    
    if current_line:
        lines.append(" ".join(current_line))
    
    return lines


def create_frame(
    width: int,
    height: int,
    points: List[str],
    current_step: int,
    theme: dict,
    title: str = "Quick Guide"
) -> Image.Image:
    """Create a single frame of the GIF."""
    # Create image
    img = Image.new('RGB', (width, height), theme["background"])
    draw = ImageDraw.Draw(img)
    
    # Fonts
    title_font = get_font(24)
    step_font = get_font(16)
    number_font = get_font(14)
    
    # Draw header with gradient effect (simulated)
    header_height = 60
    for y in range(header_height):
        alpha = y / header_height
        r = int(theme["accent"][0] * (1 - alpha * 0.5))
        g = int(theme["accent"][1] * (1 - alpha * 0.5))
        b = int(theme["accent"][2] * (1 - alpha * 0.5))
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    # Draw title
    draw.text((20, 18), title, font=title_font, fill=(255, 255, 255))
    
    # Draw Ambibuzz branding
    brand_text = "by Ambibuzz"
    try:
        brand_bbox = step_font.getbbox(brand_text)
        brand_width = brand_bbox[2] - brand_bbox[0]
    except:
        brand_width = len(brand_text) * 8
    draw.text((width - brand_width - 20, 22), brand_text, font=step_font, fill=(200, 200, 255))
    
    # Draw steps
    y_offset = header_height + 20
    step_height = 50
    padding = 15
    
    for i, point in enumerate(points):
        is_current = i == current_step
        is_done = i < current_step
        
        # Step background
        step_y = y_offset + i * (step_height + 10)
        bg_color = theme["accent"] if is_current else (theme["success"] if is_done else theme["step_bg"])
        
        # Draw rounded rectangle for step
        draw.rounded_rectangle(
            [(padding, step_y), (width - padding, step_y + step_height)],
            radius=8,
            fill=bg_color,
            outline=theme["border"] if not is_current else theme["highlight"],
            width=2 if is_current else 1
        )
        
        # Step number circle
        circle_x = padding + 25
        circle_y = step_y + step_height // 2
        circle_radius = 12
        circle_color = (255, 255, 255) if is_current or is_done else theme["accent"]
        draw.ellipse(
            [(circle_x - circle_radius, circle_y - circle_radius),
             (circle_x + circle_radius, circle_y + circle_radius)],
            fill=circle_color
        )
        
        # Step number or checkmark
        number_color = theme["accent"] if not (is_current or is_done) else theme["background"]
        if is_done:
            # Draw checkmark
            draw.text((circle_x - 5, circle_y - 8), "✓", font=number_font, fill=number_color)
        else:
            draw.text((circle_x - 4, circle_y - 8), str(i + 1), font=number_font, fill=number_color)
        
        # Step text
        text_x = circle_x + circle_radius + 15
        text_color = (255, 255, 255) if is_current or is_done else theme["text"]
        
        # Wrap text if needed
        max_text_width = width - text_x - padding - 10
        wrapped = wrap_text(point, step_font, max_text_width)
        
        for j, line in enumerate(wrapped[:2]):  # Max 2 lines
            draw.text(
                (text_x, step_y + 8 + j * 18),
                line,
                font=step_font,
                fill=text_color
            )
    
    # Progress indicator at bottom
    progress_y = height - 25
    progress_width = width - 40
    progress_height = 6
    
    # Background bar
    draw.rounded_rectangle(
        [(20, progress_y), (20 + progress_width, progress_y + progress_height)],
        radius=3,
        fill=theme["step_bg"]
    )
    
    # Progress bar
    if len(points) > 0:
        filled_width = int(progress_width * (current_step + 1) / len(points))
        if filled_width > 0:
            draw.rounded_rectangle(
                [(20, progress_y), (20 + filled_width, progress_y + progress_height)],
                radius=3,
                fill=theme["accent"]
            )
    
    return img


def generate_helpdesk_gif(
    response_text: str,
    title: str = "Quick Guide",
    width: int = 480,
    height: int = 360,
    theme_name: str = "dark",
    frame_duration: int = 1500,
    max_points: int = 5
) -> Optional[str]:
    """
    Generate an animated GIF from helpdesk response text.
    
    Args:
        response_text: The helpdesk response text
        title: Title for the GIF
        width: GIF width in pixels
        height: GIF height in pixels
        theme_name: Color theme ('dark' or 'light')
        frame_duration: Duration of each frame in milliseconds
        max_points: Maximum number of points to show
    
    Returns:
        URL of the generated GIF file, or None if generation fails
    """
    if not PILLOW_AVAILABLE:
        frappe.log_error("Pillow not available for GIF generation", "GIF Generator")
        return None
    
    try:
        # Check if GIF generation is enabled (supports Jive Core mode)
        from ampower_jive.utils.config_provider import get_config_provider
        provider = get_config_provider()
        if not provider.is_feature_enabled("enable_gif_generation"):
            return None
        
        # Extract key points from response
        points = extract_key_points(response_text, max_points)
        
        if not points:
            return None
        
        # Get theme
        theme = THEMES.get(theme_name, THEMES["dark"])
        
        # Adjust height based on number of points
        calculated_height = max(height, 100 + len(points) * 60 + 40)
        
        # Create frames
        frames = []
        
        # Initial frame showing all steps (step -1 means none highlighted yet)
        intro_frame = create_frame(width, calculated_height, points, -1, theme, title)
        frames.append(intro_frame)
        
        # Frames for each step
        for i in range(len(points)):
            frame = create_frame(width, calculated_height, points, i, theme, title)
            frames.append(frame)
        
        # Final frame with all steps completed
        final_frame = create_frame(width, calculated_height, points, len(points), theme, title)
        frames.append(final_frame)
        frames.append(final_frame)  # Hold on final frame
        
        # Save GIF to BytesIO
        gif_buffer = BytesIO()
        
        # Save with proper durations
        durations = [frame_duration] * len(frames)
        durations[0] = 1000  # Intro frame shorter
        durations[-1] = 2000  # Final frame longer
        durations[-2] = 2000
        
        frames[0].save(
            gif_buffer,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=True
        )
        
        gif_buffer.seek(0)
        
        # Generate unique filename
        content_hash = hashlib.md5(response_text[:200].encode()).hexdigest()[:8]
        filename = f"helpdesk_guide_{content_hash}.gif"
        
        # Save as Frappe file
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "content": gif_buffer.getvalue(),
            "is_private": 0
        })
        file_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return file_doc.file_url
        
    except Exception as e:
        frappe.log_error(f"GIF generation error: {e}\n{frappe.get_traceback()}", "GIF Generator Error")
        return None


def generate_simple_gif(
    text: str,
    width: int = 400,
    height: int = 200
) -> Optional[str]:
    """
    Generate a simple animated text GIF.
    Fallback for when full GIF generation isn't suitable.
    """
    if not PILLOW_AVAILABLE:
        return None
    
    try:
        theme = THEMES["dark"]
        frames = []
        font = get_font(18)
        
        # Wrap text
        wrapped = wrap_text(text[:150], font, width - 40)
        
        # Create typing animation frames
        for i in range(len(wrapped) + 1):
            img = Image.new('RGB', (width, height), theme["background"])
            draw = ImageDraw.Draw(img)
            
            # Draw border
            draw.rounded_rectangle(
                [(5, 5), (width - 5, height - 5)],
                radius=10,
                outline=theme["accent"],
                width=2
            )
            
            # Draw text lines
            y = 30
            for j, line in enumerate(wrapped[:i]):
                draw.text((20, y + j * 25), line, font=font, fill=theme["text"])
            
            # Add cursor on current line
            if i < len(wrapped):
                cursor_x = 20
                if i > 0:
                    try:
                        bbox = font.getbbox(wrapped[i-1] if i > 0 else "")
                        cursor_x = 20 + (bbox[2] - bbox[0])
                    except:
                        pass
                draw.text((cursor_x, y + (i) * 25), "▌", font=font, fill=theme["accent"])
            
            frames.append(img)
        
        if not frames:
            return None
        
        # Save GIF
        gif_buffer = BytesIO()
        frames[0].save(
            gif_buffer,
            format='GIF',
            save_all=True,
            append_images=frames[1:],
            duration=300,
            loop=0
        )
        
        gif_buffer.seek(0)
        
        content_hash = hashlib.md5(text[:50].encode()).hexdigest()[:8]
        filename = f"helpdesk_text_{content_hash}.gif"
        
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": filename,
            "content": gif_buffer.getvalue(),
            "is_private": 0
        })
        file_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return file_doc.file_url
        
    except Exception as e:
        frappe.log_error(f"Simple GIF error: {e}", "GIF Generator Error")
        return None
