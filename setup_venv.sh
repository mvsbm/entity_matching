#!/usr/bin/env bash
# Creates .venv with the pinned dependencies; VS Code then lists .venv as a Jupyter kernel (notebooks/demo.ipynb).
set -euo pipefail
cd "$(dirname "$0")"

python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required (PEP 695 generics)"'
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
echo "Done. In VS Code: Select Kernel → Python Environments → .venv"
