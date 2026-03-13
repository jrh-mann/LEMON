"""Tests for EventSink reference counting.

The parent ChatTask and background builder threads share the same EventSink.
Without reference counting, the parent's close() kills the SSE stream while
builders are still emitting events — causing subworkflow chat output to vanish.

Reference counting ensures the SSE stream stays open until ALL producers
(parent + builders) have released.
"""

import threading
import time

import pytest

from src.backend.api.sse import EventSink


class TestEventSinkRefCount:
    def test_single_owner_release_closes(self):
        """release() closes the sink when the single owner releases."""
        sink = EventSink()
        assert not sink.is_closed
        sink.release()
        assert sink.is_closed

    def test_acquired_sink_survives_first_release(self):
        """Sink stays open after first release if another producer acquired it."""
        sink = EventSink()
        sink.acquire()  # second producer
        sink.release()  # first producer done
        assert not sink.is_closed, "Sink should stay open — builder still has a reference"

    def test_second_release_closes(self):
        """Sink closes when the last producer releases."""
        sink = EventSink()
        sink.acquire()
        sink.release()  # parent done
        assert not sink.is_closed
        sink.release()  # builder done
        assert sink.is_closed

    def test_push_after_parent_release_still_works(self):
        """Events pushed after parent release are queued (sink still open)."""
        sink = EventSink()
        sink.acquire()  # builder takes a reference
        sink.release()  # parent releases — sink stays open

        # Builder pushes an event — should succeed because sink is still open
        sink.push("chat_response", {"workflow_id": "wf1"})
        assert not sink.is_closed

        # Consume the event
        events = list(_drain_queue(sink))
        assert len(events) == 1
        assert events[0][0] == "chat_response"

    def test_push_after_full_release_noop(self):
        """Events pushed after all producers release are silently dropped."""
        sink = EventSink()
        sink.acquire()
        sink.release()
        sink.release()
        assert sink.is_closed

        # This should silently no-op
        sink.push("chat_response", {"workflow_id": "wf1"})
        # Queue should only have the None sentinel from close()
        events = list(_drain_queue(sink))
        assert len(events) == 0  # sentinel is consumed by _drain_queue

    def test_multiple_acquires(self):
        """Multiple builders can each acquire; sink closes when all release."""
        sink = EventSink()
        sink.acquire()  # builder 1
        sink.acquire()  # builder 2

        sink.release()  # parent done
        assert not sink.is_closed
        sink.release()  # builder 1 done
        assert not sink.is_closed
        sink.release()  # builder 2 done
        assert sink.is_closed

    def test_close_force_overrides_refcount(self):
        """close() force-closes regardless of ref count (for swap_sink)."""
        sink = EventSink()
        sink.acquire()  # builder has a reference
        sink.close()  # force close (e.g. from swap_sink)
        assert sink.is_closed

    def test_thread_safety(self):
        """acquire/release from multiple threads doesn't corrupt state."""
        sink = EventSink()
        n_producers = 10
        for _ in range(n_producers):
            sink.acquire()

        errors = []

        def release_after_delay(delay: float):
            time.sleep(delay)
            try:
                sink.release()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(n_producers):
            t = threading.Thread(target=release_after_delay, args=(0.001 * i,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        # Parent releases last
        sink.release()

        assert not errors, f"Errors during threaded release: {errors}"
        assert sink.is_closed

    def test_builder_events_flow_after_parent_done(self):
        """End-to-end: parent releases, builder continues emitting, then releases."""
        sink = EventSink()
        sink.acquire()  # builder reference

        # Parent emits its response and releases
        sink.push("chat_response", {"workflow_id": "parent_wf"})
        sink.release()  # parent done — sink stays open

        # Builder continues to emit events
        sink.push("chat_stream", {"chunk": "Building node...", "workflow_id": "sub_wf"})
        sink.push("chat_response", {"workflow_id": "sub_wf", "response": "Done"})

        # Builder releases — sink closes
        sink.release()
        assert sink.is_closed

        # Verify all events were queued
        events = list(_drain_queue(sink))
        assert len(events) == 3
        assert events[0][0] == "chat_response"  # parent
        assert events[1][0] == "chat_stream"    # builder
        assert events[2][0] == "chat_response"  # builder


def _drain_queue(sink: EventSink) -> list:
    """Helper: drain all non-sentinel items from the sink's queue."""
    import queue as q
    items = []
    while True:
        try:
            item = sink._queue.get_nowait()
            if item is None:
                break  # sentinel
            items.append(item)
        except q.Empty:
            break
    return items
