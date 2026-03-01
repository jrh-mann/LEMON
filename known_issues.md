# Known Issues

This document tracks known issues, technical debt, and areas requiring future attention in the LEMON codebase.

## 1. Subflow Python Export Fallback
- **Location**: `src/backend/execution/python_compiler.py` (line 792)
- **Description**: When a subflow is missing or not reachable via the database, the `PythonCodeGenerator` defaults to rendering a commented out block such as `# TODO: Implement call to subworkflow 'abc'`. We recently implemented recursive subflow fetching, but if fetching fails, this graceful degradation requires manual intervention from the developer running the script.

## 2. Hardcoded Temporary Directory Paths
- **Description**: Certain evaluations (`test_run_image_eval_integration.py`, local execution pipelines) previously used hardcoded `Path("/tmp")` paths. This is a known issue on Windows where `/tmp` gets mapped to `$DRIVE/tmp` and may not exist. Most of these have been resolved dynamically, but some scripts might still be brittle across operating systems.
- **Resolution**: Need to audit the repository for lingering `Path("/tmp")` literals and replace them with standard cross-platform routines such as Python's native `tempfile` module.

## 3. `on_step` Interpreter Callback Payload Changes
- **Description**: Over iterations, the `TreeInterpreter` started firing non-node execution steps such as `event_type="start_executed"`, `"subflow_start"`, `"end_reached"`, and `"calculation_completed"` alongside the standard iteration `step_info` items.
- **Impact**: Some of testing suites broke due to length mismatch in accumulated `steps`. Tests were patched to filter `step_index` payloads, but long term, the typing on the event callbacks needs a strict interface definition.

## 4. Circular Subflow Dependency Protection 
- **Description**: While `TreeInterpreter` implements protection in the form of `SubflowCycleError` when a workflow calls itself directly or indirectly, the frontend visualizer currently allows users to attempt to generate cycles (adding a subflow node pointing to an ancestor).
- **Impact**: Creating these edges will only fail during compile time or runtime, rather than preventing the UI state to begin with.

## 5. File Uploads without DB tracking
- **Description**: Uploaded images (such as for node LLM analysis) are mapped to static URLs using the hash, but aren't cleaned up automatically over time. This can bloat storage if used extensively without cleanup crons.
