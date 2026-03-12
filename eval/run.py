"""CLI entry point for the evaluation framework.

Usage:
    python -m eval.run --model sonnet --runs 1
    python -m eval.run --model haiku,sonnet --samples diabetes --runs 2
    python -m eval.run --model sonnet --runs 3 --parallel 2
    python -m eval.run --list-samples
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

from .dataset import Sample, load_dataset
from .harness import EvalResult, run_sample
from .log import save_result, save_summary_csv
from .models import MODELS, resolve_model
from .scaffold import DEFAULT_SCAFFOLD, NO_THINKING_SCAFFOLD, REFINEMENT_SCAFFOLD, Scaffold

logger = logging.getLogger("eval.run")

_LOG_DIR = Path(__file__).resolve().parent / "logs"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_eval(
    dataset: List[Sample],
    models: List[str],
    scaffold: Scaffold,
    runs: int = 1,
    max_parallel: int = 1,
    log_dir: Path = _LOG_DIR,
) -> List[EvalResult]:
    """Run the full evaluation matrix: models × samples × runs.

    Args:
        dataset: Samples to evaluate.
        models: List of model short names (e.g. ["sonnet", "haiku"]).
        scaffold: Agent pipeline configuration.
        runs: Number of runs per (model, sample) pair.
        max_parallel: Max concurrent extractions.
        log_dir: Where to save result JSON files.

    Returns:
        List of all EvalResults.
    """
    # Build the work list: (sample, model, run_number).
    work: List[Tuple[Sample, str, str]] = []
    for model in models:
        resolve_model(model)  # validate early
        for sample in dataset:
            for run_num in range(1, runs + 1):
                run_id = f"{run_num}_{uuid.uuid4().hex[:6]}"
                work.append((sample, model, run_id))

    total = len(work)
    print(f"\n{'='*60}")
    print(f"LEMON Eval: {total} runs ({len(models)} models × {len(dataset)} samples × {runs} runs)")
    print(f"Models: {', '.join(models)}")
    print(f"Samples: {', '.join(s.name for s in dataset)}")
    print(f"Parallel: {max_parallel}")
    print(f"{'='*60}\n")

    results: List[EvalResult] = []

    def do_one(item: Tuple[Sample, str, str]) -> EvalResult:
        sample, model, run_id = item
        result = run_sample(sample, model, scaffold, run_id=run_id)
        # Score against golden solution.
        if result.workflow.get("nodes") and sample.golden_path.exists():
            try:
                import json
                from .scorer import score
                golden = json.loads(sample.golden_path.read_text())
                result.scores = score(golden, result.workflow)
            except Exception as exc:
                logger.error("Scoring failed for %s: %s", sample.name, exc)
        # Save immediately so partial results survive crashes.
        try:
            path = save_result(result, log_dir=log_dir)
            logger.info("Saved: %s", path.name)
        except Exception as exc:
            logger.error("Failed to save result: %s", exc)
        return result

    if max_parallel <= 1:
        # Sequential — simpler for debugging.
        for i, item in enumerate(work, 1):
            sample, model, run_id = item
            print(f"[{i}/{total}] {model} × {sample.name} (run {run_id})")
            result = do_one(item)
            results.append(result)
            _print_result(result)
    else:
        # Parallel via thread pool.
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            future_to_item = {pool.submit(do_one, item): item for item in work}
            for i, future in enumerate(as_completed(future_to_item), 1):
                item = future_to_item[future]
                sample, model, run_id = item
                try:
                    result = future.result()
                    results.append(result)
                    print(f"[{i}/{total}] {model} × {sample.name} (run {run_id})")
                    _print_result(result)
                except Exception as exc:
                    print(f"[{i}/{total}] {model} × {sample.name} FAILED: {exc}")

    # Summary.
    if results:
        csv_path = save_summary_csv(results, log_dir=log_dir)
        print(f"\n{'='*60}")
        print(f"Summary saved: {csv_path}")
        print(f"{'='*60}")
        _print_summary_table(results)

    return results


def _print_result(result: EvalResult) -> None:
    """Print one-line result summary."""
    status = "ERROR" if result.error else "OK"
    print(
        f"  {status} | nodes={len(result.workflow.get('nodes', []))} "
        f"edges={len(result.workflow.get('edges', []))} "
        f"vars={len(result.workflow.get('variables', []))} | "
        f"tools={len(result.tool_calls)} llm_calls={result.tokens.llm_calls} | "
        f"in={result.tokens.input_tokens:,} out={result.tokens.output_tokens:,} "
        f"time={result.wall_time_s:.1f}s"
    )
    if result.scores:
        s = result.scores
        print(
            f"  SCORE: {s.overall:.0%} "
            f"(vars={s.variables.score:.0%} nodes={s.nodes.score:.0%} "
            f"topo={s.topology.score:.0%} cond={s.conditions.score:.0%} "
            f"out={s.outputs.score:.0%})"
        )
    if result.error:
        print(f"  Error: {result.error}")


def _print_summary_table(results: List[EvalResult]) -> None:
    """Print a summary table of all results."""
    has_scores = any(r.scores for r in results)
    score_header = " Vars% Node% Topo% Cond%  Out%   AVG" if has_scores else ""
    print(f"\n{'Model':<10} {'Sample':<22} {'Run':<10} {'Nodes':>5} {'Edges':>5} "
          f"{'Vars':>4} {'Tools':>5} {'Cost':>8} {'Time':>6} {'St':<3}{score_header}")
    print("-" * (95 + (38 if has_scores else 0)))
    for r in results:
        status = "ERR" if r.error else "OK"
        line = (
            f"{r.model:<10} {r.sample_name:<22} {r.run_id:<10} "
            f"{len(r.workflow.get('nodes', [])):>5} "
            f"{len(r.workflow.get('edges', [])):>5} "
            f"{len(r.workflow.get('variables', [])):>4} "
            f"{len(r.tool_calls):>5} "
            f"${r.cost_usd:>7.4f} "
            f"{r.wall_time_s:>5.0f}s "
            f"{status:<3}"
        )
        if has_scores and r.scores:
            s = r.scores
            line += (
                f" {s.variables.score:>4.0%} {s.nodes.score:>4.0%} "
                f"{s.topology.score:>4.0%} {s.conditions.score:>4.0%} "
                f"{s.outputs.score:>4.0%} {s.overall:>5.0%}"
            )
        print(line)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LEMON evaluation framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python -m eval.run --model sonnet --runs 1
  python -m eval.run --model haiku,sonnet,opus --runs 3
  python -m eval.run --model sonnet --samples diabetes,liver --runs 2 --parallel 2
  python -m eval.run --list-samples
  python -m eval.run --list-models
""",
    )
    parser.add_argument(
        "--model", type=str, default="sonnet",
        help="Comma-separated model names (default: sonnet)",
    )
    parser.add_argument(
        "--samples", type=str, default=None,
        help="Comma-separated sample name filters (default: all)",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of runs per (model, sample) pair (default: 1)",
    )
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="Max parallel extractions (default: 1)",
    )
    parser.add_argument(
        "--no-thinking", action="store_true",
        help="Disable extended thinking (default: enabled at 50k, matching frontend)",
    )
    parser.add_argument(
        "--refine", action="store_true",
        help="Enable refinement pass after initial extraction (review + simplify)",
    )
    parser.add_argument(
        "--log-dir", type=str, default=str(_LOG_DIR),
        help=f"Log directory (default: {_LOG_DIR})",
    )
    parser.add_argument("--list-samples", action="store_true", help="List available samples")
    parser.add_argument("--list-models", action="store_true", help="List available models")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Configure logging.
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_samples:
        dataset = load_dataset()
        print("Available samples:")
        for s in dataset:
            print(f"  {s.name:<25} image={s.image_path.name}")
        return

    if args.list_models:
        print("Available models:")
        for name, cfg in MODELS.items():
            print(f"  {name:<10} id={cfg.model_id}  in=${cfg.input_cost_per_mtok}/Mtok  out=${cfg.output_cost_per_mtok}/Mtok")
        return

    # Parse model list.
    models = [m.strip() for m in args.model.split(",") if m.strip()]

    # Load dataset with optional filter.
    sample_filter = [s.strip() for s in args.samples.split(",")] if args.samples else None
    dataset = load_dataset(names=sample_filter)

    if not dataset:
        print("No samples found. Use --list-samples to see available samples.")
        sys.exit(1)

    # Select scaffold.
    if args.no_thinking:
        scaffold = NO_THINKING_SCAFFOLD
    elif args.refine:
        scaffold = REFINEMENT_SCAFFOLD
    else:
        scaffold = DEFAULT_SCAFFOLD

    # Run.
    run_eval(
        dataset=dataset,
        models=models,
        scaffold=scaffold,
        runs=args.runs,
        max_parallel=args.parallel,
        log_dir=Path(args.log_dir),
    )


if __name__ == "__main__":
    main()
