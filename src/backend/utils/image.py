"""Shared helpers for the backend."""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path


def image_to_data_url(image_path: Path) -> str:
    """Read an image file and return a data URL."""
    suffix = image_path.suffix.lower().lstrip(".")
    media_type = "image/png"
    if suffix in {"jpg", "jpeg"}:
        media_type = "image/jpeg"
    elif suffix == "webp":
        media_type = "image/webp"
    elif suffix == "gif":
        media_type = "image/gif"

    raw = image_path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def image_to_data_url_with_grid(image_path: Path) -> str:
    """Read an image file, overlay a normalized 0-1000 coordinate grid, and return a data URL."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        # Fallback if Pillow is not installed
        return image_to_data_url(image_path)

    try:
        # Open and ensure RGB
        img = Image.open(image_path).convert("RGB")
        
        # Resize if huge to save LLM tokens/processing, while preserving aspect ratio
        max_size = 2000
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
        w, h = img.size
        
        # Create drawing context
        draw = ImageDraw.Draw(img)
        
        # Use default font
        font = ImageFont.load_default()
        
        # We want to draw a 10x10 grid.
        # The prompt says coords are 0-1000. So we draw lines every 10% (100 normalized units)
        grid_color = (255, 0, 0, 128)  # Semi-transparent red
        text_color = (255, 0, 0)
        text_bg = (255, 255, 255, 180)
        
        line_width = max(1, min(w, h) // 500)
        
        # Optional: Save for debugging if env var is set
        debug_save = os.environ.get("LEMON_DEBUG_GRID", "").lower() in {"1", "true"}

        # Draw vertical lines and X-axis labels (top and bottom)
        for i in range(11):
            normalized_x = i * 100
            actual_x = int(w * i / 10)
            
            # Line
            draw.line([(actual_x, 0), (actual_x, h)], fill=grid_color, width=line_width)
            
            # Text label
            label = str(normalized_x)
            
            # Top label
            bbox = draw.textbbox((actual_x, 5), label, font=font)
            draw.rectangle(bbox, fill=text_bg)
            draw.text((actual_x, 5), label, fill=text_color, font=font)
            
            # Bottom label
            bbox_bottom = draw.textbbox((actual_x, h - 15), label, font=font)
            draw.rectangle(bbox_bottom, fill=text_bg)
            draw.text((actual_x, h - 15), label, fill=text_color, font=font)

        # Draw horizontal lines and Y-axis labels (left and right)
        for i in range(11):
            normalized_y = i * 100
            actual_y = int(h * i / 10)
            
            # Line
            draw.line([(0, actual_y), (w, actual_y)], fill=grid_color, width=line_width)
            
            # Left label
            label = str(normalized_y)
            bbox = draw.textbbox((5, actual_y), label, font=font)
            draw.rectangle(bbox, fill=text_bg)
            draw.text((5, actual_y), label, fill=text_color, font=font)
            
            # Right label
            bbox_right = draw.textbbox((w - 30, actual_y), label, font=font)
            draw.rectangle(bbox_right, fill=text_bg)
            draw.text((w - 30, actual_y), label, fill=text_color, font=font)

        if debug_save:
            debug_path = image_path.parent / f"{image_path.stem}_grid_debug.jpg"
            img.save(debug_path, "JPEG", quality=85)

        # Save to bytes
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to generate image grid, falling back to original: %s", e)
        return image_to_data_url(image_path)

