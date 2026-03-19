#!/usr/bin/env bash

set -e

# Clear screen
clear

echo "================================================="
echo "        Bootstrapping IronCore Setup..."
echo "================================================="

# Tắt server cũ nếu có
pkill -f "uvicorn ironcore.api.server:app" || true

# Xóa môi trường cũ để khỏi bị nặng nếu user đang ở bản Full
if [ -d ".venv" ]; then
    echo ">> Removing old virtual environment (.venv)..."
    rm -rf .venv
fi

echo ">> Creating fresh virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

echo ">> Installing setup dependencies (this will only take a few seconds)..."
pip install -q questionary rich

# Run the interactive Setup Wizard
python setup.py
