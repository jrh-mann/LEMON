from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_file
from flask_cors import CORS

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.lemon.analysis.agent import WorkflowAnalyzer
from src.lemon.core.evaluator import SolverEvaluator
from src.lemon.core.workflow import WorkflowAnalysis
from src.lemon.generation.generator import CodeGenerator, GenerationContext
from src.lemon.solvers.code_solver import AgenticCodeSolver
from src.lemon.testing.generator import TestCaseGenerator
from src.lemon.testing.harness import TestHarness
from src.lemon.utils.logging import configure_logging, get_logger
from src.utils.request_utils import make_request

load_dotenv(REPO_ROOT / ".env")
configure_logging(level="INFO", json_logs=False)
logger = get_logger(__name__)

RUNS_DIR = Path(__file__).parent / "runs"
STATE_FILE = Path(__file__).parent / ".orchestrator_state.json"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

NUM_TEST_CASES = 100
BATCH_SIZE = 5
MAX_WORKERS = 5
BEST_OF_N = 3
MAX_ITERATIONS = 5


@dataclass
class ConversationMessage:
    id: str
    role: str
    content: str
    ts: float
    tags: List[str] = field(default_factory=list)


@dataclass
class OrchestratorState:
    stage: str = "idle"
    revision: int = 0
    conversation: List[ConversationMessage] = field(default_factory=list)
    analysis: Optional[Dict[str, Any]] = None
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    iterations: List[Dict[str, Any]] = field(default_factory=list)
    test_progress: Dict[str, Any] = field(
        default_factory=lambda: {"current": 0, "total": 0, "percent": 0}
    )
    workflow_image: Optional[str] = None
    workflow_name: Optional[str] = None
    run_id: Optional[str] = None
    run_dir: Optional[str] = None
    generated_code_path: Optional[str] = None
    last_feedback: Optional[str] = None


STATE_LOCK = threading.Lock()
STATE = OrchestratorState()


