@echo off
rem One-click start for Windows: sets up Python's packages the first time, then starts SootAble and opens it in the browser.
cd /d "%~dp0"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up, this takes about a minute...
  %PY% -m venv .venv || (echo Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/ & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo Install failed. Check your internet connection. & pause & exit /b 1)
)
".venv\Scripts\python.exe" main.py
pause
