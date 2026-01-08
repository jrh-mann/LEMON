"""Flask server for LEMON dashboard."""

import json
import subprocess
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Store running tasks
active_tasks = {}


@app.route("/")
def index():
    """Render dashboard."""
    return render_template("dashboard.html")


@app.route("/api/run/<step_id>", methods=["POST"])
def run_step(step_id):
    """Run a pipeline step."""
    config = request.json or {}
    
    # Map step IDs to scripts
    scripts = {
        "analyze": "python main.py",
        "generate": "python generate_test_cases.py",
        "label": f"python label_test_cases.py --best-of-n {config.get('votingRounds', 3)} --batch-size {config.get('batchSize', 20)}",
        "code": "python workflow_code.py",  # Placeholder
        "test": "python run_tests.py",
        "refine": "python refine_code.py --max-iterations {config.get('maxIterations', 5)}"
    }
    
    script = scripts.get(step_id)
    if not script:
        return jsonify({"error": f"Unknown step: {step_id}"}), 400
    
    # Mark as running
    active_tasks[step_id] = {"status": "running", "progress": 0}
    
    # Run in background thread
    def run_task():
        try:
            print(f"🔄 Running: {script}")
            result = subprocess.run(
                script,
                shell=True,
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent
            )
            
            print(f"✅ Completed {step_id}: return code {result.returncode}")
            print(f"Output: {result.stdout[:200]}...")
            
            # Parse results based on step
            stats = parse_step_results(step_id, result.stdout)
            
            active_tasks[step_id] = {
                "status": "complete" if result.returncode == 0 else "failed",
                "stats": stats,
                "output": result.stdout,
                "error": result.stderr if result.returncode != 0 else None
            }
            
        except Exception as e:
            print(f"❌ Error in {step_id}: {e}")
            active_tasks[step_id] = {
                "status": "failed",
                "error": str(e)
            }
    
    thread = threading.Thread(target=run_task, daemon=True)
    thread.start()
    
    return jsonify({
        "status": "started",
        "step_id": step_id
    })


@app.route("/api/status/<step_id>")
def get_status(step_id):
    """Get status of a running step."""
    task = active_tasks.get(step_id, {"status": "unknown"})
    return jsonify(task)


@app.route("/api/stats")
def get_stats():
    """Get overall pipeline statistics."""
    
    # Load token usage
    token_file = Path(__file__).parent.parent / "tokens.json"
    tokens = 0
    if token_file.exists():
        with open(token_file) as f:
            data = json.load(f)
            tokens = data.get("total_tokens", 0)
    
    # Load test results
    test_file = Path(__file__).parent.parent / "labeled_test_cases.json"
    accuracy = 0
    if test_file.exists():
        # Calculate accuracy from test results
        # This is a placeholder - adjust based on your actual data structure
        accuracy = 75  # Default
    
    return jsonify({
        "token_usage": tokens,
        "accuracy": accuracy,
        "steps_complete": len([t for t in active_tasks.values() if t.get("status") == "complete"])
    })


@app.route("/api/files")
def get_files():
    """Get status of all artifact files."""
    base_dir = Path(__file__).parent.parent
    
    files = {
        "workflow_analysis.json": {
            "exists": (base_dir / "workflow_analysis.json").exists(),
            "size": (base_dir / "workflow_analysis.json").stat().st_size if (base_dir / "workflow_analysis.json").exists() else 0,
            "produces_step": "analyze",
            "used_by": ["label"]
        },
        "workflow_inputs.json": {
            "exists": (base_dir / "workflow_inputs.json").exists(),
            "size": (base_dir / "workflow_inputs.json").stat().st_size if (base_dir / "workflow_inputs.json").exists() else 0,
            "produces_step": "analyze",
            "used_by": ["generate", "label"]
        },
        "workflow_outputs.json": {
            "exists": (base_dir / "workflow_outputs.json").exists(),
            "size": (base_dir / "workflow_outputs.json").stat().st_size if (base_dir / "workflow_outputs.json").exists() else 0,
            "produces_step": "analyze",
            "used_by": ["generate", "label"]
        },
        "test_cases.json": {
            "exists": (base_dir / "test_cases.json").exists(),
            "size": (base_dir / "test_cases.json").stat().st_size if (base_dir / "test_cases.json").exists() else 0,
            "produces_step": "generate",
            "used_by": ["label"]
        },
        "labeled_test_cases.json": {
            "exists": (base_dir / "labeled_test_cases.json").exists(),
            "size": (base_dir / "labeled_test_cases.json").stat().st_size if (base_dir / "labeled_test_cases.json").exists() else 0,
            "produces_step": "label",
            "used_by": ["test", "refine"]
        },
        "workflow_code.py": {
            "exists": (base_dir / "workflow_code.py").exists(),
            "size": (base_dir / "workflow_code.py").stat().st_size if (base_dir / "workflow_code.py").exists() else 0,
            "produces_step": "code",
            "used_by": ["test"]
        }
    }
    
    return jsonify(files)


@app.route("/api/files/<filename>", methods=["DELETE"])
def delete_file(filename):
    """Delete an artifact file."""
    base_dir = Path(__file__).parent.parent
    file_path = base_dir / filename
    
    # Whitelist of allowed files
    allowed_files = [
        "workflow_analysis.json",
        "workflow_inputs.json", 
        "workflow_outputs.json",
        "test_cases.json",
        "labeled_test_cases.json",
        "workflow_code.py"
    ]
    
    if filename not in allowed_files:
        return jsonify({"error": "File not allowed"}), 403
    
    try:
        if file_path.exists():
            file_path.unlink()
            return jsonify({"status": "deleted", "filename": filename})
        else:
            return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def parse_step_results(step_id, output):
    """Parse script output to extract statistics."""
    stats = {}
    
    if step_id == "generate":
        # Extract: "Generated 100 test cases"
        if "test cases" in output:
            import re
            match = re.search(r"(\d+) test cases", output)
            if match:
                stats["count"] = match.group(1)
    
    elif step_id == "label":
        # Extract: "Labeled 95/100"
        if "labeled" in output.lower():
            import re
            match = re.search(r"(\d+)/(\d+)", output)
            if match:
                stats["labeled"] = match.group(1)
                stats["total"] = match.group(2)
    
    elif step_id == "test":
        # Extract: "Pass Rate: 75.0%"
        if "Pass Rate" in output:
            import re
            match = re.search(r"Pass Rate: ([\d.]+)%", output)
            if match:
                stats["pass_rate"] = match.group(1)
    
    return stats


if __name__ == "__main__":
    print("🍋 LEMON Dashboard starting...")
    print("📍 Open http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
