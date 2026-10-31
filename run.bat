@echo off
rem One-click start for Windows. Sets everything up the first time (installing Python itself if the PC has none),
rem then starts SootAble and opens it in the browser.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run

call :findpy
if defined PY goto setup

where winget >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ then run this again.
  pause & exit /b 1
)
echo Python was not found. Installing Python 3.12 with winget, this takes a few minutes...
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PY="%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo Python is installed now. Close this window and double-click run.bat again.
  pause & exit /b 0
)

:setup
echo First run: setting up, this takes about a minute...
%PY% -m venv .venv || (echo Could not create the virtual environment. & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo Install failed. Check your internet connection. & pause & exit /b 1)

:run
".venv\Scripts\python.exe" main.py
pause
exit /b 0

:findpy
rem Sets PY to a working Python 3.10+ command, or leaves it empty.
set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if defined PY goto :eof
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
goto :eof
