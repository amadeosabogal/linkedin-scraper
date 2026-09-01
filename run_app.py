"""
Launcher script for LinkedIn Lead Hunter & Job Matcher Platform.
Run with:
    py run_app.py
or
    python run_app.py
"""
import sys
import os
import asyncio
import uvicorn

# Ensure the root directory is on the python search path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# On Windows, Playwright requires WindowsProactorEventLoopPolicy for async subprocesses
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 LinkedIn Lead Hunter & Job Matcher Platform")
    print("📍 URL: http://127.0.0.1:8000")
    print("=" * 60)
    
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        loop="asyncio"
    )
