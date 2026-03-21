"""Tests for Phase 1: Image injection in orchestrator respond().

Verifies that when uploaded_files contain images, the user message
is built as a list of content blocks (image + text) rather than a
plain string.
"""

import base64
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from src.backend.llm.client import LLMResponse

import pytest


class TestImageInjection:
    """Test that orchestrator injects images into user messages."""

    def _make_orchestrator(self):
        """Create a minimal orchestrator with a mock registry."""
        from src.backend.agents.orchestrator import Orchestrator
        from src.backend.tools import ToolRegistry

        registry = ToolRegistry()
        return Orchestrator(registry)

    def test_image_injection_produces_content_blocks(self, tmp_path: Path):
        """When uploaded files contain an image, effective_message should be a list."""
        orch = self._make_orchestrator()

        # Create a fake image
        img_path = tmp_path / "test.jpeg"
        img_bytes = b"\xff\xd8\xff\xe0fake-jpeg"
        img_path.write_bytes(img_bytes)

        orch.uploaded_files = [
            {"name": "test.jpeg", "path": str(img_path), "file_type": "image"}
        ]

        # Patch call_llm to capture the messages it receives
        captured_messages = []

        def mock_llm(messages, **kwargs):
            captured_messages.append(messages)
            return LLMResponse(text="OK")

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=mock_llm):
            orch.respond("Analyze this workflow", has_files=orch.uploaded_files)

        # The user message (last before LLM call) should have content blocks
        assert len(captured_messages) == 1
        msgs = captured_messages[0]
        user_msg = msgs[-1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list), "Expected list content blocks for image"

        # First block should be the image
        img_block = user_msg["content"][0]
        assert img_block["type"] == "image"
        assert img_block["source"]["media_type"] == "image/jpeg"
        decoded = base64.b64decode(img_block["source"]["data"])
        assert decoded == img_bytes

        # Last block should be the text
        text_block = user_msg["content"][-1]
        assert text_block["type"] == "text"
        assert "Analyze this workflow" in text_block["text"]

    def test_no_image_keeps_string_message(self):
        """When no images are uploaded, effective_message stays as a string."""
        orch = self._make_orchestrator()

        captured_messages = []

        def mock_llm(messages, **kwargs):
            captured_messages.append(messages)
            return LLMResponse(text="OK")

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=mock_llm):
            orch.respond("Just a text message", has_files=[])

        msgs = captured_messages[0]
        user_msg = msgs[-1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], str)
        assert user_msg["content"] == "Just a text message"

    def test_png_media_type_detected(self, tmp_path: Path):
        """PNG images should get image/png media type."""
        orch = self._make_orchestrator()

        img_path = tmp_path / "diagram.png"
        img_path.write_bytes(b"\x89PNGfake")

        orch.uploaded_files = [
            {"name": "diagram.png", "path": str(img_path), "file_type": "image"}
        ]

        captured_messages = []

        def mock_llm(messages, **kwargs):
            captured_messages.append(messages)
            return LLMResponse(text="OK")

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=mock_llm):
            orch.respond("Check this", has_files=orch.uploaded_files)

        user_msg = captured_messages[0][-1]
        img_block = user_msg["content"][0]
        assert img_block["source"]["media_type"] == "image/png"

    def test_missing_image_file_skipped(self, tmp_path: Path):
        """If image path doesn't exist, it should be skipped (string message)."""
        orch = self._make_orchestrator()

        orch.uploaded_files = [
            {"name": "gone.jpeg", "path": str(tmp_path / "gone.jpeg"), "file_type": "image"}
        ]

        captured_messages = []

        def mock_llm(messages, **kwargs):
            captured_messages.append(messages)
            return LLMResponse(text="OK")

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=mock_llm):
            orch.respond("Check this", has_files=orch.uploaded_files)

        user_msg = captured_messages[0][-1]
        # No image blocks produced since file doesn't exist -> stays string
        assert isinstance(user_msg["content"], str)