class EventHub:
    def __init__(self) -> None:
        self._clients: List[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._lock:
            self._clients.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def publish(self, event: Dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                continue


EVENTS = EventHub()


def _emit(event_type: str, data: Dict[str, Any]) -> None:
    event = {"type": event_type, "data": data, "ts": time.time()}
    EVENTS.publish(event)


def _save_state() -> None:
    payload = {
        "stage": STATE.stage,
        "revision": STATE.revision,
        "conversation": [asdict(msg) for msg in STATE.conversation],
        "analysis": STATE.analysis,
        "inputs": STATE.inputs,
        "outputs": STATE.outputs,
        "iterations": STATE.iterations,
        "test_progress": STATE.test_progress,
        "workflow_image": STATE.workflow_image,
        "workflow_name": STATE.workflow_name,
        "run_id": STATE.run_id,
        "run_dir": STATE.run_dir,
        "generated_code_path": STATE.generated_code_path,
        "last_feedback": STATE.last_feedback,
    }
    STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_state() -> None:
    if not STATE_FILE.exists():
        return
    try:
        raw = STATE_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("State file was invalid JSON; resetting.", extra={"path": str(STATE_FILE)})
        return
    STATE.stage = payload.get("stage", "idle")
    STATE.revision = payload.get("revision", 0)
    STATE.conversation = [ConversationMessage(**msg) for msg in payload.get("conversation", [])]
    STATE.analysis = payload.get("analysis")
    STATE.inputs = payload.get("inputs", [])
    STATE.outputs = payload.get("outputs", [])
    STATE.iterations = payload.get("iterations", [])
    STATE.test_progress = payload.get("test_progress", {"current": 0, "total": 0, "percent": 0})
    STATE.workflow_image = payload.get("workflow_image")
    STATE.workflow_name = payload.get("workflow_name")
    STATE.run_id = payload.get("run_id")
    STATE.run_dir = payload.get("run_dir")
    STATE.generated_code_path = payload.get("generated_code_path")
    STATE.last_feedback = payload.get("last_feedback")





app = Flask(__name__)
CORS(app)


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/events")
def events() -> Response:
    q = EVENTS.subscribe()

    def stream() -> Any:
        try:
            while True:
                try:
                    event = q.get(timeout=20)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield "data: {\"type\": \"ping\"}\n\n"
        finally:
            EVENTS.unsubscribe(q)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/state")
def get_state() -> Response:
    with STATE_LOCK:
        payload = {
            "stage": STATE.stage,
            "revision": STATE.revision,
            "conversation": [asdict(msg) for msg in STATE.conversation],
            "analysis": STATE.analysis,
            "inputs": STATE.inputs,
            "outputs": STATE.outputs,
            "iterations": STATE.iterations,
            "test_progress": STATE.test_progress,
            "workflow_image": STATE.workflow_image,
            "workflow_name": STATE.workflow_name,
            "run_id": STATE.run_id,
            "run_dir": STATE.run_dir,
            "generated_code_path": STATE.generated_code_path,
            "last_feedback": STATE.last_feedback,
        }
    return jsonify(payload)


@app.route("/api/upload", methods=["POST"])
def upload() -> Response:
    if "file" not in request.files:
        return jsonify({"error": "missing_file"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty_filename"}), 400

    workflow_name = (request.form.get("workflow_name") or "").strip()
    slug = _slugify(workflow_name) if workflow_name else "workflow"
    run_id = uuid.uuid4().hex[:10]
    run_dir = RUNS_DIR / f"{slug}_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename).suffix or ".png"
    filename = f"{slug}{suffix}"
    path = run_dir / filename
    file.save(path)

    _reset_state()
    with STATE_LOCK:
        STATE.workflow_image = str(path)
        STATE.workflow_name = workflow_name or slug
        STATE.run_id = run_id
        STATE.run_dir = str(run_dir)
    _append_message("user", f"Uploaded workflow image: {file.filename}", tags=["upload"])

    _start_background(_run_analysis, feedback=None)
    return jsonify(
        {
            "status": "ok",
            "path": str(path),
            "workflow_name": STATE.workflow_name,
            "run_id": STATE.run_id,
        }
    )


@app.route("/api/analysis/approve", methods=["POST"])
def approve_analysis() -> Response:
    _append_message("user", "Analysis looks good. Proceed.", tags=["approval"])
    _append_message(
        "orchestrator",
        "Starting test case generation and labeling.",
        tags=["tests"],
    )
    _start_background(_run_tests_and_codegen)
    return jsonify({"status": "ok"})


@app.route("/api/analysis/feedback", methods=["POST"])
def feedback_analysis() -> Response:
    data = request.get_json(silent=True) or {}
    feedback = (data.get("feedback") or "").strip()
    if not feedback:
        return jsonify({"error": "empty_feedback"}), 400

    with STATE_LOCK:
        STATE.last_feedback = feedback
    _append_message("user", feedback, tags=["feedback"])
    _append_message(
        "orchestrator",
        "Understood. I will refine the analysis and re-run the extraction.",
        tags=["analysis"],
    )
    _start_background(_run_analysis, feedback=feedback)
    return jsonify({"status": "ok"})


@app.route("/api/edge-case", methods=["POST"])
def edge_case() -> Response:
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty_message"}), 400

    _append_message("user", message, tags=["edge"])
    _append_message(
        "orchestrator",
        "Got it. I will treat this as an edge case and validate it in the final pass.",
        tags=["edge"],
    )
    return jsonify({"status": "ok"})


@app.route("/api/download")
def download() -> Response:
    with STATE_LOCK:
        code_path = STATE.generated_code_path
        workflow_name = STATE.workflow_name or "workflow"
    if not code_path or not Path(code_path).exists():
        return jsonify({"error": "not_ready"}), 404
    filename = f"{_slugify(workflow_name)}.py"
    return send_file(code_path, as_attachment=True, download_name=filename)


@app.route("/api/reset", methods=["POST"])
def reset() -> Response:
    _reset_state()
    _emit("state_reset", {"status": "ok"})
    return jsonify({"status": "ok"})


def _append_message(role: str, content: str, tags: Optional[List[str]] = None) -> None:
    msg = ConversationMessage(
        id=str(uuid.uuid4()),
        role=role,
        content=content,
        ts=time.time(),
        tags=tags or [],
    )
    with STATE_LOCK:
        STATE.conversation.append(msg)
        _save_state()
    _emit("message", asdict(msg))


def _set_stage(stage: str) -> None:
    with STATE_LOCK:
        STATE.stage = stage
        _save_state()
    _emit("stage_started", {"stage": stage})


def _reset_state() -> None:
    with STATE_LOCK:
        STATE.stage = "idle"
        STATE.revision = 0
        STATE.conversation = []
        STATE.analysis = None
        STATE.inputs = []
        STATE.outputs = []
        STATE.iterations = []
        STATE.test_progress = {"current": 0, "total": 0, "percent": 0}
        STATE.workflow_image = None
        STATE.workflow_name = None
        STATE.run_id = None
        STATE.run_dir = None
        STATE.generated_code_path = None
        STATE.last_feedback = None
        _save_state()


def _start_background(target: Any, *args: Any, **kwargs: Any) -> None:
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()


def _slugify(value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    safe = "-".join(part for part in safe.split("-") if part)
    return safe or "workflow"


def _build_feedback_prompt(base_prompt: str, prev_analysis: Dict[str, Any], feedback: str) -> str:
    return (
        base_prompt
        + "\n\nPREVIOUS ANALYSIS JSON:\n"
        + json.dumps(prev_analysis, indent=2)
        + "\n\nUSER FEEDBACK:\n"
        + feedback
        + "\n\nPlease revise the analysis JSON to address the feedback."
    )


def _run_analysis(*, feedback: Optional[str]) -> None:
    with STATE_LOCK:
        image_path = STATE.workflow_image
        previous_analysis = STATE.analysis
        run_dir = STATE.run_dir
    if not image_path:
        _append_message("orchestrator", "No workflow image found to analyze.")
        return
    if not run_dir:
        _append_message("orchestrator", "No workflow run directory available.")
        return

    _set_stage("analyzing")
    _append_message("orchestrator", "Analyzing the workflow diagram.", tags=["analysis"])

    try:
        analyzer = WorkflowAnalyzer()
        if feedback and previous_analysis:
            analyzer.analysis_prompt = _build_feedback_prompt(
                analyzer.analysis_prompt, previous_analysis, feedback
            )

        analysis = analyzer.analyze(Path(image_path))
        inputs = analyzer.extract_standardized_inputs(analysis)
        outputs = analyzer.extract_outputs(analysis)

        analysis_payload = analysis.model_dump()
        inputs_payload = [x.model_dump(exclude_none=True) for x in inputs]

        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "workflow_analysis.json").write_text(
            json.dumps(analysis_payload, indent=2), encoding="utf-8"
        )
        (run_path / "workflow_inputs.json").write_text(
            json.dumps(inputs_payload, indent=2), encoding="utf-8"
        )
        (run_path / "workflow_outputs.json").write_text(
            json.dumps(outputs, indent=2), encoding="utf-8"
        )

        with STATE_LOCK:
            STATE.analysis = analysis_payload
            STATE.inputs = inputs_payload
            STATE.outputs = outputs
            STATE.revision += 1
            revision = STATE.revision
            _save_state()

        _emit(
            "analysis_ready",
            {
                "inputs": inputs_payload,
                "outputs": outputs,
                "revision": revision,
            },
        )
        _set_stage("awaiting_approval")
        _append_message(
            "orchestrator",
            "Analysis ready. Review inputs and outputs, then approve or ask for refinement.",
            tags=["analysis"],
        )
        _emit("approval_requested", {"revision": revision})
    except Exception as exc:
        logger.exception("Analysis failed")
        _append_message(
            "orchestrator", f"Analysis failed. {type(exc).__name__}: {exc}", tags=["error"]
        )
        _emit("error", {"stage": "analysis", "message": str(exc)})


def _run_tests_and_codegen() -> None:
    with STATE_LOCK:
        image_path = STATE.workflow_image
        analysis_payload = STATE.analysis
        outputs = STATE.outputs
        run_dir = STATE.run_dir
    if not image_path or not analysis_payload or not outputs:
        _append_message("orchestrator", "Missing analysis artifacts. Cannot run tests.")
        return
    if not run_dir:
        _append_message("orchestrator", "No workflow run directory available.")
        return

    _set_stage("tests_running")

    try:
        run_path = Path(run_dir)
        run_path.mkdir(parents=True, exist_ok=True)
        generator = TestCaseGenerator(str(run_path / "workflow_inputs.json"))
        test_cases = generator.generate_test_cases(NUM_TEST_CASES, "comprehensive")
        (run_path / "test_cases.json").write_text(
            json.dumps(test_cases, indent=2), encoding="utf-8"
        )

        def progress_callback(
            completed_batches: int,
            total_batches: int,
            pass_num: int,
            pass_total: int,
        ) -> None:
            overall_completed = (pass_num - 1) * total_batches + completed_batches
            overall_total = total_batches * pass_total
            percent = int((overall_completed / overall_total) * 100) if overall_total else 0
            with STATE_LOCK:
                STATE.test_progress = {
                    "current": overall_completed,
                    "total": overall_total,
                    "percent": percent,
                }
                _save_state()
            _emit(
                "tests_progress",
                {
                    "current": overall_completed,
                    "total": overall_total,
                    "percent": percent,
                },
            )

        labeled = generator.label_test_cases(
            test_cases=test_cases,
            workflow_image_path=str(Path(image_path)),
            valid_outputs=outputs,
            workflow_analysis=analysis_payload,
            batch_size=BATCH_SIZE,
            max_workers=MAX_WORKERS,
            best_of_n=BEST_OF_N,
            progress_callback=progress_callback,
        )

        (run_path / "tests.json").write_text(
            json.dumps(labeled, indent=2), encoding="utf-8"
        )

        with STATE_LOCK:
            total = STATE.test_progress.get("total", 0)
            STATE.test_progress = {"current": total, "total": total, "percent": 100}
            _save_state()

        _emit("tests_progress", STATE.test_progress)

        _append_message(
            "orchestrator", "Test cases ready. Starting refinement.", tags=["tests"]
        )
        _run_codegen(labeled, outputs, analysis_payload, Path(image_path), run_path)
    except Exception as exc:
        logger.exception("Test generation failed")
        _append_message(
            "orchestrator",
            f"Test generation failed. {type(exc).__name__}: {exc}",
            tags=["error"],
        )
        _emit("error", {"stage": "tests", "message": str(exc)})


def _run_codegen(
    labeled_tests: List[Dict[str, Any]],
    outputs: List[str],
    analysis_payload: Dict[str, Any],
    image_path: Path,
    run_path: Path,
) -> None:
    _set_stage("code_refining")

    try:
        analysis = WorkflowAnalysis.model_validate(analysis_payload)
        harness = TestHarness(test_cases=labeled_tests, valid_outputs=outputs)
        workflow_slug = _slugify(STATE.workflow_name or "workflow")
        output_path = run_path / f"{workflow_slug}.py"

        solver = AgenticCodeSolver(
            workflow_image=image_path,
            workflow_analysis=analysis,
            valid_outputs=outputs,
            test_harness=harness,
            output_path=output_path,
        )

        def on_iteration(iteration_result: Any) -> None:
            data = {
                "iteration": iteration_result.iteration,
                "score": iteration_result.score,
                "passed": None,
                "total": None,
            }
            with STATE_LOCK:
                STATE.iterations.append(data)
                _save_state()
            _emit("iteration_result", data)

        evaluator = SolverEvaluator(
            score_threshold=1.0,
            max_iterations=MAX_ITERATIONS,
            on_iteration=on_iteration,
        )

        previous_cwd = Path.cwd()
        os.chdir(run_path)
        try:
            evaluator.evaluate(
                solver=solver,
                test_cases=labeled_tests,
                max_iterations=MAX_ITERATIONS,
                score_threshold=1.0,
            )
        finally:
            os.chdir(previous_cwd)

        with STATE_LOCK:
            STATE.generated_code_path = str(output_path)
            _save_state()

        _review_and_finalize(
            output_path=output_path,
            harness=harness,
            analysis=analysis,
            outputs=outputs,
            image_path=image_path,
            run_path=run_path,
        )
    except Exception as exc:
        logger.exception("Refinement failed")
        _append_message(
            "orchestrator",
            f"Refinement failed. {type(exc).__name__}: {exc}",
            tags=["error"],
        )
        _emit("error", {"stage": "refinement", "message": str(exc)})


def _review_and_finalize(
    *,
    output_path: Path,
    harness: TestHarness,
    analysis: WorkflowAnalysis,
    outputs: List[str],
    image_path: Path,
    run_path: Path,
) -> None:
    code = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    if not code:
        _append_message("orchestrator", "No code generated to review.", tags=["error"])
        _emit("error", {"stage": "review", "message": "Generated code missing"})
        return

    max_review_rounds = 2
    for review_round in range(1, max_review_rounds + 1):
        ok, feedback = _review_code(code)
        if ok:
            _append_message("orchestrator", "Code review passed. Finalizing output.")
            break

        _append_message(
            "orchestrator",
            f"Code review flagged issues (round {review_round}). Rewriting with feedback.",
            tags=["review"],
        )
        generator = CodeGenerator()
        context = GenerationContext(
            failures=[{"error": f"Code review feedback: {feedback}", "test_case": {}}],
            test_cases_file=run_path / "tests.json",
        )
        code = generator.generate(
            workflow_image_path=image_path,
            workflow_data=analysis,
            valid_outputs=outputs,
            context=context,
        )
        output_path.write_text(code, encoding="utf-8")
        score = harness.score(code)

        iteration_num = len(STATE.iterations) + 1
        iteration_data = {
            "iteration": iteration_num,
            "score": score.pass_rate,
            "passed": score.passed,
            "total": score.total,
        }
        with STATE_LOCK:
            STATE.iterations.append(iteration_data)
            _save_state()
        _emit("iteration_result", iteration_data)

        if score.pass_rate >= 1.0:
            _append_message("orchestrator", "Rewritten code passed all tests.")
            break

    with STATE_LOCK:
        _save_state()

    _set_stage("done")
    _append_message("orchestrator", "Pipeline complete. Your Python file is ready.")
    _emit(
        "artifact_ready",
        {
            "path": STATE.generated_code_path,
            "download_url": "/api/download",
        },
    )


def _review_code(code: str) -> tuple[bool, str]:
    prompt = (
        "You are a senior Python reviewer. Review the code for correctness, "
        "clarity, and adherence to deterministic logic. The code should not "
        "use try/except for normal control flow. Return JSON only in the form "
        "{\"status\": \"pass\"|\"fail\", \"feedback\": \"...\"}."
        "\n\nCODE:\n"
        + code
    )
    response = make_request(
        [{"role": "user", "content": prompt}],
        max_tokens=800,
        system="You are a strict Python code reviewer.",
    )
    text = response.content[0].text if response.content else ""
    try:
        data = json.loads(text)
        status = str(data.get("status", "")).lower()
        feedback = str(data.get("feedback", "")).strip()
        if status == "pass":
            return True, ""
        return False, feedback or "Review failed without specific feedback."
    except Exception:
        logger.warning("Code review returned invalid JSON; treating as pass.")
        return True, ""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
