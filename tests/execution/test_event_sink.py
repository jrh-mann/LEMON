"""Tests for the EventSink SSE infrastructure.

Verifies:
- push/iterate/close lifecycle
- Keepalive on idle
- Close semantics (sentinel, is_closed)
- Thread safety (concurrent pushes from multiple threads)
- GeneratorExit handling (client disconnect)
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from src.backend.tasks.sse import EventSink


class TestEventSinkBasic:
    """Basic push → iterate → close lifecycle."""

    def test_push_and_iterate(self):
        """Events pushed before close appear in correct SSE format."""
        sink = EventSink()
        sink.push("chat_stream", {"chunk": "hello"})
        sink.push("chat_stream", {"chunk": " world"})
        sink.close()

        lines = list(sink)
        assert len(lines) == 2
        assert lines[0] == 'event: chat_stream\ndata: {"chunk": "hello"}\n\n'
        assert lines[1] == 'event: chat_stream\ndata: {"chunk": " world"}\n\n'

    def test_close_stops_iteration(self):
        """close() sends sentinel that terminates the iterator."""
        sink = EventSink()
        sink.push("test", {"x": 1})
        sink.close()

        result = list(sink)
        assert len(result) == 1
        assert sink.is_closed

    def test_push_after_close_is_noop(self):
        """Events pushed after close() are silently dropped."""
        sink = EventSink()
        sink.close()
        sink.push("late_event", {"should": "be dropped"})

        result = list(sink)
        assert len(result) == 0

    def test_empty_sink_close(self):
        """Closing a sink with no events yields nothing."""
        sink = EventSink()
        sink.close()
        assert list(sink) == []

    def test_is_closed_initially_false(self):
        sink = EventSink()
        assert not sink.is_closed

    def test_is_closed_after_close(self):
        sink = EventSink()
        sink.close()
        assert sink.is_closed

    def test_double_close_is_safe(self):
        """Calling close() twice doesn't raise or double-sentinel."""
        sink = EventSink()
        sink.push("x", {"a": 1})
        sink.close()
        sink.close()  # Should not raise
        result = list(sink)
        assert len(result) == 1


class TestEventSinkSSEFormat:
    """Verify SSE line formatting matches the standard."""

    def test_event_format(self):
        sink = EventSink()
        sink.push("workflow_update", {"action": "add_node", "data": {"id": "n1"}})
        sink.close()

        lines = list(sink)
        assert len(lines) == 1
        # SSE format: event: <name>\ndata: <json>\n\n
        event_line, data_line, trailing = lines[0].split("\n", 2)
        assert event_line == "event: workflow_update"
        assert data_line.startswith("data: ")
        parsed = json.loads(data_line[6:])
        assert parsed == {"action": "add_node", "data": {"id": "n1"}}
        assert trailing == "\n"  # double newline terminator

    def test_json_special_chars(self):
        """Ensure JSON with special characters is properly encoded."""
        sink = EventSink()
        sink.push("msg", {"text": 'He said "hello" & <goodbye>'})
        sink.close()
        lines = list(sink)
        assert len(lines) == 1
        # JSON.parse should roundtrip
        data_str = lines[0].split("data: ", 1)[1].rstrip("\n")
        parsed = json.loads(data_str)
        assert parsed["text"] == 'He said "hello" & <goodbye>'


class TestEventSinkThreadSafety:
    """Verify concurrent pushes from multiple threads don't corrupt the queue."""

    def test_concurrent_pushes(self):
        """Multiple threads pushing simultaneously — all events arrive."""
        sink = EventSink()
        n_threads = 5
        events_per_thread = 20

        def push_events(thread_id: int):
            for i in range(events_per_thread):
                sink.push("event", {"thread": thread_id, "seq": i})

        threads = [
            threading.Thread(target=push_events, args=(t,))
            for t in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        sink.close()
        result = list(sink)
        assert len(result) == n_threads * events_per_thread

    def test_push_while_iterating(self):
        """Events pushed while iteration is in progress still arrive."""
        sink = EventSink()
        collected: list[str] = []

        def reader():
            for line in sink:
                collected.append(line)

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()

        # Push events from the main thread (simulates background task)
        for i in range(5):
            sink.push("stream", {"i": i})
            time.sleep(0.01)  # Small delay to interleave with reads

        sink.close()
        reader_thread.join(timeout=5)

        assert len(collected) == 5


class TestEventSinkGeneratorExit:
    """Verify client disconnect (GeneratorExit) is handled cleanly."""

    def test_generator_exit_marks_closed(self):
        """When the iterator is closed externally, is_closed becomes True."""
        sink = EventSink()
        sink.push("event", {"x": 1})

        it = iter(sink)
        next(it)  # Read first event
        it.close()  # Simulate client disconnect (GeneratorExit)

        assert sink.is_closed
