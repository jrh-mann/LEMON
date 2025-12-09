"""Flask backend for LEMON frontend demo."""

import os
import sys
import json
import queue
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from flask_cors import CORS

# Add parent directory to path to import LEMON modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.code_generator import generate_workflow_code
from src.utils.code_test_harness import CodeTestHarness
from src.utils.workflow_agent import WorkflowAgent
from src.utils.test_case_generator import TestCaseGenerator
from src.utils.request_utils import get_token_stats
import ast

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Global state for progress streaming
progress_queue = queue.Queue()
current_status = {"stage": "idle", "message": "Ready"}


def emit_progress(stage, message, data=None):
    """Emit progress update."""
    update = {
        "stage": stage,
        "message": message,
        "data": data or {}
    }
    progress_queue.put(update)
    current_status.update(update)


def validate_code_structure(code: str) -> bool:
    """Static analysis to ensure code is runnable."""
    try:
        tree = ast.parse(code)
        has_function = any(
            isinstance(node, ast.FunctionDef) and node.name == 'determine_workflow_outcome'
            for node in ast.walk(tree)
        )
        return has_function
    except SyntaxError:
        return False


def refinement_loop_with_progress(workflow_image="workflow.jpeg", max_iterations=None):
    """Refinement loop with progress callbacks."""
    try:
        emit_progress("setup", "🚀 Starting Pipeline...", {
            "model": os.getenv("DEPLOYMENT_NAME", "Not set in .env")
        })
        
        # Resolve workflow image path relative to project root
        if not Path(workflow_image).is_absolute():
            workflow_image_path = project_root / workflow_image
        else:
            workflow_image_path = Path(workflow_image)
        
        inputs_file = project_root / "workflow_inputs.json"
        outputs_file = project_root / "workflow_outputs.json"
        
        if inputs_file.exists() and outputs_file.exists():
            emit_progress("analysis", "✅ Found existing workflow analysis files, skipping analysis step")
            with open(outputs_file) as f:
                valid_outputs = json.load(f)
            with open(inputs_file) as f:
                standardized_inputs = json.load(f)
            data = {
                "inputs": standardized_inputs,
                "outputs": [{"name": output} for output in valid_outputs]
            }
            emit_progress("analysis", f"✅ Loaded {len(standardized_inputs)} inputs and {len(valid_outputs)} outputs")
        else:
            emit_progress("analysis", "🔍 Analyzing workflow structure...")
            agent = WorkflowAgent(max_tokens=16000)
            data = agent.analyze_workflow_structured(str(workflow_image_path))
            
            if "error" in data:
                emit_progress("error", f"❌ Workflow analysis failed: {data.get('error_message', 'Unknown error')}")
                return
            
            valid_outputs = agent.extract_and_save_outputs(data, str(project_root / "workflow_outputs.json"))
            standardized_inputs = agent.extract_and_save_inputs(data, str(project_root / "workflow_inputs.json"))
            
            emit_progress("analysis", f"✅ Analysis complete: {len(standardized_inputs)} inputs, {len(valid_outputs)} outputs", {
                "inputs": standardized_inputs,
                "outputs": valid_outputs
            })
        
        emit_progress("test_generation", "🧪 Generating 1000 initial test cases...")
        gen = TestCaseGenerator(str(project_root / "workflow_inputs.json"))
        test_cases = gen.generate_test_cases(1000, "comprehensive")
        gen.save_test_cases(test_cases, str(project_root / "tests.json"))
        emit_progress("test_generation", f"✅ Generated {len(test_cases)} test cases")
        
        harness = CodeTestHarness(str(project_root / "tests.json"), valid_outputs)
        failures = None
        best_score = 0.0
        code = None
        iteration = 0
        
        emit_progress("refinement", "🔄 Starting refinement loop...")
        
        while True:
            iteration += 1
            if max_iterations and iteration > max_iterations:
                emit_progress("refinement", f"⚠️ Reached max iterations ({max_iterations}). Stopping.")
                break
            
            emit_progress("refinement", f"🔄 Iteration {iteration}" + (f"/{max_iterations}" if max_iterations else ""), {
                "iteration": iteration,
                "best_score": best_score
            })
            
            emit_progress("code_generation", "💻 Generating code...")
            code = generate_workflow_code(str(workflow_image_path), data, valid_outputs, failures)
            
            emit_progress("code_generation", "✅ Code generated", {"code": code})
            
            if not validate_code_structure(code):
                emit_progress("validation", "⚠️ Generated invalid code structure. Retrying...")
                continue
            
            with open(project_root / "generated_code.py", "w") as f:
                f.write(code)
            
            emit_progress("testing", "🧪 Running sandbox tests...")
            score_data = harness.score(code)
            current_score = score_data['pass_rate']
            
            emit_progress("testing", f"📊 Score: {current_score*100:.1f}% ({score_data['passed']}/{score_data['total']})", {
                "score": current_score,
                "passed": score_data['passed'],
                "total": score_data['total'],
                "failures": score_data['failures'][:5] if score_data['failures'] else []
            })
            
            if current_score == 1.0:
                emit_progress("success", "✅ Initial Validation Passed (100%)")
                break
            
            if current_score > best_score:
                emit_progress("progress", f"📈 Improved from {best_score*100:.1f}% to {current_score*100:.1f}%")
            
            best_score = max(best_score, current_score)
            failures = score_data['failures']
        
        if best_score == 1.0:
            emit_progress("final_validation", "🔒 Final Validation (Adversarial Edge Cases)...")
            final_tests = gen.generate_test_cases(200, "edge_cases")
            gen.save_test_cases(final_tests, str(project_root / "final_tests.json"))
            
            final_harness = CodeTestHarness(str(project_root / "final_tests.json"), valid_outputs)
            final_score = final_harness.score(code)
            
            emit_progress("final_validation", f"🏁 Final Edge Case Score: {final_score['pass_rate']*100:.1f}%", {
                "final_score": final_score['pass_rate'],
                "final_passed": final_score['passed'],
                "final_total": final_score['total']
            })
            
            if final_score['pass_rate'] == 1.0:
                emit_progress("complete", "🎉 SUCCESS! Code Verified & Ready to Ship.", {
                    "code": code,
                    "final_score": final_score['pass_rate']
                })
            else:
                emit_progress("warning", f"⚠️ Failed on edge cases. Failures: {len(final_score['failures'])}")
        else:
            emit_progress("warning", f"❌ Failed to converge to 100% accuracy. Best: {best_score*100:.1f}%", {
                "code": code,
                "best_score": best_score
            })
            
    except Exception as e:
        emit_progress("error", f"❌ Error: {str(e)}", {"error": str(e)})
        import traceback
        emit_progress("error", f"Traceback: {traceback.format_exc()}")


