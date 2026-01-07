# LEMON Frontend Demo

Interactive web UI for visualizing the LEMON workflow-to-code pipeline in real time.

## Features

- 🎨 **Modern UI** - Beautiful dark theme with smooth animations
- 📊 **Real-time Progress** - Live updates via Server-Sent Events (SSE)
- 📈 **Metrics Dashboard** - Track iterations, test scores, and pass rates
- 💻 **Code Display** - Syntax-highlighted generated code
- 📋 **Detailed Logs** - Verbose progress logging with timestamps
- 🖼️ **Workflow Visualization** - Display workflow diagram
- ✅ **Test Results** - View test failures and success rates

## Installation

From repo root:

```bash
uv pip install -r requirements.txt
```

3. Make sure your `.env` file is configured with:
   - `ENDPOINT` - Anthropic API endpoint
   - `DEPLOYMENT_NAME` - Model name
   - `API_KEY` - API key
   - `E2B_API_KEY` - E2B sandbox API key

## Running the Frontend

```bash
uv run python frontend/app.py
```

2. Open your browser and navigate to:
```
http://localhost:5000
```

3. Click "Start Pipeline" to begin the workflow-to-code generation process!

## Usage

1. **Start Pipeline**: Click the "Start Pipeline" button to begin
2. **Monitor Progress**: Watch the timeline and live logs as the pipeline progresses
3. **View Metrics**: Check the dashboard for real-time test scores and iteration count
4. **Review Code**: Generated code appears automatically with syntax highlighting
5. **Check Results**: View detailed test results and any failures

## Pipeline Stages

The frontend visualizes these stages:

1. **Setup** - Initializing the pipeline
2. **Workflow Analysis** - Analyzing workflow structure
3. **Test Case Generation** - Generating comprehensive test cases
4. **Code Refinement** - Iteratively improving code through testing
5. **Final Validation** - Validating with edge cases

## Architecture

- **Backend**: Flask with Server-Sent Events for real-time progress streaming
- **Frontend**: Vanilla HTML/CSS/JavaScript with Prism.js for code highlighting
- **Progress Updates**: Queue-based progress updates streamed to the frontend

## Troubleshooting

- **Port already in use**: Change the port in `app.py` (default: 5000)
- **Workflow image not found**: Ensure `workflow.jpeg` exists in the parent directory
- **API errors**: Check that your `.env` file is properly configured

