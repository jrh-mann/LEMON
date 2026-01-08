# 🍋 LEMON Dashboard

Beautiful, interactive dashboard for the LEMON workflow-to-code pipeline.

## Features

✨ **Beautiful UI** - Modern glassmorphism design with smooth animations
🔄 **Interactive Pipeline** - Visual flow diagram with real-time status updates
⚙️ **Configurable Steps** - Adjust parameters for each pipeline step
📊 **Live Stats** - Token usage, accuracy, and progress tracking
📋 **Live Logs** - Real-time output from pipeline steps

## Quick Start

```bash
# From the frontend directory
python start.py
```

Dashboard opens automatically at http://localhost:5000

## Manual Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
python dashboard_app.py
```

## Pipeline Steps

1. **🔍 Analyze Workflow** - Extract structure from flowchart image
2. **🎲 Generate Tests** - Create comprehensive test cases
3. **🏷️ Label Tests** - Label test cases with majority voting
4. **💻 Generate Code** - Create Python implementation
5. **🧪 Test Code** - Run tests in E2B sandbox
6. **✨ Refine** - Iteratively improve code quality

## Configuration

Click the ⚙️ button on any step to configure:

- **Batch Size** - Number of test cases per API call (default: 20)
- **Voting Rounds** - Number of independent labeling passes (default: 3)
- **Model** - Which LLM to use (GPT-4o, GPT-5, Haiku)
- **Max Iterations** - For refinement loop (default: 5)

## Tech Stack

- **Backend:** Flask + subprocess runners
- **Frontend:** HTML + Tailwind CSS + Alpine.js
- **No build step required** - All dependencies from CDN
- **Zero config** - Just run and go

## API Endpoints

```
GET  /                    - Dashboard UI
POST /api/run/<step_id>  - Run pipeline step
GET  /api/status/<step_id> - Get step status
GET  /api/stats          - Get overall stats
```

## Screenshots

![Dashboard](screenshot.png)

## Development

The dashboard is intentionally simple:
- Single HTML file with inline styles
- Alpine.js for reactivity (no build step)
- Tailwind CSS from CDN
- Flask backend calls your existing Python scripts

## Customization

Edit `templates/dashboard.html` to:
- Change colors (update Tailwind classes)
- Add more steps to the pipeline
- Modify step configurations
- Customize the UI layout

No rebuild needed - just refresh the page!

---

**Note:** This is a demo dashboard. For production use, consider:
- WebSockets for real-time updates (instead of polling)
- Better error handling and logging
- Authentication/authorization
- Persistent storage of results
- Background task queue (Celery/Redis)
