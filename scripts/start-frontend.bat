@echo off
REM ---------------------------------------------------------------------------
REM Starts the dashboard without Docker.
REM Start the backend first, then double-click this file.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0\..\frontend"

if not exist "node_modules" (
    echo Installing the dashboard packages for the first time...
    call npm install
    if errorlevel 1 (
        echo.
        echo Node.js was not found. Install it from nodejs.org and try again.
        pause
        exit /b 1
    )
)

echo.
echo Starting the dashboard on http://localhost:3000
echo Press Ctrl+C to stop.
echo.
call npm run dev
pause