@app.route('/')
def index():
    """Serve the main page."""
    return render_template('index.html')


@app.route('/api/start', methods=['POST'])
def start_pipeline():
    """Start the refinement pipeline."""
    global progress_queue
    progress_queue = queue.Queue()
    
    data = request.json or {}
    workflow_image = data.get('workflow_image', 'workflow.jpeg')
    max_iterations = data.get('max_iterations')
    
    # Run in background thread
    thread = threading.Thread(
        target=refinement_loop_with_progress,
        args=(workflow_image, max_iterations)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started"})


@app.route('/api/progress')
def progress():
    """Stream progress updates via Server-Sent Events."""
    def generate():
        while True:
            try:
                # Get update from queue (blocking with timeout)
                update = progress_queue.get(timeout=1)
                yield f"data: {json.dumps(update)}\n\n"
                
                # If complete or error, stop streaming
                if update['stage'] in ['complete', 'error']:
                    break
            except queue.Empty:
                # Send heartbeat to keep connection alive
                yield f"data: {json.dumps({'stage': 'heartbeat'})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/status')
def status():
    """Get current status."""
    return jsonify(current_status)


@app.route('/api/workflow-image')
def get_workflow_image():
    """Get the workflow image."""
    image_path = project_root / "workflow.jpeg"
    if image_path.exists():
        return send_from_directory(str(project_root), "workflow.jpeg")
    return jsonify({"error": "Workflow image not found"}), 404


@app.route('/api/generated-code')
def get_generated_code():
    """Get the generated code."""
    code_path = project_root / "generated_code.py"
    if code_path.exists():
        with open(code_path) as f:
            return jsonify({"code": f.read(), "exists": True})
    return jsonify({"exists": False})


@app.route('/api/token-stats')
def get_token_stats_endpoint():
    """Get current token usage statistics."""
    stats = get_token_stats()
    return jsonify(stats)


if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)

