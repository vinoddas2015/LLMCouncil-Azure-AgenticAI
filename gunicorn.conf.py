"""Gunicorn configuration for Azure App Service.

This config adds the current working directory to sys.path so that
the 'backend' package is importable. Oryx extracts the app to a temp
directory and sets PYTHONPATH to only the virtualenv site-packages,
so without this fix `import backend` fails.
"""
import os
import sys

# Add the app root (where backend/ lives) to sys.path
app_root = os.path.dirname(os.path.abspath(__file__))
if app_root not in sys.path:
    sys.path.insert(0, app_root)

# Gunicorn settings
bind = "0.0.0.0:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
