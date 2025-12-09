"""Utilities for making API requests."""

import os
import json
import base64
from io import BytesIO
from pathlib import Path
from dotenv import load_dotenv
from anthropic import AnthropicFoundry
from PIL import Image

# Load environment variables from .env file
load_dotenv()

# Path to token tracking file
TOKENS_FILE = Path(__file__).parent.parent.parent / "tokens.json"


def get_anthropic_client():
    """Initialize and return an AnthropicFoundry client using environment variables.
    
    Returns:
        AnthropicFoundry: Configured client instance
        
    Raises:
        ValueError: If required environment variables are missing
    """
    endpoint = os.getenv("ENDPOINT")
    deployment_name = os.getenv("DEPLOYMENT_NAME")
    api_key = os.getenv("API_KEY")
    
    if not all([endpoint, deployment_name, api_key]):
        raise ValueError("Missing required environment variables: ENDPOINT, DEPLOYMENT_NAME, or API_KEY")
    
    return AnthropicFoundry(
        api_key=api_key,
        base_url=endpoint
    )


def load_token_tracking():
    """Load cumulative token usage from tokens.json.
    
    Returns:
        dict: Dictionary with token usage statistics
    """
    if TOKENS_FILE.exists():
        try:
            with open(TOKENS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # If file is corrupted or can't be read, start fresh
            pass
    
    # Default structure if file doesn't exist
    return {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_tokens": 0,
        "request_count": 0
    }


def save_token_tracking(token_data):
    """Save cumulative token usage to tokens.json.
    
    Args:
        token_data (dict): Dictionary with token usage statistics
    """
    try:
        with open(TOKENS_FILE, 'w') as f:
            json.dump(token_data, f, indent=2)
    except IOError as e:
        print(f"Warning: Could not save token tracking to {TOKENS_FILE}: {e}")


def track_tokens(response):
    """Track token usage from an API response and update cumulative totals.
    
    Args:
        response: API response object with usage information
    """
    # Get token usage from response
    # Anthropic API responses have usage.input_tokens and usage.output_tokens
    if hasattr(response, 'usage'):
        usage = response.usage
        input_tokens = getattr(usage, 'input_tokens', 0)
        output_tokens = getattr(usage, 'output_tokens', 0)
    else:
        # Fallback if usage structure is different
        input_tokens = getattr(response, 'input_tokens', 0)
        output_tokens = getattr(response, 'output_tokens', 0)
    
    # Load current totals
    token_data = load_token_tracking()
    
    # Update cumulative totals
    token_data["total_input_tokens"] += input_tokens
    token_data["total_output_tokens"] += output_tokens
    token_data["total_tokens"] = token_data["total_input_tokens"] + token_data["total_output_tokens"]
    token_data["request_count"] += 1
    
    # Save updated totals
    save_token_tracking(token_data)
    
    return token_data


def get_token_stats():
    """Get current cumulative token usage statistics.
    
    Returns:
        dict: Dictionary with current token usage statistics
    """
    return load_token_tracking()


def make_request(messages, max_tokens=1024, model=None, system=None):
    """Make a request to the Anthropic API.
    
    Args:
        messages (list): List of message dictionaries with 'role' and 'content' keys
        max_tokens (int, optional): Maximum tokens in response. Defaults to 1024.
        model (str, optional): Model deployment name. If None, uses DEPLOYMENT_NAME from env.
        system (str, optional): System prompt to guide the assistant's behavior.
        
    Returns:
        The response message object from the API
        
    Raises:
        ValueError: If required environment variables are missing
    """
    client = get_anthropic_client()
    
    if model is None:
        model = os.getenv("DEPLOYMENT_NAME")
        if not model:
            raise ValueError("DEPLOYMENT_NAME environment variable is required")
    
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    
    if system:
        kwargs["system"] = system
    
    message = client.messages.create(**kwargs)
    
    # Track token usage
    track_tokens(message)
    
    return message


def make_simple_request(user_message, max_tokens=1024, model=None):
    """Make a simple request with a single user message.
    
    Args:
        user_message (str): The user's message content
        max_tokens (int, optional): Maximum tokens in response. Defaults to 1024.
        model (str, optional): Model deployment name. If None, uses DEPLOYMENT_NAME from env.
        
    Returns:
        The response message object from the API
    """
    messages = [
        {"role": "user", "content": user_message}
    ]
    return make_request(messages, max_tokens=max_tokens, model=model)


def generate_green_image(width=512, height=512, output_path=None):
    """Generate a solid green image.
    
    Args:
        width (int, optional): Image width in pixels. Defaults to 512.
        height (int, optional): Image height in pixels. Defaults to 512.
        output_path (str, optional): Path to save the image. If None, image is not saved to disk.
        
    Returns:
        PIL.Image: The generated green image
    """
    # Create a solid green image (RGB: 0, 255, 0)
    image = Image.new('RGB', (width, height), color=(0, 255, 0))
    
    if output_path:
        image.save(output_path)
    
    return image


def image_to_base64(image, format='PNG'):
    """Convert a PIL Image to base64 encoded string.
    
    Args:
        image (PIL.Image): The image to encode
        format (str, optional): Image format. Defaults to 'PNG'.
        
    Returns:
        str: Base64 encoded image string
    """
    buffered = BytesIO()
    image.save(buffered, format=format)
    img_bytes = buffered.getvalue()
    img_base64 = base64.b64encode(img_bytes).decode('utf-8')
    return img_base64


def make_image_request(image, prompt, max_tokens=1024, model=None, image_format='PNG'):
    """Make a request to Claude with an image.
    
    Args:
        image (PIL.Image or str): PIL Image object or path to image file
        prompt (str): Text prompt/question about the image
        max_tokens (int, optional): Maximum tokens in response. Defaults to 1024.
        model (str, optional): Model deployment name. If None, uses DEPLOYMENT_NAME from env.
        image_format (str, optional): Image format if image is PIL.Image. Defaults to 'PNG'.
        
    Returns:
        The response message object from the API
    """
    # Load image if it's a file path
    if isinstance(image, str):
        img = Image.open(image)
    else:
        img = image
    
    # Convert image to base64
    img_base64 = image_to_base64(img, format=image_format)
    
    # Determine media type based on format
    media_type_map = {
        'PNG': 'image/png',
        'JPEG': 'image/jpeg',
        'JPG': 'image/jpeg',
        'WEBP': 'image/webp',
        'GIF': 'image/gif',
    }
    media_type = media_type_map.get(image_format.upper(), 'image/png')
    
    # Create message with image
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_base64
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }
    ]
    
    return make_request(messages, max_tokens=max_tokens, model=model)

