#!/bin/bash
# Quick start script for LEMON Frontend

echo "🍋 Starting LEMON Frontend..."
echo ""
echo "Make sure you have:"
echo "  ✓ Installed frontend dependencies: pip install -r requirements.txt"
echo "  ✓ Installed main LEMON dependencies (from parent directory)"
echo "  ✓ Configured .env file with API keys"
echo ""
echo "Starting Flask server on http://localhost:5000"
echo "Press Ctrl+C to stop"
echo ""

cd "$(dirname "$0")"
python app.py

