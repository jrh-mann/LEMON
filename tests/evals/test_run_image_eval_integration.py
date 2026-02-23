from __future__ import annotations

from pathlib import Path
import json
import os

from src.backend.utils.paths import lemon_data_dir

from evals import run_image_eval


class _MockAnalyzeWorkflowTool:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._counter = 0

    def execute(self, args):
        self._counter += 1
        uploads_dir = lemon_data_dir(self.repo_root) / "uploads"
        latest = max(uploads_dir.glob("*"), key=lambda p: p.stat().st_mtime)
        name = latest.name

        if "liver_pathology" in name:
            # Force structural failure for semantic score test path.
            analysis = {
                "variables": [{"id": "input_x_int", "name": "x", "type": "int", "source": "input"}],
                "outputs": [{"name": "Unknown"}],
                "tree": {},
                "doubts": ["could not resolve boxes"],
                "_raw_model_output": "{}",
            }
            flowchart = {"nodes": [], "edges": []}
        else:
            analysis = {
                "variables": [{"id": "input_age_int", "name": "age", "type": "int", "source": "input"}],
                "outputs": [{"name": "Adult"}, {"name": "Minor"}],
                "tree": {
                    "start": {
                        "id": "start",
                        "type": "start",
                        "label": "Start",
                        "children": [
                            {
                                "id": "out_adult",
                                "type": "output",
                                "label": "Adult",
                                "children": [],
                            }
                        ],
                    }
                },
                "doubts": [],
                "_raw_model_output": "{\"mock\": true}",
            }
            flowchart = {
                "nodes": [
                    {"id": "start", "type": "start", "label": "Start", "x": 0, "y": 0},
                    {"id": "out_adult", "type": "end", "label": "Adult", "x": 0, "y": 0},
                ],
                "edges": [{"from": "start", "to": "out_adult", "label": ""}],
            }

        return {
            "session_id": f"mock_{self._counter}",
            "analysis": analysis,
            "flowchart": flowchart,
        }


def test_run_evaluation_generates_expected_artifacts(monkeypatch):
    repo_root = Path("/Users/jeetthakwani/dev/LEMON")
    run_id = "pytest_eval_run"

    # Ensure clean output directory for deterministic assertions.
    results_dir = repo_root / "evals" / "results" / run_id
    if results_dir.exists():
        for path in sorted(results_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()

    monkeypatch.setattr(run_image_eval, "AnalyzeWorkflowTool", _MockAnalyzeWorkflowTool)

    summary = run_image_eval.run_evaluation(
        repo_root=repo_root,
        cases_arg="all",
        trials=1,
        run_id=run_id,
        emit_report=True,
        transport="direct",
    )

    assert summary["total_trials"] == 3
    assert len(summary["cases"]) == 3
    assert summary["eval_data_dir"].startswith("/tmp/lemon_eval_")

    summary_path = Path(summary["summary_path"])
    assert summary_path.exists()

    diagnostics = summary.get("diagnostics", {})
    failures_path = Path(diagnostics["failures_jsonl"])
    report_path = Path(diagnostics["report_md"])
    assert failures_path.exists()
    assert report_path.exists()

    lines = [line for line in failures_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert any("ambiguity unresolved" in row.get("buckets", []) for row in parsed)

    # Semantic failure path should be represented for liver mock output.
    liver_rows = [row for row in parsed if row.get("case_id") == "liver_pathology"]
    assert liver_rows, "Expected liver_pathology trial record"


def test_environment_restored_after_run(monkeypatch):
    repo_root = Path("/Users/jeetthakwani/dev/LEMON")
    run_id = "pytest_env_restore"

    original_data_dir = os.environ.get("LEMON_DATA_DIR")
    original_raw = os.environ.get("LEMON_INCLUDE_RAW_ANALYSIS")

    monkeypatch.setattr(run_image_eval, "AnalyzeWorkflowTool", _MockAnalyzeWorkflowTool)

    run_image_eval.run_evaluation(
        repo_root=repo_root,
        cases_arg="workflow_test",
        trials=1,
        run_id=run_id,
        emit_report=False,
        transport="direct",
    )

    assert os.environ.get("LEMON_DATA_DIR") == original_data_dir
    assert os.environ.get("LEMON_INCLUDE_RAW_ANALYSIS") == original_raw


def test_mcp_transport_uses_api_call(monkeypatch):
    repo_root = Path("/Users/jeetthakwani/dev/LEMON")
    run_id = "pytest_mcp_transport"

    def _fake_call_mcp_tool(name, args):
        assert name == "analyze_workflow"
        assert "image_data_url" in args
        return {
            "session_id": "mcp_mock_1",
            "analysis": {
                "variables": [{"id": "input_age_int", "name": "age", "type": "int", "source": "input"}],
                "outputs": [{"name": "Adult"}],
                "tree": {},
                "doubts": [],
                "_raw_model_output": "{\"mock\": true}",
            },
            "flowchart": {"nodes": [], "edges": []},
        }

    monkeypatch.setattr(run_image_eval, "call_mcp_tool", _fake_call_mcp_tool)

    summary = run_image_eval.run_evaluation(
        repo_root=repo_root,
        cases_arg="workflow_test",
        trials=1,
        run_id=run_id,
        emit_report=False,
        transport="mcp",
    )

    assert summary["transport"] == "mcp"
    assert summary["total_trials"] == 1
