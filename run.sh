#!/usr/bin/env sh
# One-command start for macOS and Linux: sets up Python's packages the first time, then starts SootAble
# and opens it in the browser.   Usage:  ./run.sh
cd "$(dirname "$0")" || exit 1
command -v python3 >/dev/null 2>&1 || { echo "Python 3.10 or newer is needed: https://www.python.org/downloads/"; exit 1; }
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up, this takes about a minute..."
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt || { echo "Setup failed."; exit 1; }
fi
exec .venv/bin/python main.py
