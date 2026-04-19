#!/bin/bash
set -e

# Require Python 3.8+
PYTHON=$(command -v python3 || command -v python)
PY_VERSION=$("$PYTHON" -c 'import sys; print(sys.version_info >= (3, 8))')

if [ "$PY_VERSION" != "True" ]; then
  echo "ERROR: Python 3.8 or higher is required."
  echo "Found: $($PYTHON --version)"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Install dependencies if needed
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  "$PYTHON" -m venv .venv
fi

source .venv/bin/activate

echo "Upgrading pip..."
pip install -q --upgrade pip

echo "Installing dependencies..."
pip install -q -r requirements.txt

echo ""
echo "Starting PR Review AI Assistant backend..."
echo "URL: http://127.0.0.1:8765"
echo "Logs: ~/.gh-ai-assistant/server.log"
echo ""

uvicorn main:app --host 127.0.0.1 --port 8765
