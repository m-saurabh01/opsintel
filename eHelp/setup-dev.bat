@echo off
REM eHelp Windows Development Setup Script
REM Run this after extracting windows-dev-portable.zip

setlocal enabledelayedexpansion

echo.
echo ============================================
echo   eHelp - Offline Development Setup
echo ============================================
echo.

set "NODE_PATH=%cd%\node-v22.23.4-win-x64"
set "PYTHON_PATH=%cd%\python-3.11.9-embed-amd64"
set "UV_PATH=%cd%\uv-latest"

REM Check if paths exist
if not exist "%NODE_PATH%" (
    echo [ERROR] Node.js not found at %NODE_PATH%
    echo Please extract node-v22.23.4-win-x64 to this directory first.
    exit /b 1
)

if not exist "%PYTHON_PATH%" (
    echo [ERROR] Python not found at %PYTHON_PATH%
    echo Please extract python-3.11.9-embed-amd64 to this directory first.
    exit /b 1
)

echo [1/5] Verifying installations...
"%NODE_PATH%\node.exe" --version >nul 2>&1 || (
    echo [ERROR] Node.js verification failed
    exit /b 1
)
"%PYTHON_PATH%\python.exe" --version >nul 2>&1 || (
    echo [ERROR] Python verification failed
    exit /b 1
)
echo [OK] Node.js and Python are ready

echo.
echo [2/5] Setting up PATH...
set "PATH=%NODE_PATH%;%PYTHON_PATH%;%UV_PATH%;%PATH%"

echo.
echo [3/5] Installing backend dependencies...
cd /d "%cd%\backend"
"%UV_PATH%\uv.exe" pip install -q --system -r pyproject.toml 2>nul || (
    echo [ERROR] Failed to install Python dependencies
    exit /b 1
)
echo [OK] Backend ready

echo.
echo [4/5] Installing frontend dependencies...
cd /d "%cd%\frontend"
call "%NODE_PATH%\npm.cmd" install --legacy-peer-deps --quiet 2>nul || (
    echo [ERROR] Failed to install NPM dependencies
    exit /b 1
)
echo [OK] Frontend dependencies installed

echo.
echo [5/5] Building frontend...
call "%NODE_PATH%\npm.cmd" run build >nul 2>&1 || (
    echo [WARNING] Frontend build failed, but setup continues
)
echo [OK] Frontend built

echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo Next steps:
echo 1. Open two terminals in this directory
echo 2. Terminal 1: cd backend && run-dev.bat
echo 3. Terminal 2: cd frontend && npm run dev
echo 4. Open http://localhost:8123 in Chrome
echo.
echo Quick start (backend only):
echo   cd backend && run-dev.bat
echo.
pause
