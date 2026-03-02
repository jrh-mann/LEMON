"""Mock-based tests for the validate_and_retry harness — no LLM calls."""

import logging

import pytest

from src.backend.validation.retry_harness import validate_and_retry
from src.backend.validation.workflow_validator import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_validator(data):
    """Always passes."""
    return (True, [])


def _fail_once_validator():
    """Fails on first call, passes on second."""
    call_count = {"n": 0}
    def _validate(data):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (False, [ValidationError(code="BAD", message="something wrong")])
        return (True, [])
    return _validate


def _always_fail_validator(data):
    """Always fails."""
    return (False, [ValidationError(code="STILL_BAD", message="still wrong")])


def _identity_format(errors):
    return "; ".join(e.message for e in errors)


def _noop_retry(error_text):
    return '{"fixed": true}'


def _identity_parse(raw):
    import json
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidateAndRetry:

    def test_valid_first_pass(self):
        """No retries when data is valid from the start."""
        data, errors = validate_and_retry(
            data={"ok": True},
            validate_fn=_ok_validator,
            format_errors_fn=_identity_format,
            retry_llm_fn=_noop_retry,
            parse_fn=_identity_parse,
        )
        assert data == {"ok": True}
        assert errors == []

    def test_invalid_then_valid(self):
        """One retry is enough when the LLM fixes the issue."""
        data, errors = validate_and_retry(
            data={"broken": True},
            validate_fn=_fail_once_validator(),
            format_errors_fn=_identity_format,
            retry_llm_fn=lambda _: '{"fixed": true}',
            parse_fn=_identity_parse,
        )
        assert data == {"fixed": True}
        assert errors == []

    def test_max_retries_exhausted(self):
        """Returns remaining errors after exhausting retries."""
        data, errors = validate_and_retry(
            data={"broken": True},
            validate_fn=_always_fail_validator,
            format_errors_fn=_identity_format,
            retry_llm_fn=lambda _: '{"still_broken": true}',
            parse_fn=_identity_parse,
            max_retries=2,
        )
        assert len(errors) > 0
        assert errors[0].code == "STILL_BAD"

    def test_parse_failure_during_retry(self):
        """Parse failure on a retry attempt doesn't crash — keeps trying."""
        call_count = {"n": 0}

        def _flaky_parse(raw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ValueError("bad JSON")
            import json
            return json.loads(raw)

        # Validator: fails twice (initial + after first successful parse),
        # then passes on third validation call.
        validate_calls = {"n": 0}
        def _validator(data):
            validate_calls["n"] += 1
            if validate_calls["n"] <= 2:
                return (False, [ValidationError(code="ERR", message="nope")])
            return (True, [])

        data, errors = validate_and_retry(
            data={"start": True},
            validate_fn=_validator,
            format_errors_fn=_identity_format,
            retry_llm_fn=lambda _: '{"attempt": true}',
            parse_fn=_flaky_parse,
            max_retries=3,
        )
        # First retry: parse fails → data stays as {"start": True}
        # Second retry: parse succeeds → data becomes {"attempt": true}
        # Third validation passes
        assert errors == []

    def test_llm_retry_exception_stops_loop(self):
        """If the LLM retry itself raises, loop breaks gracefully."""
        def _exploding_retry(error_text):
            raise RuntimeError("LLM unavailable")

        data, errors = validate_and_retry(
            data={"broken": True},
            validate_fn=_always_fail_validator,
            format_errors_fn=_identity_format,
            retry_llm_fn=_exploding_retry,
            parse_fn=_identity_parse,
            max_retries=3,
        )
        # Should return original data with errors, not crash
        assert len(errors) > 0
        assert data == {"broken": True}

    def test_custom_logger_no_crash(self):
        """Passing a custom logger works without errors."""
        log = logging.getLogger("test_retry_harness")
        data, errors = validate_and_retry(
            data={"ok": True},
            validate_fn=_ok_validator,
            format_errors_fn=_identity_format,
            retry_llm_fn=_noop_retry,
            parse_fn=_identity_parse,
            logger=log,
        )
        assert errors == []

    def test_zero_max_retries(self):
        """max_retries=0 means no retries — just validate and return."""
        data, errors = validate_and_retry(
            data={"broken": True},
            validate_fn=_always_fail_validator,
            format_errors_fn=_identity_format,
            retry_llm_fn=_noop_retry,
            parse_fn=_identity_parse,
            max_retries=0,
        )
        assert len(errors) > 0
        assert data == {"broken": True}
