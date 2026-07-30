#!/bin/bash
# ==============================================================================
# Ops Console & Stats Agent Server Setup Script
# ==============================================================================
# This script installs all necessary dependencies (including a virtual screen Xvfb)
# to run the CleverTap Stats Agent in headed mode on a cloud VM (GCP/AWS/Ubuntu).
# ==============================================================================

set -e

echo "=== Updating Package lists ==="
sudo apt-get update -y

echo "=== Installing Python and virtual environment libraries ==="
sudo apt-get install -y python3-pip python3-venv python3-dev build-essential

echo "=== Installing Xvfb (Virtual Screen) and display dependencies ==="
sudo apt-get install -y xvfb fluxbox x11-apps

echo "=== Setting up virtual environment ==="
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Virtual environment created."
fi

echo "=== Installing python packages ==="
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install python-dotenv

echo "=== Installing Playwright and browser dependencies ==="
./.venv/bin/playwright install chromium
sudo ./.venv/bin/playwright install-deps chromium

echo "=============================================================================="
echo " Setup complete!"
echo "=============================================================================="
echo " To run the server with the virtual display in the background, use:"
echo ""
echo "   Xvfb :99 -screen 0 1280x1024x24 &"
echo "   export DISPLAY=:99"
echo "   nohup ./.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &"
echo ""
echo " The website will then be available at: http://<your-vm-ip>:8000"
echo "=============================================================================="
