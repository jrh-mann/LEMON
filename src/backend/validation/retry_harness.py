"""Generic validate-and-retry harness.

Feeds structural validation errors back to an LLM so it can self-correct.
Callers supply their own validate / format / retry / parse functions —
the harness only owns the loop logic.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .workflow_validator import ValidationError


def validate_and_retry(
    *,
    data: Dict[str, Any],
    validate_fn: Callable[[Dict[str, Any]], Tuple[bool, List[ValidationError]]],
    format_errors_fn: Callable[[List[ValidationError]], str],
    retry_llm_fn: Callable[[str], str],
    parse_fn: Callable[[str], Dict[str, Any]],
    max_retries: int = 2,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Dict[str, Any], List[ValidationError]]:
    """Validate *data* and, if invalid, retry via LLM up to *max_retries* times.

    Parameters
    ----------
    data:
        The parsed dict to validate.
    validate_fn:
        ``(data) -> (is_valid, errors)``
    format_errors_fn:
        ``(errors) -> human-readable string`` fed to the LLM.
    retry_llm_fn:
        ``(error_text) -> raw_llm_string``.  Called with the formatted
        error text; must return the LLM's corrected raw output.
    parse_fn:
        ``(raw_string) -> dict``.  Parses the LLM's raw output back
        into a dict.  May raise on parse failure.
    max_retries:
        Maximum number of LLM retry attempts (default 2).
    logger:
        Optional logger for debug output.

    Returns
    -------
    (data, remaining_errors):
        If validation passes (possibly after retries), ``remaining_errors``
        is empty.  If retries are exhausted, the caller gets the last
        data and the remaining errors to decide what to do.
    """
    log = logger or logging.getLogger(__name__)

    is_valid, errors = validate_fn(data)
    if is_valid:
        return (data, [])

    for attempt in range(1, max_retries + 1):
        error_text = format_errors_fn(errors)
        log.info(
            "Structural validation failed (%d error(s)), retry %d/%d",
            len(errors),
            attempt,
            max_retries,
        )

        # Ask the LLM to fix the issues
        try:
            raw = retry_llm_fn(error_text)
        except Exception:
            log.warning("LLM retry call failed on attempt %d", attempt, exc_info=True)
            break

        # Parse the corrected output
        try:
            data = parse_fn(raw)
        except Exception:
            log.warning(
                "Parse failed on retry attempt %d", attempt, exc_info=True
            )
            # Keep previous data and errors — try again if retries remain
            continue

        # Re-validate
        is_valid, errors = validate_fn(data)
        if is_valid:
            log.info("Structural validation passed after retry %d", attempt)
            return (data, [])

    log.warning(
        "Structural validation still has %d error(s) after %d retries",
        len(errors),
        max_retries,
    )
    return (data, errors)
