"""Miro API client for fetching board data.

This client wraps the Miro REST API v2 to retrieve board items
(shapes, connectors) for importing flowcharts into LEMON.

Usage:
    client = MiroClient(access_token="your-token")
    items = client.get_board_items("board_id")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("backend.miro")

# Miro API base URL
MIRO_API_BASE = "https://api.miro.com/v2"

# Request timeout in seconds
REQUEST_TIMEOUT = 30


@dataclass
class MiroBoard:
    """Miro board metadata."""

    id: str
    name: str
    description: str
    created_at: str
    modified_at: str


@dataclass
class MiroShape:
    """A shape item from a Miro board."""

    id: str
    shape_type: str  # e.g., "flow_chart_decision", "flow_chart_process"
    content: str  # Text content inside the shape
    x: float
    y: float
    width: float
    height: float
    raw_data: Dict[str, Any]  # Full API response for this item


@dataclass
class MiroConnector:
    """A connector (line) between two shapes on a Miro board."""

    id: str
    start_item_id: str
    end_item_id: str
    caption: str  # Text label on the connector (e.g., "Yes", "No")
    shape: str  # "straight", "elbowed", "curved"
    raw_data: Dict[str, Any]


class MiroAPIError(Exception):
    """Exception raised for Miro API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class MiroClient:
    """Client for interacting with the Miro REST API v2."""

    def __init__(self, access_token: str):
        """Initialize the Miro client.

        Args:
            access_token: Miro personal access token
        """
        self.access_token = access_token
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a request to the Miro API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/boards/{board_id}")
            params: Query parameters

        Returns:
            JSON response data

        Raises:
            MiroAPIError: If the request fails
        """
        url = f"{MIRO_API_BASE}{endpoint}"

        try:
            response = self._session.request(
                method,
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            # Handle specific error codes
            if response.status_code == 401:
                raise MiroAPIError(
                    "Invalid or expired Miro access token. Please reconnect your Miro account.",
                    status_code=401,
                )
            if response.status_code == 403:
                raise MiroAPIError(
                    "Access denied. Your token may not have permission to access this board.",
                    status_code=403,
                )
            if response.status_code == 404:
                raise MiroAPIError(
                    "Board not found. Please check the board URL/ID.",
                    status_code=404,
                )
            if response.status_code == 429:
                raise MiroAPIError(
                    "Rate limit exceeded. Please try again later.",
                    status_code=429,
                )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            raise MiroAPIError("Request to Miro API timed out")
        except requests.exceptions.ConnectionError:
            raise MiroAPIError("Could not connect to Miro API")
        except requests.exceptions.RequestException as e:
            raise MiroAPIError(f"Miro API request failed: {e}")

    def get_board(self, board_id: str) -> MiroBoard:
        """Get board metadata.

        Args:
            board_id: The Miro board ID

        Returns:
            MiroBoard object with board metadata
        """
        data = self._request("GET", f"/boards/{board_id}")

        return MiroBoard(
            id=data.get("id", board_id),
            name=data.get("name", "Untitled"),
            description=data.get("description", ""),
            created_at=data.get("createdAt", ""),
            modified_at=data.get("modifiedAt", ""),
        )

    def get_board_items(
        self,
        board_id: str,
        item_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get all items from a board with pagination.

        Args:
            board_id: The Miro board ID
            item_type: Optional filter by item type (e.g., "shape", "connector")

        Returns:
            List of item dictionaries
        """
        all_items: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        limit = 50  # Miro's max per request

        while True:
            params: Dict[str, Any] = {"limit": limit}
            if item_type:
                params["type"] = item_type
            if cursor:
                params["cursor"] = cursor

            data = self._request("GET", f"/boards/{board_id}/items", params=params)

            items = data.get("data", [])
            all_items.extend(items)

            # Check for more pages
            cursor = data.get("cursor")
            if not cursor or len(items) < limit:
                break

        logger.info(
            "Fetched %d items from board %s (type=%s)",
            len(all_items),
            board_id,
            item_type or "all",
        )
        return all_items

    def get_shapes(self, board_id: str) -> List[MiroShape]:
        """Get all shape items from a board.

        Args:
            board_id: The Miro board ID

        Returns:
            List of MiroShape objects
        """
        items = self.get_board_items(board_id, item_type="shape")
        shapes = []

        for item in items:
            data = item.get("data", {})
            geometry = item.get("geometry", {})
            position = item.get("position", {})

            shape_type = data.get("shape", "rectangle")
            content = data.get("content", "")
            # Log full data structure for debugging shape type issues
            logger.info(
                "Miro shape: id=%s, type='%s', content='%s', all_data_keys=%s",
                item.get("id", "?"),
                shape_type,
                content[:50] if content else "(empty)",
                list(data.keys()),
            )

            shape = MiroShape(
                id=item.get("id", ""),
                shape_type=shape_type,
                content=content,
                x=position.get("x", 0),
                y=position.get("y", 0),
                width=geometry.get("width", 100),
                height=geometry.get("height", 100),
                raw_data=item,
            )
            shapes.append(shape)

        return shapes

    def get_connectors(self, board_id: str) -> List[MiroConnector]:
        """Get all connector items from a board.

        Miro has a separate endpoint for connectors: /v2/boards/{board_id}/connectors

        Args:
            board_id: The Miro board ID

        Returns:
            List of MiroConnector objects
        """
        connectors = []
        cursor: Optional[str] = None
        limit = 50

        while True:
            params: Dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor

            data = self._request("GET", f"/boards/{board_id}/connectors", params=params)

            items = data.get("data", [])
            for item in items:
                start_item = item.get("startItem", {})
                end_item = item.get("endItem", {})
                captions = item.get("captions", [])

                # Extract caption text (first caption if multiple)
                caption = ""
                if captions and len(captions) > 0:
                    caption = captions[0].get("content", "")

                connector = MiroConnector(
                    id=item.get("id", ""),
                    start_item_id=start_item.get("id", ""),
                    end_item_id=end_item.get("id", ""),
                    caption=caption,
                    shape=item.get("shape", "straight"),
                    raw_data=item,
                )
                connectors.append(connector)

            # Check for more pages
            cursor = data.get("cursor")
            if not cursor or len(items) < limit:
                break

        logger.info("Fetched %d connectors from board %s", len(connectors), board_id)
        return connectors

    def get_user_boards(self, limit: int = 50) -> List[MiroBoard]:
        """Get list of boards accessible to the user.

        Args:
            limit: Maximum number of boards to return

        Returns:
            List of MiroBoard objects
        """
        data = self._request("GET", "/boards", params={"limit": limit})
        boards = []

        for item in data.get("data", []):
            board = MiroBoard(
                id=item.get("id", ""),
                name=item.get("name", "Untitled"),
                description=item.get("description", ""),
                created_at=item.get("createdAt", ""),
                modified_at=item.get("modifiedAt", ""),
            )
            boards.append(board)

        return boards

    def test_connection(self) -> bool:
        """Test if the access token is valid.

        Returns:
            True if connection is successful
        """
        try:
            # Try to list boards with limit=1 to test the connection
            self._request("GET", "/boards", params={"limit": 1})
            return True
        except MiroAPIError:
            return False


def extract_board_id(url_or_id: str) -> str:
    """Extract board ID from a Miro URL or return the ID as-is.

    Handles URLs like:
        - https://miro.com/app/board/uXjVK5jR2xc=/
        - https://miro.com/app/board/uXjVK5jR2xc=
        - uXjVK5jR2xc=

    Args:
        url_or_id: Miro board URL or ID

    Returns:
        The board ID

    Raises:
        ValueError: If the URL/ID format is invalid
    """
    url_or_id = url_or_id.strip()

    # If it looks like a URL, parse it
    if url_or_id.startswith("http"):
        parsed = urlparse(url_or_id)

        # Expected path: /app/board/{board_id}/
        path_match = re.match(r"/app/board/([^/]+)/?", parsed.path)
        if path_match:
            return path_match.group(1)

        raise ValueError(
            f"Could not extract board ID from URL: {url_or_id}. "
            "Expected format: https://miro.com/app/board/{board_id}/"
        )

    # Assume it's already a board ID
    if not url_or_id:
        raise ValueError("Board ID cannot be empty")

    return url_or_id
