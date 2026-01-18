"""MCP client helper for calling backend tools via Streamable HTTP."""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any, Iterable

import anyio
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger("backend.mcp_client")

DEFAULT_MCP_URL = "http://127.0.0.1:8000/mcp"


def _get_mcp_url() -> str:
    return os.environ.get("LEMON_MCP_URL", DEFAULT_MCP_URL)


def call_mcp_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    url = _get_mcp_url()

    async def _call() -> dict[str, Any]:
        timeout_s = float(os.environ.get("LEMON_MCP_TIMEOUT", "120"))
        async with streamable_http_client(url) as (read_stream, write_stream, _):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=timeout_s),
            ) as session:
                logger.info("MCP initialize start")
                try:
                    with anyio.fail_after(timeout_s):
                        await session.initialize()
                except TimeoutError as exc:
                    raise RuntimeError(
                        f"MCP initialize timed out after {timeout_s:.1f}s"
                    ) from exc
                logger.info("MCP initialize complete")
                logger.info("MCP list_tools start")
                try:
                    with anyio.fail_after(timeout_s):
                        await session.list_tools()
                except TimeoutError as exc:
                    raise RuntimeError(
                        f"MCP list_tools timed out after {timeout_s:.1f}s"
                    ) from exc
                logger.info("MCP list_tools complete")
                logger.info("MCP call_tool start name=%s timeout_s=%.1f", name, timeout_s)
                try:
                    with anyio.fail_after(timeout_s):
                        result = await session.call_tool(name, args or {})
                except TimeoutError as exc:
                    raise RuntimeError(
                        f"MCP tool call timed out after {timeout_s:.1f}s: {name}"
                    ) from exc
                if result.isError:
                    error_text = ""
                    for block in result.content or []:
                        if getattr(block, "type", None) == "text":
                            error_text += getattr(block, "text", "")
                    error_text = error_text.strip()
                    raise RuntimeError(f"MCP tool error: {error_text or 'unknown error'}")
                if result.structuredContent is not None:
                    return result.structuredContent
                # Fallback: attempt to parse text content as JSON.
                text_parts: list[str] = []
                for block in result.content or []:
                    if getattr(block, "type", None) == "text":
                        text_parts.append(getattr(block, "text", ""))
                joined = "".join(text_parts).strip()
                if joined:
                    try:
                        return json.loads(joined)
                    except json.JSONDecodeError:
                        return {"text": joined}
                return {}

    logger.info("Calling MCP tool name=%s url=%s", name, url)
    try:
        return anyio.run(_call)
    except ExceptionGroup as exc:  # Python 3.11+
        details = _format_exception_group(exc)
        logger.error("MCP call failed with exception group: %s", details)
        raise RuntimeError(f"MCP tool call failed: {details}") from exc
    except Exception as exc:
        logger.exception("MCP call failed: %s", exc)
        raise


def _format_exception_group(exc: ExceptionGroup) -> str:
    parts: list[str] = []
    for item in _flatten_exceptions(exc):
        parts.append(f"{type(item).__name__}: {item}")
    return "; ".join(parts) if parts else str(exc)


def _flatten_exceptions(exc: ExceptionGroup) -> Iterable[BaseException]:
    for item in exc.exceptions:
        if isinstance(item, ExceptionGroup):
            yield from _flatten_exceptions(item)
        else:
            yield item
