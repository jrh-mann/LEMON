"""Quick start script for LEMON dashboard."""

import subprocess
import webbrowser
import time
from pathlib import Path

def main():
    print("🍋 Starting LEMON Dashboard...")
    print()
    
    # Install frontend dependencies
    print("📦 Installing dependencies...")
    frontend_dir = Path(__file__).parent
    subprocess.run(
        ["pip", "install", "-r", "requirements.txt"],
        cwd=frontend_dir,
        check=True
    )
    
    print("✅ Dependencies installed")
    print()
    
    # Start Flask server
    print("🚀 Starting server...")
    print("📍 Dashboard will open at http://localhost:5000")
    print()
    
    # Open browser after short delay
    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:5000")
    
    import threading
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run Flask app
    subprocess.run(
        ["python", "dashboard_app.py"],
        cwd=frontend_dir
    )

if __name__ == "__main__":
    main()
