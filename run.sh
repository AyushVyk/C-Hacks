#!/usr/bin/env sh
# One-command start for macOS and Linux: sets up Python's packages the first time, then starts SootAble
# and opens it in the browser.   Usage:  ./run.sh
cd "$(dirname "$0")" || exit 1

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
  echo "SootAble needs Python 3.10 or newer (with venv), and this computer does not have it."
  case "$(uname -s)" in
    Darwin) echo "Install it with:   brew install python      (no Homebrew? get Python from https://www.python.org/downloads/)" ;;
    *)      echo "Install it with:   sudo apt install python3 python3-venv python3-pip      (Debian, Ubuntu)"
            echo "                   sudo dnf install python3                               (Fedora)" ;;
  esac
  echo "Then run ./run.sh again."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up, this takes about a minute..."
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt || { echo "Setup failed."; exit 1; }
fi
exec .venv/bin/python main.py
