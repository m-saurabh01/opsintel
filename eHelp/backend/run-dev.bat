@echo off
REM eHelp Windows Development Runner
REM Run this from the backend directory to start the dev server

setlocal enabledelayedexpansion

set "PYTHON_PATH=..\python-3.11.9-embed-amd64"
set "UV_PATH=..\uv-latest"

if not exist "%PYTHON_PATH%" (
    echo [ERROR] Python not found. Run setup-dev.bat from the parent directory first.
    exit /b 1
)

echo.
echo ============================================
echo   eHelp Development Server
echo ============================================
echo.
echo Starting FastAPI on http://localhost:8123
echo Press Ctrl+C to stop
echo.

set "EHELP_DEV_ADMIN=1"
set "EHELP_DATA_DIR=%APPDATA%\ehelp\data"
set "PYTHONPATH=%cd%"

REM Create data directory if it doesn't exist
if not exist "%EHELP_DATA_DIR%" mkdir "%EHELP_DATA_DIR%"

REM Run the development server
"%PYTHON_PATH%\python.exe" -m uvicorn ehelp.app:app --host 127.0.0.1 --port 8123 --reload

pause
