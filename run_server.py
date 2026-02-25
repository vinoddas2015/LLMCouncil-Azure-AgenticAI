"""Azure App Service entry point.

Uvicorn with workers>1 uses multiprocessing.spawn (not fork) on Linux.
Spawned processes start a fresh Python interpreter that does NOT inherit
sys.path from the parent — only environment variables are preserved.

Fix: set PYTHONPATH env var BEFORE calling uvicorn.run() so spawned
workers can find the 'backend' package.

Startup command: python run_server.py
"""

import sys
import os

# 1. Add this script's directory to sys.path for the MASTER process
app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# 2. Set PYTHONPATH env var so SPAWNED worker processes also get the path
#    (multiprocessing.spawn inherits env vars but NOT sys.path)
current_pypath = os.environ.get("PYTHONPATH", "")
if app_dir not in current_pypath:
    os.environ["PYTHONPATH"] = (
        app_dir + os.pathsep + current_pypath if current_pypath else app_dir
    )

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("WEBSITES_PORT", "8000")))
    print(f"[run_server.py] app_dir={app_dir}")
    print(f"[run_server.py] PYTHONPATH={os.environ.get('PYTHONPATH', '')}")
    print(f"[run_server.py] sys.path={sys.path[:5]}")
    print(f"[run_server.py] CWD={os.getcwd()}")
    print(f"[run_server.py] Contents of {app_dir}: {os.listdir(app_dir)}")
    backend_path = os.path.join(app_dir, "backend")
    print(f"[run_server.py] backend/ exists: {os.path.isdir(backend_path)}")
    if os.path.isdir(backend_path):
        print(f"[run_server.py] backend/ contents: {os.listdir(backend_path)}")
    else:
        # Look for backend in all sys.path entries
        for p in sys.path:
            bp = os.path.join(p, "backend")
            if os.path.isdir(bp):
                print(f"[run_server.py] Found backend/ at {bp}: {os.listdir(bp)}")
                break
        # Check if there's a nested directory
        if os.path.isdir(app_dir):
            for item in os.listdir(app_dir):
                full = os.path.join(app_dir, item)
                if os.path.isdir(full):
                    print(f"[run_server.py]   subdir: {item}/ -> {os.listdir(full)[:5]}")
    print(f"[run_server.py] Starting uvicorn on port {port}, workers=1")
    sys.stdout.flush()
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        timeout_keep_alive=120,
        log_level="info",
    )
