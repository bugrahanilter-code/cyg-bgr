@echo off
REM ---------------------------------------------------------------------------
REM Starts the trading platform backend without Docker.
REM Double-click this file, then leave the window open.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\..\backend"

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment for the first time...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python was not found. Install Python 3.11 or newer from python.org
        echo and make sure "Add python.exe to PATH" is ticked.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo Starting the backend on http://localhost:8000
echo API documentation: http://localhost:8000/docs
echo Press Ctrl+C to stop.
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
