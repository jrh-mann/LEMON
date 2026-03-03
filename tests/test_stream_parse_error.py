"""Tests for _is_stream_parse_error() and the friendly error message logic
in socket_chat.py.

The socket layer's catch-all exception handler classifies errors so that
raw JSON/SSE parser internals (from the Anthropic SDK) are replaced with
a user-friendly retry message. These tests verify that classification.
"""

import pytest

from src.backend.api.socket_chat import _is_stream_parse_error


# ---------------------------------------------------------------------------
# _is_stream_parse_error — positive cases (should return True)
# ---------------------------------------------------------------------------

class TestIsStreamParseErrorPositive:
    """Errors that look like JSON/SSE stream parse failures."""

    def test_serde_json_expected_colon(self):
        """Rust serde_json via pydantic-core: 'expected : at line 1 column 91'."""
        assert _is_stream_parse_error("expected : at line 1 column 91") is True

    def test_serde_json_expected_value(self):
        """Rust serde_json: 'expected value at line 1 column 1'."""
        assert _is_stream_parse_error("expected value at line 1 column 1") is True

    def test_python_json_expecting_comma(self):
        """Python json.JSONDecodeError: 'Expecting ',' delimiter: ...'."""
        assert _is_stream_parse_error(
            "Expecting ',' delimiter: line 1 column 95 (char 94)"
        ) is True

    def test_python_json_expecting_value(self):
        """Python json.JSONDecodeError: 'Expecting value: ...'."""
        assert _is_stream_parse_error(
            "Expecting value: line 1 column 1 (char 0)"
        ) is True

    def test_python_json_expecting_property_name(self):
        """Python json.JSONDecodeError: 'Expecting property name enclosed in double quotes'."""
        assert _is_stream_parse_error(
            "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
        ) is True

    def test_unterminated_string(self):
        """Python json: 'Unterminated string starting at: ...'."""
        assert _is_stream_parse_error(
            "Unterminated string starting at: line 1 column 10 (char 9)"
        ) is True

    def test_invalid_escape(self):
        """Python json: 'Invalid \\escape: ...'."""
        assert _is_stream_parse_error(
            "Invalid \\escape: line 1 column 5 (char 4)"
        ) is True


# ---------------------------------------------------------------------------
# _is_stream_parse_error — negative cases (should return False)
# ---------------------------------------------------------------------------

class TestIsStreamParseErrorNegative:
    """Errors that are NOT stream parse failures — should pass through raw."""

    def test_connection_refused(self):
        assert _is_stream_parse_error("Connection refused") is False

    def test_api_key_error(self):
        assert _is_stream_parse_error("Invalid API key provided") is False

    def test_rate_limit(self):
        assert _is_stream_parse_error("Rate limit exceeded") is False

    def test_timeout(self):
        assert _is_stream_parse_error("Request timed out") is False

    def test_empty_string(self):
        assert _is_stream_parse_error("") is False

    def test_generic_python_error(self):
        assert _is_stream_parse_error("TypeError: 'NoneType' object is not iterable") is False

    def test_expected_in_middle_of_string(self):
        """'expected' must be at the START of the string to match."""
        assert _is_stream_parse_error("Something expected went wrong") is False

    def test_expecting_in_middle_of_string(self):
        """'Expecting' must be at the START of the string to match."""
        assert _is_stream_parse_error("I was Expecting an error") is False
