"""Miro OAuth 2.0 authentication flow.

This module handles the OAuth flow for connecting user accounts to Miro.

Environment variables required:
    MIRO_CLIENT_ID: Your Miro app's client ID
    MIRO_CLIENT_SECRET: Your Miro app's client secret
    MIRO_REDIRECT_URI: The callback URL (e.g., http://localhost:5001/api/auth/miro/callback)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger("backend.miro_oauth")

# Miro OAuth endpoints
MIRO_AUTHORIZE_URL = "https://miro.com/oauth/authorize"
MIRO_TOKEN_URL = "https://api.miro.com/v1/oauth/token"

# Default redirect URI for local development
DEFAULT_REDIRECT_URI = "http://localhost:5001/api/auth/miro/callback"


@dataclass
class MiroTokens:
    """OAuth tokens from Miro."""
    access_token: str
    refresh_token: Optional[str]
    expires_at: Optional[datetime]
    token_type: str = "bearer"


class MiroOAuthError(Exception):
    """Error during Miro OAuth flow."""
    pass


def get_miro_config() -> dict:
    """Get Miro OAuth configuration from environment.

    Returns:
        Dict with client_id, client_secret, redirect_uri

    Raises:
        MiroOAuthError: If required env vars are missing
    """
    client_id = os.environ.get("MIRO_CLIENT_ID")
    client_secret = os.environ.get("MIRO_CLIENT_SECRET")
    redirect_uri = os.environ.get("MIRO_REDIRECT_URI", DEFAULT_REDIRECT_URI)

    if not client_id or not client_secret:
        raise MiroOAuthError(
            "MIRO_CLIENT_ID and MIRO_CLIENT_SECRET environment variables are required"
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def get_authorization_url(state: Optional[str] = None) -> str:
    """Generate the Miro authorization URL.

    Args:
        state: Optional state parameter for CSRF protection

    Returns:
        URL to redirect the user to for authorization
    """
    config = get_miro_config()

    params = {
        "response_type": "code",
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        # Request read access to boards
        # Note: Miro may require specific scopes depending on your app configuration
    }

    if state:
        params["state"] = state

    return f"{MIRO_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(code: str) -> MiroTokens:
    """Exchange an authorization code for access tokens.

    Args:
        code: The authorization code from the callback

    Returns:
        MiroTokens with access_token and optional refresh_token

    Raises:
        MiroOAuthError: If token exchange fails
    """
    config = get_miro_config()

    try:
        response = requests.post(
            MIRO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config["redirect_uri"],
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error_description") or error_data.get("error") or response.text
            logger.error("Token exchange failed: %s", error_msg)
            raise MiroOAuthError(f"Failed to exchange code: {error_msg}")

        data = response.json()

        # Calculate expiration time if expires_in is provided
        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])

        return MiroTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            token_type=data.get("token_type", "bearer"),
        )

    except requests.RequestException as e:
        logger.exception("Network error during token exchange")
        raise MiroOAuthError(f"Network error: {e}")


def refresh_access_token(refresh_token: str) -> MiroTokens:
    """Refresh an expired access token.

    Args:
        refresh_token: The refresh token

    Returns:
        New MiroTokens with fresh access_token

    Raises:
        MiroOAuthError: If refresh fails
    """
    config = get_miro_config()

    try:
        response = requests.post(
            MIRO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
        )

        if response.status_code != 200:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error_description") or error_data.get("error") or response.text
            logger.error("Token refresh failed: %s", error_msg)
            raise MiroOAuthError(f"Failed to refresh token: {error_msg}")

        data = response.json()

        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])

        return MiroTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),  # Keep old if not provided
            expires_at=expires_at,
            token_type=data.get("token_type", "bearer"),
        )

    except requests.RequestException as e:
        logger.exception("Network error during token refresh")
        raise MiroOAuthError(f"Network error: {e}")


def is_token_expired(expires_at: Optional[str]) -> bool:
    """Check if a token is expired or about to expire.

    Args:
        expires_at: ISO format expiration timestamp

    Returns:
        True if token is expired or expires within 5 minutes
    """
    if not expires_at:
        return False  # No expiration = doesn't expire

    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        # Consider expired if within 5 minutes of expiry
        buffer = timedelta(minutes=5)
        return datetime.now(timezone.utc) >= (expiry - buffer)
    except (ValueError, AttributeError):
        return False
