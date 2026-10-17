#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Detect IP for multi-device access
LAN_IP=$(.venv/bin/python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "127.0.0.1")

echo "=========================================================="
echo " 📚 EPUB TRANSLATOR WEB UI"
echo "=========================================================="
echo " - Akses Lokal (Komputer ini) : http://localhost:8501"
echo " - Akses Jaringan (HP / Tablet): http://${LAN_IP}:8501"
echo "=========================================================="
echo "Tekan Ctrl+C di terminal ini untuk menghentikan server."
echo ""

exec .venv/bin/streamlit run app_streamlit.py \
    --server.address 0.0.0.0 \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false

