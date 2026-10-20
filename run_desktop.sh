#!/usr/bin/env bash
# Quick launcher for EPUB Translator Desktop GUI
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    exec "$SCRIPT_DIR/.venv/bin/python" desktop_app.py "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 desktop_app.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python desktop_app.py "$@"
else
    echo "Error: Python 3 not found. Please activate your virtual environment or install python3."
    exit 1
fi

