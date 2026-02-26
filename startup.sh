#!/bin/bash
# Startup script for Azure App Service
# Handles Oryx compressed output extraction, venv activation, and server start

set -e
cd /home/site/wwwroot

# 1. Extract Oryx compressed output if present (CompressDestinationDir=true)
if [ -f output.tar.gz ]; then
    echo "[startup.sh] Extracting output.tar.gz ..."
    tar xzf output.tar.gz
    echo "[startup.sh] Extraction complete."
fi

# 2. Set PYTHONPATH so 'backend' package is importable
export PYTHONPATH="/home/site/wwwroot:${PYTHONPATH}"

# 3. Activate the Oryx-built virtual environment
if [ -d /home/site/wwwroot/antenv ]; then
    echo "[startup.sh] Activating antenv virtual environment"
    source /home/site/wwwroot/antenv/bin/activate
fi

# 4. Debug: list files to confirm extraction
echo "[startup.sh] wwwroot contents: $(ls -la)"
echo "[startup.sh] backend/ exists: $(test -d backend && echo YES || echo NO)"

# 5. Start the server
echo "[startup.sh] Starting uvicorn on port ${WEBSITES_PORT:-8000}"
exec python run_server.py
