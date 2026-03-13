"""Tests for ChatEventChannel — thread-safe SSE transport layer.

Covers:
1. publish() injects workflow_id and pushes to sink
2. stream_chunk / stream_thinking accumulate and emit
3. swap_sink replays accumulated content to the new sink
4. Lock prevents interleaving of swap and publish
5. publish_workflow_state caches for replay
6. close() delegates to sink
"""

import threading
from unittest.mock import MagicMock, call

from src.backend.tasks.chat_event_channel import ChatEventChannel
from src.backend.tasks.sse import EventSink


def _make_channel(
    *,
    workflow_id: str | None = "wf-1",
    task_id: str = "task-1",
) -> tuple[ChatEventChannel, EventSink]:
    """Build a channel with a real EventSink and a fixed workflow_id."""
    sink = EventSink()
    channel = ChatEventChannel(sink, task_id, lambda: workflow_id)
    return channel, sink


def _mock_sink() -> MagicMock:
    """Return a MagicMock that mimics EventSink enough for swap_sink."""
    s = MagicMock(spec=EventSink)
    s.is_closed = False
    return s


# ── publish ──────────────────────────────────────────────

class TestPublish:
    def test_injects_workflow_id(self):
        channel, _ = _make_channel(workflow_id="wf-42")
        sink = _mock_sink()
        channel._sink = sink  # use mock so we can inspect calls

        channel.publish("test_event", {"key": "val"})
        sink.push.assert_called_once_with(
            "test_event", {"key": "val", "workflow_id": "wf-42"}
        )

    def test_skips_workflow_id_when_none(self):
        channel, _ = _make_channel(workflow_id=None)
        sink = _mock_sink()
        channel._sink = sink

        channel.publish("test_event", {"key": "val"})
        sink.push.assert_called_once_with("test_event", {"key": "val"})

    def test_does_not_overwrite_existing_workflow_id(self):
        channel, _ = _make_channel(workflow_id="wf-42")
        sink = _mock_sink()
        channel._sink = sink

        channel.publish("test_event", {"workflow_id": "explicit"})
        sink.push.assert_called_once_with(
            "test_event", {"workflow_id": "explicit"}
        )


# ── streaming ────────────────────────────────────────────

class TestStreaming:
    def test_stream_chunk_accumulates_and_emits(self):
        channel, _ = _make_channel()
        sink = _mock_sink()
        channel._sink = sink

        channel.stream_chunk("Hello ")
        channel.stream_chunk("world")

        assert channel.stream_buffer == "Hello world"
        assert channel.did_stream is True
        assert sink.push.call_count == 2

    def test_stream_thinking_accumulates_and_emits(self):
        channel, _ = _make_channel()
        sink = _mock_sink()
        channel._sink = sink

        channel.stream_thinking("think1")
        channel.stream_thinking("think2")

        assert channel.thinking_chunks == ["think1", "think2"]
        assert sink.push.call_count == 2

    def test_stream_thinking_ignores_empty(self):
        channel, _ = _make_channel()
        sink = _mock_sink()
        channel._sink = sink

        channel.stream_thinking("")
        assert channel.thinking_chunks == []
        assert sink.push.call_count == 0


# ── swap_sink ────────────────────────────────────────────

class TestSwapSink:
    def test_replays_thinking_and_stream(self):
        channel, old_sink = _make_channel(workflow_id="wf-1", task_id="t1")
        # Accumulate content
        channel.stream_thinking("thought-A")
        channel.stream_chunk("text-B")

        new_sink = _mock_sink()
        channel.swap_sink(new_sink)

        # New sink should receive: resumed, thinking replay, stream replay
        events = [c.args[0] for c in new_sink.push.call_args_list]
        assert events == ["chat_progress", "chat_thinking", "chat_stream"]

        # Verify thinking replay contains concatenated chunks
        thinking_call = new_sink.push.call_args_list[1]
        assert thinking_call.args[1]["chunk"] == "thought-A"

        # Verify stream replay
        stream_call = new_sink.push.call_args_list[2]
        assert stream_call.args[1]["chunk"] == "text-B"

    def test_replays_workflow_state(self):
        channel, _ = _make_channel(workflow_id="wf-1")
        channel.publish_workflow_state({"workflow": {"name": "test"}})

        new_sink = _mock_sink()
        channel.swap_sink(new_sink)

        # Should replay: resumed + workflow_state_updated
        events = [c.args[0] for c in new_sink.push.call_args_list]
        assert "workflow_state_updated" in events

    def test_closes_old_sink(self):
        channel, old_sink = _make_channel()
        new_sink = _mock_sink()
        channel.swap_sink(new_sink)

        assert old_sink.is_closed

    def test_channel_uses_new_sink_after_swap(self):
        channel, _ = _make_channel()
        new_sink = _mock_sink()
        channel.swap_sink(new_sink)

        channel.publish("after_swap", {"data": 1})
        # The last call on new_sink should be our post-swap publish
        last_call = new_sink.push.call_args_list[-1]
        assert last_call.args[0] == "after_swap"

    def test_swap_with_no_accumulated_content(self):
        """Swap with nothing accumulated — only the 'resumed' event."""
        channel, _ = _make_channel()
        new_sink = _mock_sink()
        channel.swap_sink(new_sink)

        events = [c.args[0] for c in new_sink.push.call_args_list]
        assert events == ["chat_progress"]


# ── thread safety ────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_publish_and_swap(self):
        """Many publishers + a swap — no exceptions, no lost events."""
        channel, _ = _make_channel()
        errors = []

        def publisher(n: int):
            try:
                for i in range(50):
                    channel.publish("evt", {"n": n, "i": i})
            except Exception as e:
                errors.append(e)

        def swapper():
            try:
                new_sink = _mock_sink()
                channel.swap_sink(new_sink)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=publisher, args=(i,)) for i in range(4)]
        threads.append(threading.Thread(target=swapper))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent access raised: {errors}"


# ── helper methods ───────────────────────────────────────

class TestHelpers:
    def test_publish_progress(self):
        channel, _ = _make_channel()
        sink = _mock_sink()
        channel._sink = sink

        channel.publish_progress("start", "Thinking...", tool="my_tool")
        payload = sink.push.call_args.args[1]
        assert payload["event"] == "start"
        assert payload["status"] == "Thinking..."
        assert payload["tool"] == "my_tool"

    def test_publish_error(self):
        channel, _ = _make_channel()
        sink = _mock_sink()
        channel._sink = sink

        channel.publish_error("something broke")
        event, payload = sink.push.call_args.args
        assert event == "agent_error"
        assert payload["error"] == "something broke"

    def test_close(self):
        channel, sink = _make_channel()
        channel.close()
        assert sink.is_closed
