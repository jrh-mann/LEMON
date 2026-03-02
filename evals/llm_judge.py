"""LLM-based correctness scorer for workflow eval.

Instead of rigid F1 token matching on nodes/edges, an LLM judge assesses
whether the predicted workflow is logically correct by comparing it against
the ground truth logic.  Differently-shaped graphs that are logically
equivalent should score well; subworkflow expansions are a positive signal.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Dict, List, Mapping

from src.backend.llm.client import call_llm

logger = logging.getLogger(__name__)

# ── Scoring rubric sent to the judge ──────────────────────────────────

_JUDGE_PROMPT = """\
You are an expert workflow evaluator. Compare a **predicted workflow** against
**ground-truth logic** and score it on the rubric below.

## Rubric (score each dimension 0-10)

1. **decision_completeness** — Does the predicted workflow capture ALL decision
   points from the ground truth?  Missing a decision is worse than having an
   extra one. Reordering decisions is fine if logic is preserved.

2. **variable_coverage** — Are the right input variables defined? Stage-specific
   variables (e.g. A1c after metformin vs A1c after SGLT2i) should be separate.
   Extra variables for subworkflow expansions are acceptable.

3. **output_correctness** — Does the workflow reach the correct final outcomes?
   Each distinct clinical outcome in the ground truth should be reachable.
   Output labels should be specific, not generic placeholders.

4. **logical_consistency** — Do the conditions on decision nodes make sense?
   Are the comparators/thresholds correct?  Use your medical knowledge to
   judge whether the branching logic is clinically sound.

5. **subworkflow_quality** — If the predicted workflow expands action nodes
   into subworkflows, are those expansions medically reasonable and well
   structured?  Score 5 if no subworkflows exist (neutral).  Score higher
   if they add useful detail, lower if they are wrong.

## Output format

Return ONLY a JSON object:
```json
{{
  "decision_completeness": <0-10>,
  "variable_coverage": <0-10>,
  "output_correctness": <0-10>,
  "logical_consistency": <0-10>,
  "subworkflow_quality": <0-10>,
  "reasoning": "Brief explanation of major strengths and weaknesses.",
  "specific_errors": [
    "Concrete error 1: e.g. 'Decision X checks variable Y but should check Z'",
    "Concrete error 2: e.g. 'Output Foo is missing, model routes to Bar instead'"
  ]
}}
```

## Ground-truth logic (Python)

```python
{gt_source}
```

Expected outputs: {expected_outputs}

## Predicted workflow

### Variables (inputs)
{pred_variables}

### Outputs
{pred_outputs}

### Tree structure
{pred_tree}

### Subworkflows
{pred_subworkflows}

### Model's reasoning (extended thinking)
{model_reasoning}

Now score the predicted workflow against the ground truth. Pay attention to
the model's reasoning to understand WHY it made specific choices — flag cases
where its reasoning was wrong or where it misread the diagram.
Return ONLY JSON, no extra text.
"""


def _safe_json(obj: Any, max_chars: int = 12000) -> str:
    """Serialize an object to compact JSON, truncating if too large."""
    text = json.dumps(obj, indent=1, ensure_ascii=True, default=str)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (truncated)"
    return text


def llm_judge_score(
    analysis: Mapping[str, Any],
    flowchart: Mapping[str, Any],
    ground_truth_module: Any,
    case_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Run an LLM judge on a single trial and return dimension scores.

    Returns a dict with keys: decision_completeness, variable_coverage,
    output_correctness, logical_consistency, subworkflow_quality,
    composite (0-1), reasoning.
    """
    # Build the ground-truth context
    gt_source = inspect.getsource(ground_truth_module.determine_workflow_outcome)
    expected_outputs = case_config.get("expected_outputs", [])

    # Build the predicted context
    pred_variables = analysis.get("variables", [])
    pred_outputs = analysis.get("outputs", [])
    pred_tree = analysis.get("tree", {})
    pred_subworkflows = analysis.get("subworkflows", [])
    # Model's extended thinking — truncated to avoid blowing up the context
    model_reasoning = str(analysis.get("reasoning", ""))[:4000] or "(none)"

    prompt = _JUDGE_PROMPT.format(
        gt_source=gt_source,
        expected_outputs=expected_outputs,
        pred_variables=_safe_json(pred_variables),
        pred_outputs=_safe_json(pred_outputs),
        pred_tree=_safe_json(pred_tree),
        pred_subworkflows=_safe_json(pred_subworkflows) if pred_subworkflows else "(none)",
        model_reasoning=model_reasoning,
    )

    try:
        raw = call_llm(
            [{"role": "user", "content": prompt}],
            max_completion_tokens=2000,
            caller="eval_llm_judge",
            request_tag="judge_score",
        )
    except Exception as e:
        logger.error("LLM judge call failed: %s", e)
        return _fallback_result(str(e))

    # Parse the JSON response
    try:
        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        result = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("LLM judge returned invalid JSON: %s", e)
        return _fallback_result(f"JSON parse error: {e}", raw_output=raw)

    # Normalize and compute composite
    dimensions = [
        "decision_completeness",
        "variable_coverage",
        "output_correctness",
        "logical_consistency",
        "subworkflow_quality",
    ]
    scores: Dict[str, float] = {}
    for dim in dimensions:
        val = result.get(dim, 0)
        try:
            scores[dim] = max(0.0, min(10.0, float(val)))
        except (TypeError, ValueError):
            scores[dim] = 0.0

    # Composite: weighted average normalized to 0-1
    # Weight output_correctness and logical_consistency more heavily
    weights = {
        "decision_completeness": 0.20,
        "variable_coverage": 0.15,
        "output_correctness": 0.30,
        "logical_consistency": 0.25,
        "subworkflow_quality": 0.10,
    }
    composite = sum(scores[d] * weights[d] for d in dimensions) / 10.0

    return {
        **{d: scores[d] for d in dimensions},
        "composite": round(composite, 4),
        "composite_pct": round(composite * 100, 2),
        "reasoning": result.get("reasoning", ""),
        "specific_errors": result.get("specific_errors", []),
    }


def _fallback_result(error: str, raw_output: str = "") -> Dict[str, Any]:
    """Return a zero-score result when the judge fails."""
    return {
        "decision_completeness": 0.0,
        "variable_coverage": 0.0,
        "output_correctness": 0.0,
        "logical_consistency": 0.0,
        "subworkflow_quality": 0.0,
        "composite": 0.0,
        "composite_pct": 0.0,
        "reasoning": f"Judge failed: {error}",
        "raw_output": raw_output,
    }
