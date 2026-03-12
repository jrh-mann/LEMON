"""Tests for Phase 0: ViewImageTool and UpdatePlanTool.

Verifies:
1. ViewImageTool.execute() returns image content block with correct base64
2. UpdatePlanTool.execute() returns items correctly
3. _to_anthropic_messages() passes list content through tool results
4. Tool discovery picks up the new tools
"""

import base64
import json
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# ViewImageTool
# ---------------------------------------------------------------------------

class TestViewImageTool:
    def test_returns_image_content_block(self, tmp_path: Path):
        """ViewImageTool should return base64-encoded image as content list."""
        from src.backend.tools.workflow_analysis.view_image import ViewImageTool

        # Create a fake image file
        img_path = tmp_path / "test.jpeg"
        img_bytes = b"\xff\xd8\xff\xe0fake-jpeg-data"
        img_path.write_bytes(img_bytes)

        tool = ViewImageTool()
        result = tool.execute({}, session_state={
            "uploaded_files": [
                {"name": "test.jpeg", "path": str(img_path), "file_type": "image"}
            ],
        })

        assert result["success"] is True
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2

        # First block is the image
        img_block = result["content"][0]
        assert img_block["type"] == "image"
        assert img_block["source"]["type"] == "base64"
        assert img_block["source"]["media_type"] == "image/jpeg"
        # Verify base64 roundtrip
        decoded = base64.b64decode(img_block["source"]["data"])
        assert decoded == img_bytes

        # Second block is the text label
        text_block = result["content"][1]
        assert text_block["type"] == "text"
        assert "test.jpeg" in text_block["text"]

    def test_no_image_returns_error(self):
        """ViewImageTool should error when no image in session."""
        from src.backend.tools.workflow_analysis.view_image import ViewImageTool

        tool = ViewImageTool()
        result = tool.execute({}, session_state={"uploaded_files": []})

        assert result["success"] is False
        assert "No uploaded image" in result["error"]

    def test_missing_file_returns_error(self, tmp_path: Path):
        """ViewImageTool should error when image file doesn't exist on disk."""
        from src.backend.tools.workflow_analysis.view_image import ViewImageTool

        tool = ViewImageTool()
        result = tool.execute({}, session_state={
            "uploaded_files": [
                {"name": "gone.png", "path": str(tmp_path / "gone.png"), "file_type": "image"}
            ],
        })

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_png_media_type(self, tmp_path: Path):
        """ViewImageTool should detect PNG media type."""
        from src.backend.tools.workflow_analysis.view_image import ViewImageTool

        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png")

        tool = ViewImageTool()
        result = tool.execute({}, session_state={
            "uploaded_files": [
                {"name": "test.png", "path": str(img_path), "file_type": "image"}
            ],
        })

        assert result["success"] is True
        assert result["content"][0]["source"]["media_type"] == "image/png"


# ---------------------------------------------------------------------------
# UpdatePlanTool
# ---------------------------------------------------------------------------

class TestUpdatePlanTool:
    def test_returns_items(self):
        """UpdatePlanTool should return the items passed to it."""
        from src.backend.tools.workflow_analysis.update_plan import UpdatePlanTool

        tool = UpdatePlanTool()
        items = [
            {"text": "Identify nodes", "done": False},
            {"text": "Create workflow", "done": True},
        ]
        result = tool.execute({"items": items})

        assert result["success"] is True
        assert result["action"] == "plan_updated"
        assert result["items"] == items

    def test_invalid_items_type(self):
        """UpdatePlanTool should error when items is not a list."""
        from src.backend.tools.workflow_analysis.update_plan import UpdatePlanTool

        tool = UpdatePlanTool()
        result = tool.execute({"items": "not a list"})

        assert result["success"] is False


# ---------------------------------------------------------------------------
# Anthropic message conversion: list content passthrough
# ---------------------------------------------------------------------------

class TestAnthropicListContent:
    def test_list_content_passes_through_tool_result(self):
        """_to_anthropic_messages should pass list content in tool results directly."""
        from src.backend.llm.anthropic import _to_anthropic_messages

        image_content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "abc123"}},
            {"type": "text", "text": "Image: test.jpeg"},
        ]

        messages = [
            {"role": "user", "content": "analyze this"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "tc_1", "name": "view_image", "input": {}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc_1",
                "content": image_content,  # List content — should pass through
            },
        ]

        system, converted = _to_anthropic_messages(messages)

        # Find the tool_result message
        tool_result_msg = next(
            m for m in converted
            if m["role"] == "user" and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in m.get("content", [])
            )
        )

        tool_result_block = next(
            b for b in tool_result_msg["content"]
            if b.get("type") == "tool_result"
        )

        # List content should pass through directly (not json.dumps'd)
        assert isinstance(tool_result_block["content"], list)
        assert tool_result_block["content"] == image_content

    def test_string_content_stays_string(self):
        """String tool result content should remain a string."""
        from src.backend.llm.anthropic import _to_anthropic_messages

        messages = [
            {"role": "user", "content": "do something"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "tc_1", "name": "add_node", "input": {}}
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "tc_1",
                "content": '{"success": true}',
            },
        ]

        system, converted = _to_anthropic_messages(messages)
        tool_result_msg = next(
            m for m in converted
            if m["role"] == "user" and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in m.get("content", [])
            )
        )
        tool_result_block = next(
            b for b in tool_result_msg["content"]
            if b.get("type") == "tool_result"
        )
        assert isinstance(tool_result_block["content"], str)


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------

class TestToolDiscovery:
    def test_new_tools_discovered(self):
        """build_tool_registry should discover ViewImageTool and UpdatePlanTool."""
        from src.backend.tools.discovery import discover_tool_classes

        tool_classes = discover_tool_classes()
        names = {cls.name for cls in tool_classes if hasattr(cls, 'name')}
        assert "view_image" in names, f"view_image not found in {names}"
        assert "update_plan" in names, f"update_plan not found in {names}"
