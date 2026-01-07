"""Flask backend for LEMON frontend demo."""

import json
import os
import queue
import sys
import threading
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from flask_cors import CORS

# Add parent directory to path to import LEMON modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.lemon.config.settings import Settings
from src.lemon.core.pipeline import RefinementPipeline
from src.utils.request_utils import get_token_stats

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# Global state for progress streaming
progress_queue = queue.Queue()
current_status = {"stage": "idle", "message": "Ready"}


def emit_progress(stage, message, data=None):
    """Emit progress update."""
    update = {"stage": stage, "message": message, "data": data or {}}
    progress_queue.put(update)
    current_status.update(update)


def refinement_loop_with_progress(workflow_image="workflow.jpeg", max_iterations=None):
    """Refinement loop with progress callbacks."""
    try:
        emit_progress(
            "setup",
            "Starting Pipeline...",
            {"model": os.getenv("DEPLOYMENT_NAME", "Not set in .env")},
        )

        # Resolve workflow image path relative to project root
        if not Path(workflow_image).is_absolute():
            workflow_image_path = project_root / workflow_image
        else:
            workflow_image_path = Path(workflow_image)

        pipeline = RefinementPipeline(Settings(), progress_callback=emit_progress)
        result = pipeline.run_with_options(
            workflow_image=workflow_image_path, max_iterations=max_iterations
        )

        emit_progress(
            "complete",
            "Pipeline complete",
            {
                "code": result.code,
                "best_score": result.best_pass_rate,
                "final_score": result.final_validation_pass_rate,
            },
        )

    except Exception as e:
        emit_progress("error", f"❌ Error: {str(e)}", {"error": str(e)})
        import traceback

        emit_progress("error", f"Traceback: {traceback.format_exc()}")


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_pipeline():
    """Start the refinement pipeline."""
    global progress_queue
    progress_queue = queue.Queue()

    data = request.json or {}
    workflow_image = data.get("workflow_image", "workflow.jpeg")
    max_iterations = data.get("max_iterations")

    # Run in background thread
    thread = threading.Thread(
        target=refinement_loop_with_progress, args=(workflow_image, max_iterations)
    )
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/progress")
def progress():
    """Stream progress updates via Server-Sent Events."""

    def generate():
        while True:
            try:
                # Get update from queue (blocking with timeout)
                update = progress_queue.get(timeout=1)
                yield f"data: {json.dumps(update)}\n\n"

                # If complete or error, stop streaming
                if update["stage"] in ["complete", "error"]:
                    break
            except queue.Empty:
                # Send heartbeat to keep connection alive
                yield f"data: {json.dumps({'stage': 'heartbeat'})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/status")
def status():
    """Get current status."""
    return jsonify(current_status)


@app.route("/api/workflow-image")
def get_workflow_image():
    """Get the workflow image."""
    image_path = project_root / "workflow.jpeg"
    if image_path.exists():
        return send_from_directory(str(project_root), "workflow.jpeg")
    return jsonify({"error": "Workflow image not found"}), 404


@app.route("/api/generated-code")
def get_generated_code():
    """Get the generated code."""
    code_path = project_root / "generated_code.py"
    if code_path.exists():
        with open(code_path) as f:
            return jsonify({"code": f.read(), "exists": True})
    return jsonify({"exists": False})


@app.route("/api/token-stats")
def get_token_stats_endpoint():
    """Get current token usage statistics."""
    stats = get_token_stats()
    return jsonify(stats)


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
