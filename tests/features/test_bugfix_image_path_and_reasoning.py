"""Tests for image path resolution and reasoning (thinking_budget) wiring.

Bug 1: Uploaded image paths were relative to .lemon/ but the orchestrator
        checked Path(f["path"]).exists() from CWD — file never found.
Fix:    socket_chat.py now resolves to absolute path before passing to orchestrator.

Bug 2: Extended thinking (reasoning) was not enabled — orchestrator never
        passed thinking_budget to call_llm_with_tools.
Fix:    Added thinking_budget param to call_llm_with_tools and wired through
        orchestrator.respond() and socket_chat.py.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


class TestImagePathResolution:
    """Verify socket_chat resolves uploaded file paths to absolute."""

    def test_save_uploaded_files_produces_absolute_paths(self, tmp_path: Path):
        """After _save_uploaded_files, each saved path must be absolute."""
        from src.backend.tasks.chat_task import ChatTask
        from src.backend.tasks.sse import EventSink
        from src.backend.storage.workflows import WorkflowStore

        # Create a minimal 1x1 white PNG as a data URL
        import base64
        # Minimal valid PNG (1x1 white pixel)
        png_bytes = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
            b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
            b"\x00\x00\x00IEND\xaeB`\x82"
        )
        data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode()

        # Build a ChatTask with repo_root set to tmp_path
        conv_store_mock = MagicMock()
        wf_store = WorkflowStore(tmp_path / ".lemon" / "workflows.sqlite")

        task = ChatTask(
            sink=EventSink(),
            conversation_store=conv_store_mock,
            repo_root=tmp_path,
            workflow_store=wf_store,
            user_id="test-user",
            task_id="test-task",
            message="hello",
            conversation_id=None,
            files_data=[{
                "id": "f1",
                "name": "test.png",
                "data_url": data_url,
                "purpose": "unclassified",
            }],
            workflow=None,
            analysis=None,
        )

        ok = task._save_uploaded_files()
        assert ok, "Expected _save_uploaded_files to succeed"
        assert len(task.saved_file_paths) == 1

        saved_path = task.saved_file_paths[0]["path"]
        # Path must be absolute so orchestrator can read it directly
        assert Path(saved_path).is_absolute(), (
            f"Expected absolute path, got: {saved_path}"
        )
        # The file must actually exist on disk
        assert Path(saved_path).exists(), (
            f"Saved file does not exist at: {saved_path}"
        )


class TestReasoningWiring:
    """Verify thinking parameter is wired through the LLM call chain."""

    def test_call_llm_accepts_thinking_and_effort(self):
        """call_llm must accept thinking (bool), effort, and on_thinking params."""
        from src.backend.llm.client import call_llm

        sig = inspect.signature(call_llm)
        assert "thinking" in sig.parameters, (
            "call_llm is missing thinking parameter"
        )
        assert "effort" in sig.parameters, (
            "call_llm is missing effort parameter"
        )
        assert "on_thinking" in sig.parameters, (
            "call_llm is missing on_thinking parameter"
        )
        # effort defaults to "high"
        assert sig.parameters["effort"].default == "high"

    def test_orchestrator_respond_accepts_thinking(self):
        """orchestrator.respond() must accept thinking param."""
        from src.backend.agents.orchestrator import Orchestrator

        sig = inspect.signature(Orchestrator.respond)
        assert "thinking" in sig.parameters, (
            "Orchestrator.respond is missing thinking parameter"
        )

    def test_thinking_forwarded_to_llm(self):
        """Orchestrator.respond must forward thinking=True to call_llm."""
        from src.backend.agents.orchestrator_factory import build_orchestrator
        from src.backend.llm.client import LLMResponse

        orch = build_orchestrator(Path("."))

        captured_kwargs = {}

        def fake_llm(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return LLMResponse(text="I'm a response")

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=fake_llm):
            orch.respond("test message", thinking=True)

        assert "thinking" in captured_kwargs, (
            "thinking not forwarded to call_llm"
        )
        assert captured_kwargs["thinking"] is True

    def test_ws_chat_passes_thinking(self):
        """ChatTask.run must pass thinking=True to orchestrator.respond()."""
        # Verify the source code contains thinking= in the respond() call
        from src.backend.tasks import chat_task

        source = inspect.getsource(chat_task.ChatTask.run)
        assert "thinking=" in source, (
            "ChatTask.run does not pass thinking to orchestrator.respond()"
        )

    def test_on_thinking_forwarded_to_llm(self):
        """Orchestrator.respond must forward on_thinking to call_llm."""
        from src.backend.agents.orchestrator_factory import build_orchestrator
        from src.backend.llm.client import LLMResponse

        orch = build_orchestrator(Path("."))
        captured_kwargs = {}

        def fake_llm(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return LLMResponse(text="response")

        thinking_chunks = []
        def my_thinking(chunk: str) -> None:
            thinking_chunks.append(chunk)

        with patch("src.backend.agents.orchestrator.call_llm", side_effect=fake_llm):
            orch.respond("test", thinking=True, on_thinking=my_thinking)

        assert captured_kwargs.get("on_thinking") is my_thinking

    def test_stream_thinking_emits_chat_thinking(self):
        """ChatTask.stream_thinking must emit chat_thinking event via the sink."""
        from src.backend.tasks.chat_task import ChatTask
        from src.backend.tasks.sse import EventSink

        mock_sink = MagicMock(spec=EventSink)
        mock_sink.is_closed = False

        task = ChatTask(
            sink=mock_sink,
            conversation_store=MagicMock(),
            repo_root=Path("/tmp"),
            workflow_store=MagicMock(),
            user_id="u1",
            task_id="t1",
            message="hi",
            conversation_id=None,
            files_data=[],
            workflow=None,
            analysis=None,
        )

        task.stream_thinking("Analyzing the workflow...")

        # ChatTask._emit calls sink.push(event, payload)
        mock_sink.push.assert_called_once_with(
            "chat_thinking",
            {"chunk": "Analyzing the workflow...", "task_id": "t1"},
        )

    def test_stream_thinking_skips_empty(self):
        """stream_thinking should not emit for empty chunks."""
        from src.backend.tasks.chat_task import ChatTask
        from src.backend.tasks.sse import EventSink

        mock_sink = MagicMock(spec=EventSink)
        mock_sink.is_closed = False

        task = ChatTask(
            sink=mock_sink,
            conversation_store=MagicMock(),
            repo_root=Path("/tmp"),
            workflow_store=MagicMock(),
            user_id="u1",
            task_id="t1",
            message="hi",
            conversation_id=None,
            files_data=[],
            workflow=None,
            analysis=None,
        )

        task.stream_thinking("")
        mock_sink.push.assert_not_called()

    def test_thinking_payload_added_when_enabled(self):
        """call_llm must add adaptive thinking payload when thinking=True."""
        from src.backend.llm.client import call_llm

        # Patch the Anthropic client to capture the payload
        captured_payload = {}

        class FakeStream:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def __iter__(self):
                return iter([])
            def get_final_message(self):
                return MagicMock(content=[], usage=MagicMock(input_tokens=0, output_tokens=0), model="test")

        class FakeMessages:
            def stream(self, **kwargs):
                captured_payload.update(kwargs)
                return FakeStream()

        fake_client = MagicMock()
        fake_client.messages = FakeMessages()

        with patch("src.backend.llm.client.get_anthropic_client", return_value=fake_client), \
             patch("src.backend.llm.client.get_anthropic_model", return_value="claude-opus-4-6"), \
             patch("src.backend.llm.client._record_tokens"):
            try:
                call_llm(
                    [{"role": "user", "content": "test"}],
                    thinking=True,
                )
            except Exception:
                pass  # May fail on response parsing, that's OK — we just need the payload

        assert "thinking" in captured_payload, (
            "thinking key not added to Anthropic API payload"
        )
        assert captured_payload["thinking"] == {"type": "adaptive"}

        # Effort parameter should always be present (default "high")
        assert "output_config" in captured_payload, (
            "output_config key not added to Anthropic API payload"
        )
        assert captured_payload["output_config"] == {"effort": "high"}
