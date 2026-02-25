#!/bin/bash
# Startup script for Azure App Service
# Ensures PYTHONPATH includes the wwwroot so 'backend' package is importable

export PYTHONPATH="/home/site/wwwroot:${PYTHONPATH}"
cd /home/site/wwwroot

# Activate the Oryx-built virtual environment
if [ -d /home/site/wwwroot/antenv ]; then
    source /home/site/wwwroot/antenv/bin/activate
fi

exec gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.main:app --bind 0.0.0.0:8000 --timeout 120
