"""Run multi-image evaluation for workflow image analysis quality."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
from statistics import mean
import sys
from typing import Any, Dict, List, Mapping, Sequence

# Allow running this file directly via absolute path.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.backend.tools.workflow_analysis.analyze import AnalyzeWorkflowTool
from src.backend.utils.image import image_to_data_url
from src.backend.utils.paths import lemon_data_dir
from src.backend.utils.uploads import save_uploaded_image
from src.backend.mcp_bridge.client import call_mcp_tool

from evals.diagnostics import emit_diagnostics
from evals.scoring import score_trial


def _repo_root() -> Path:
    return _REPO_ROOT


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_cases(repo_root: Path) -> List[Dict[str, Any]]:
    config_path = repo_root / "evals" / "config" / "image_eval_cases.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("image_eval_cases.json must contain a top-level JSON array")
    return [item for item in payload if isinstance(item, dict)]


def _select_cases(all_cases: Sequence[Mapping[str, Any]], requested: str) -> List[Dict[str, Any]]:
    if requested == "all":
        return [dict(case) for case in all_cases]

    requested_ids = [part.strip() for part in requested.split(",") if part.strip()]
    requested_set = set(requested_ids)

    selected = [dict(case) for case in all_cases if str(case.get("case_id")) in requested_set]
    found = {str(case.get("case_id")) for case in selected}
    missing = requested_set - found
    if missing:
        raise ValueError(f"Unknown case_id(s): {', '.join(sorted(missing))}")
    return selected


def _set_eval_environment(run_id: str) -> Dict[str, str | None]:
    previous = {
        "LEMON_DATA_DIR": os.environ.get("LEMON_DATA_DIR"),
        "LEMON_INCLUDE_RAW_ANALYSIS": os.environ.get("LEMON_INCLUDE_RAW_ANALYSIS"),
    }

    eval_data_dir = Path("/tmp") / f"lemon_eval_{run_id}"
    os.environ["LEMON_DATA_DIR"] = str(eval_data_dir)
    os.environ["LEMON_INCLUDE_RAW_ANALYSIS"] = "1"
    return previous


def _restore_environment(previous: Mapping[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _upload_image_for_trial(repo_root: Path, image_path: Path, case_id: str, trial_index: int) -> str:
    data_url = image_to_data_url(image_path)
    return save_uploaded_image(
        data_url,
        repo_root=repo_root,
        filename_prefix=f"eval_{case_id}_trial{trial_index}_",
    )


def _run_analysis_direct(
    *,
    tool: AnalyzeWorkflowTool,
    repo_root: Path,
    image_path: Path,
    case_id: str,
    trial_index: int,
) -> Dict[str, Any]:
    _upload_image_for_trial(repo_root, image_path, case_id, trial_index)
    return tool.execute({})


def _run_analysis_mcp(
    *,
    image_path: Path,
) -> Dict[str, Any]:
    data_url = image_to_data_url(image_path)
    result = call_mcp_tool(
        "analyze_workflow",
        {"image_data_url": data_url},
    )
    if not isinstance(result, dict):
        raise RuntimeError("MCP analyze_workflow returned a non-dict response.")
    return result


def _mean_metrics(score_entries: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    metric_names = [
        "node_f1",
        "edge_f1",
        "variable_f1",
        "output_f1",
        "semantic_score",
        "validity_score",
    ]
    aggregate: Dict[str, float] = {}
    for name in metric_names:
        values = [float(entry.get("metrics", {}).get(name, 0.0)) for entry in score_entries]
        aggregate[name] = mean(values) if values else 0.0
    aggregate["composite_raw"] = mean([float(entry.get("composite_raw", 0.0)) for entry in score_entries]) if score_entries else 0.0
    aggregate["composite_score"] = round(aggregate["composite_raw"] * 100.0, 2)
    aggregate["percentage_metrics"] = {
        key: round(value * 100.0, 2)
        for key, value in aggregate.items()
        if key in metric_names
    }
    return aggregate


def run_evaluation(
    *,
    repo_root: Path,
    cases_arg: str,
    trials: int,
    run_id: str,
    emit_report: bool,
    transport: str,
) -> Dict[str, Any]:
    all_cases = _load_cases(repo_root)
    selected_cases = _select_cases(all_cases, cases_arg)

    results_dir = repo_root / "evals" / "results" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    previous_env = _set_eval_environment(run_id)
    trial_records: List[Dict[str, Any]] = []
    case_summaries: List[Dict[str, Any]] = []

    try:
        tool = AnalyzeWorkflowTool(repo_root) if transport == "direct" else None

        for case in selected_cases:
            case_id = str(case.get("case_id"))
            image_rel = str(case.get("image_path"))
            image_path = repo_root / image_rel
            if not image_path.exists():
                raise FileNotFoundError(f"Image for case '{case_id}' not found: {image_path}")

            gt_module_name = str(case.get("ground_truth_module"))
            ground_truth_module = importlib.import_module(gt_module_name)

            case_trials: List[Dict[str, Any]] = []

            for trial_index in range(1, trials + 1):
                trial_dir = results_dir / case_id / f"trial_{trial_index:02d}"
                trial_dir.mkdir(parents=True, exist_ok=True)

                if transport == "direct":
                    assert tool is not None
                    tool_result = _run_analysis_direct(
                        tool=tool,
                        repo_root=repo_root,
                        image_path=image_path,
                        case_id=case_id,
                        trial_index=trial_index,
                    )
                elif transport == "mcp":
                    tool_result = _run_analysis_mcp(image_path=image_path)
                else:
                    raise ValueError(f"Unsupported transport: {transport}")
                session_id = str(tool_result.get("session_id", ""))
                analysis = dict(tool_result.get("analysis") or {})
                flowchart = dict(tool_result.get("flowchart") or {})

                raw_model_output = analysis.pop("_raw_model_output", "")

                score = score_trial(
                    case_config=case,
                    analysis=analysis,
                    flowchart=flowchart,
                    ground_truth_module=ground_truth_module,
                )

                raw_path = trial_dir / "raw_model_output.txt"
                analysis_path = trial_dir / "normalized_analysis.json"
                flowchart_path = trial_dir / "flowchart.json"
                score_path = trial_dir / "score.json"

                raw_path.write_text(str(raw_model_output), encoding="utf-8")
                analysis_path.write_text(json.dumps(analysis, indent=2, ensure_ascii=True), encoding="utf-8")
                flowchart_path.write_text(json.dumps(flowchart, indent=2, ensure_ascii=True), encoding="utf-8")
                score_path.write_text(json.dumps(score, indent=2, ensure_ascii=True), encoding="utf-8")

                trial_record = {
                    "case_id": case_id,
                    "image_path": image_rel,
                    "trial_index": trial_index,
                    "session_id": session_id,
                    "analysis": analysis,
                    "flowchart": flowchart,
                    "score": score,
                    "artifacts": {
                        "raw_model_output": str(raw_path),
                        "normalized_analysis": str(analysis_path),
                        "flowchart": str(flowchart_path),
                        "score": str(score_path),
                    },
                }
                trial_records.append(trial_record)
                case_trials.append(trial_record)

            case_summaries.append(
                {
                    "case_id": case_id,
                    "image_path": image_rel,
                    "ground_truth_module": gt_module_name,
                    "trial_count": len(case_trials),
                    "aggregate": _mean_metrics([trial["score"] for trial in case_trials]),
                    "trials": [
                        {
                            "trial_index": trial["trial_index"],
                            "session_id": trial["session_id"],
                            "composite_score": trial["score"].get("composite_score"),
                            "percentage_metrics": trial["score"].get("percentage_metrics", {}),
                            "artifacts": trial["artifacts"],
                        }
                        for trial in case_trials
                    ],
                }
            )

        overall_aggregate = _mean_metrics([trial["score"] for trial in trial_records])

        summary = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cases_selected": [case["case_id"] for case in selected_cases],
            "trials_per_case": trials,
            "total_trials": len(trial_records),
            "transport": transport,
            "eval_data_dir": str(lemon_data_dir(repo_root)),
            "history_db_path": str(lemon_data_dir(repo_root) / "history.sqlite"),
            "weights": {
                "node_f1": 0.25,
                "edge_f1": 0.25,
                "variable_f1": 0.15,
                "output_f1": 0.10,
                "semantic_score": 0.20,
                "validity_score": 0.05,
            },
            "aggregate": overall_aggregate,
            "cases": case_summaries,
        }

        if emit_report:
            diagnostics_paths = emit_diagnostics(
                run_id=run_id,
                trials=trial_records,
                history_db_path=Path(summary["history_db_path"]),
                results_dir=results_dir,
            )
            summary["diagnostics"] = diagnostics_paths

        summary_path = results_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
        summary["summary_path"] = str(summary_path)
        return summary
    finally:
        _restore_environment(previous_env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run image-to-workflow evaluation.")
    parser.add_argument("--cases", default="all", help="Case IDs (comma-separated) or 'all'.")
    parser.add_argument("--trials", type=int, default=3, help="Number of trials per case.")
    parser.add_argument("--run-id", default=None, help="Optional run id. Defaults to UTC timestamp.")
    parser.add_argument(
        "--emit-report",
        action="store_true",
        help="Emit failures.jsonl and report.md diagnostics files.",
    )
    parser.add_argument(
        "--transport",
        choices=["direct", "mcp"],
        default="direct",
        help="Execution transport for analyze calls: direct tool or MCP HTTP API.",
    )

    args = parser.parse_args()

    if args.trials <= 0:
        raise SystemExit("--trials must be >= 1")

    repo_root = _repo_root()
    run_id = args.run_id or _default_run_id()

    summary = run_evaluation(
        repo_root=repo_root,
        cases_arg=args.cases,
        trials=args.trials,
        run_id=run_id,
        emit_report=args.emit_report,
        transport=args.transport,
    )

    print(json.dumps({
        "run_id": summary["run_id"],
        "summary_path": summary["summary_path"],
        "aggregate": summary["aggregate"],
        "cases_selected": summary["cases_selected"],
        "total_trials": summary["total_trials"],
    }, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
