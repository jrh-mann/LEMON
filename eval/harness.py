"""Harness: runs ONE sample through the full orchestrator pipeline.

Sets up a fresh orchestrator + temp DB, sends the image, captures
everything (workflow, transcript, tool calls, tokens, timing), and
returns an EvalResult.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .dataset import Sample
from .models import ModelConfig, resolve_model
from .scaffold import MockAskQuestion, Scaffold

logger = logging.getLogger("eval.harness")

# Repo root — two levels up from eval/
_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Accumulated token usage across all LLM calls in one run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    llm_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, entry: Dict[str, Any]) -> None:
        """Accumulate from a token usage entry dict."""
        usage = entry.get("usage", entry)  # handle both wrapped and flat
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.cache_creation_input_tokens += usage.get("cache_creation_input_tokens", 0)
        self.cache_read_input_tokens += usage.get("cache_read_input_tokens", 0)
        self.llm_calls += 1


@dataclass
class ToolCallRecord:
    """One tool invocation captured during the run."""

    tool_name: str
    args: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    success: bool
    timestamp: float  # time.monotonic() relative to run start


@dataclass
class EvalResult:
    """Complete output from running one sample."""

    sample_name: str
    model: str
    model_id: str
    run_id: str
    workflow: Dict[str, Any]  # {nodes, edges, variables, outputs}
    transcript: List[Dict[str, Any]]  # full conversation history
    tool_calls: List[ToolCallRecord]
    tokens: TokenUsage
    cost_usd: float
    wall_time_s: float
    llm_response: str  # final text response from the model
    error: Optional[str] = None
    scores: Optional[Any] = None  # ScoreResult from eval.scorer (optional to avoid circular import)

    def summary_dict(self) -> Dict[str, Any]:
        """Flat dict for CSV/summary output."""
        d = {
            "sample": self.sample_name,
            "model": self.model,
            "run_id": self.run_id,
            "num_nodes": len(self.workflow.get("nodes", [])),
            "num_edges": len(self.workflow.get("edges", [])),
            "num_variables": len(self.workflow.get("variables", [])),
            "num_tool_calls": len(self.tool_calls),
            "llm_calls": self.tokens.llm_calls,
            "input_tokens": self.tokens.input_tokens,
            "output_tokens": self.tokens.output_tokens,
            "total_tokens": self.tokens.total_tokens,
            "cost_usd": round(self.cost_usd, 4),
            "wall_time_s": round(self.wall_time_s, 1),
            "error": self.error,
        }
        if self.scores is not None:
            d.update(self.scores.summary_dict())
        return d


# ---------------------------------------------------------------------------
# Token tracking via monkey-patch
# ---------------------------------------------------------------------------

# Thread-local storage so parallel runs don't collide.
_thread_local = threading.local()


def _patched_record_token_usage(entry: Dict[str, Any]) -> None:
    """Drop-in replacement for record_token_usage that also accumulates."""
    # Accumulate into thread-local TokenUsage if one is active.
    tracker: Optional[TokenUsage] = getattr(_thread_local, "tracker", None)
    if tracker is not None:
        tracker.add(entry)

    # Still call the original so the global log file is updated.
    _original_record_token_usage(entry)


# Will be set on first use.
_original_record_token_usage = None
_patch_installed = False
_patch_lock = threading.Lock()


def _install_token_patch() -> None:
    """Install the monkey-patch on record_token_usage (idempotent)."""
    global _original_record_token_usage, _patch_installed
    with _patch_lock:
        if _patch_installed:
            return
        from src.backend.utils import tokens as tokens_mod
        _original_record_token_usage = tokens_mod.record_token_usage
        tokens_mod.record_token_usage = _patched_record_token_usage
        # Also patch the reference in client.py (already imported).
        from src.backend.llm import client as client_mod
        client_mod.record_token_usage = _patched_record_token_usage
        _patch_installed = True


# ---------------------------------------------------------------------------
# Core: run one sample
# ---------------------------------------------------------------------------


def run_sample(
    sample: Sample,
    model: str,
    scaffold: Scaffold,
    run_id: Optional[str] = None,
) -> EvalResult:
    """Run one evaluation sample through the full orchestrator pipeline.

    Args:
        sample: The image + golden pair to evaluate.
        model: Short model name (e.g. "sonnet"). Resolved via models.py.
        scaffold: Agent pipeline configuration.
        run_id: Optional run identifier. Generated if not provided.

    Returns:
        EvalResult with the extracted workflow, transcript, tokens, etc.
    """
    _install_token_patch()

    model_config = resolve_model(model)
    run_id = run_id or uuid.uuid4().hex[:8]

    # Track tokens for this run via thread-local.
    token_tracker = TokenUsage()
    _thread_local.tracker = token_tracker

    # Track tool calls via on_tool_event callback.
    tool_calls: List[ToolCallRecord] = []
    t0 = time.monotonic()

    def on_tool_event(
        event_type: str,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if event_type == "tool_complete":
            tool_calls.append(ToolCallRecord(
                tool_name=tool_name,
                args=args,
                result=result,
                success=bool(result and result.get("success", False)),
                timestamp=time.monotonic() - t0,
            ))

    # Set model for this run.
    old_model = os.environ.get("ANTHROPIC_MODEL")
    os.environ["ANTHROPIC_MODEL"] = model_config.model_id

    error: Optional[str] = None
    llm_response = ""
    workflow: Dict[str, Any] = {"nodes": [], "edges": [], "variables": [], "outputs": []}
    transcript: List[Dict[str, Any]] = []

    try:
        with tempfile.TemporaryDirectory(prefix="lemon_eval_") as tmp_dir:
            # Late imports to avoid loading backend at module level.
            from src.backend.agents.orchestrator_factory import build_orchestrator
            from src.backend.storage.workflows import WorkflowStore

            # Fresh DB + workflow record.
            db_path = Path(tmp_dir) / "eval.sqlite"
            store = WorkflowStore(db_path)
            workflow_id = f"eval_{run_id}"
            user_id = "eval_user"
            store.create_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                name=f"Eval: {sample.name}",
                description=f"Eval run {run_id}",
            )

            # Build orchestrator with real tools.
            orchestrator = build_orchestrator(_REPO_ROOT)

            # Replace ask_question with mock.
            orchestrator.tools._tools["ask_question"] = MockAskQuestion()

            # Wire session context (same as ws_chat does for real requests).
            orchestrator.workflow_store = store
            orchestrator.user_id = user_id
            orchestrator.current_workflow_id = workflow_id
            orchestrator.current_workflow_name = f"Eval: {sample.name}"
            orchestrator.repo_root = _REPO_ROOT

            # Prepare image file info.
            has_files = [{
                "path": str(sample.image_path),
                "name": sample.image_path.name,
                "file_type": "image",
            }]

            # Build scaffold overrides.
            respond_kwargs: Dict[str, Any] = {
                "user_message": scaffold.user_message,
                "has_files": has_files,
                "allow_tools": True,
                "on_tool_event": on_tool_event,
            }
            if scaffold.thinking_budget is not None:
                respond_kwargs["thinking_budget"] = scaffold.thinking_budget

            # Run the full extraction.
            logger.info(
                "Starting eval: sample=%s model=%s run=%s",
                sample.name, model, run_id,
            )
            llm_response = orchestrator.respond(**respond_kwargs)

            # Detect orchestrator-swallowed errors (returns "LLM error: ..."
            # instead of raising).
            if llm_response.startswith("LLM error:"):
                error = llm_response

            # Capture results.
            workflow = {
                "nodes": orchestrator.workflow.get("nodes", []),
                "edges": orchestrator.workflow.get("edges", []),
                "variables": orchestrator.workflow.get("variables", []),
                "outputs": orchestrator.workflow.get("outputs", []),
            }
            transcript = list(orchestrator.conversation.history)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.error("Eval run failed: %s", error, exc_info=True)
    finally:
        # Restore model env var.
        if old_model is not None:
            os.environ["ANTHROPIC_MODEL"] = old_model
        elif "ANTHROPIC_MODEL" in os.environ:
            del os.environ["ANTHROPIC_MODEL"]
        # Clear thread-local tracker.
        _thread_local.tracker = None

    wall_time = time.monotonic() - t0
    cost = model_config.cost(token_tracker.input_tokens, token_tracker.output_tokens)

    result = EvalResult(
        sample_name=sample.name,
        model=model,
        model_id=model_config.model_id,
        run_id=run_id,
        workflow=workflow,
        transcript=transcript,
        tool_calls=tool_calls,
        tokens=token_tracker,
        cost_usd=cost,
        wall_time_s=wall_time,
        llm_response=llm_response,
        error=error,
    )

    logger.info(
        "Eval complete: sample=%s model=%s run=%s nodes=%d cost=$%.4f time=%.1fs%s",
        sample.name, model, run_id,
        len(workflow.get("nodes", [])),
        cost, wall_time,
        f" ERROR={error}" if error else "",
    )

    return result
