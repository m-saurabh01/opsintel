# Windows Portable Packaging Guide

## Overview

This guide explains how to create portable `windows-dev-portable.zip` and `windows-deploy-portable.zip` packages for offline Windows development and deployment.

---

## Prerequisites

- Windows 10/11 machine with internet access
- 7-Zip or WinRAR (or use built-in Windows compression)
- Approximately 2-3 GB free disk space
- Administrator access

---

## Part 1: Create Portable Node.js

### Step 1: Download Node.js Portable

1. Go to https://nodejs.org/en/download/
2. Download **Node.js v22.x** (LTS) - **Windows Portable ZIP** (not installer)
   - Look for: `node-v22.x.x-win-x64.zip`
   - Size: ~50-60 MB

### Step 2: Extract & Verify

```bash
# Extract to temp location
Expand-Archive node-v22.x.x-win-x64.zip -DestinationPath C:\temp\node-portable

# Test
C:\temp\node-portable\node.exe --version
# Output: v22.x.x

C:\temp\node-portable\npm.cmd --version
# Output: x.x.x
```

### Step 3: Pre-install NPM Dependencies

```bash
cd C:\ehelp\frontend

# Copy node portable to frontend
xcopy C:\temp\node-portable . /E /I /Y

# Install dependencies using portable npm
.\node_modules\.bin\npm install
# or if npm not in node_modules yet:
.\npm.cmd install

# Verify
.\node.exe --version
.\npm.cmd list --depth=0
```

---

## Part 2: Create Portable Python

### Step 1: Download Python Portable

1. Go to https://www.python.org/downloads/
2. Download **Python 3.12.8** - **Windows Embeddable Package** (portable)
   - Look for: `python-3.12.8-embed-amd64.zip`
   - Size: ~30-40 MB

### Step 2: Extract & Configure

```bash
# Extract to temp location
Expand-Archive python-3.12.8-embed-amd64.zip -DestinationPath C:\temp\python-portable

# Create python311._pth file to enable site-packages
# Navigate to extracted folder
cd C:\temp\python-portable

# Edit python312._pth (created automatically)
# Add this line to enable pip:
# Lib\site-packages

# Or create manually:
echo Lib\site-packages > python312._pth
```

### Step 3: Install pip

```bash
# Download get-pip.py
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py

# Run with portable python
C:\temp\python-portable\python.exe get-pip.py

# Verify
C:\temp\python-portable\python.exe -m pip --version
# Output: pip x.x.x from C:\temp\python-portable\Lib\site-packages...
```

### Step 4: Install UV Package Manager

```bash
# Install UV
C:\temp\python-portable\python.exe -m pip install uv

# Verify
C:\temp\python-portable\python.exe -m uv --version
# Output: uv x.x.x
```

### Step 5: Install Backend Dependencies

```bash
cd C:\ehelp\backend

# Create virtual environment using portable python
C:\temp\python-portable\python.exe -m venv venv

# Activate venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# or using uv:
uv pip install -r requirements.txt

# Verify
pip list
deactivate
```

---

## Part 3: Create windows-dev-portable.zip

### Structure

```
windows-dev-portable/
├── Node/                          # Portable Node.js
│   ├── node.exe
│   ├── npm.cmd
│   ├── npx.cmd
│   └── node_modules/
├── Python/                        # Portable Python
│   ├── python.exe
│   ├── python.dll
│   ├── pip.exe
│   ├── Lib/
│   └── Scripts/
├── ehelp/
│   ├── frontend/                  # Pre-installed dependencies
│   │   ├── node_modules/
│   │   ├── src/
│   │   ├── public/
│   │   ├── vite.config.js
│   │   ├── package.json
│   │   └── package-lock.json
│   ├── backend/                   # Pre-installed dependencies
│   │   ├── venv/                  # Virtual environment
│   │   ├── ehelp/
│   │   ├── requirements.txt
│   │   ├── pyproject.toml
│   │   └── run-dev.bat
│   ├── README.md
│   ├── setup-dev.bat              # Main setup script
│   └── data/                      # Empty data directory
└── START.bat                       # Quick launcher
```

### Step 1: Organize Directories

```bash
# Create structure
mkdir C:\portable-dev
mkdir C:\portable-dev\Node
mkdir C:\portable-dev\Python
mkdir C:\portable-dev\ehelp

# Copy components
xcopy C:\temp\node-portable\* C:\portable-dev\Node /E /I /Y
xcopy C:\temp\python-portable\* C:\portable-dev\Python /E /I /Y

# Copy ehelp source
xcopy C:\ehelp\frontend C:\portable-dev\ehelp\frontend /E /I /Y
xcopy C:\ehelp\backend C:\portable-dev\ehelp\backend /E /I /Y
```

### Step 2: Create START.bat

```batch
@echo off
cd /d "%~dp0"
title eHelp Development Environment
echo.
echo eHelp Development Setup
echo =======================
echo.
echo Starting backend server...
start cmd /k "cd ehelp\backend && ..\..\..\Python\python.exe -m uvicorn ehelp.app:app --host 0.0.0.0 --port 8123 --reload"

echo.
echo Starting frontend dev server...
start cmd /k "cd ehelp\frontend && ..\..\..\Node\npm.cmd run dev"

echo.
echo Application will be available at http://localhost:8123
echo.
pause
```

### Step 3: Compress

```bash
# Using 7-Zip (recommended, best compression)
7z a -tzip windows-dev-portable.zip C:\portable-dev\*

# Or using PowerShell
Compress-Archive -Path C:\portable-dev -DestinationPath windows-dev-portable.zip -Force

# Result: ~400-500 MB
```

---

## Part 4: Create windows-deploy-portable.zip

### Structure

```
windows-deploy-portable/
├── Node/                          # Portable Node.js (optional for deploy)
├── Python/                        # Portable Python
│   ├── python.exe
│   ├── python.dll
│   ├── Lib/
│   └── Scripts/
├── ehelp/
│   ├── backend/                   # Pre-built, optimized
│   │   ├── venv/
│   │   └── ehelp/
│   ├── frontend/static/           # Pre-built Vite output
│   │   ├── index.html
│   │   ├── assets/
│   │   └── ...
│   ├── data/
│   ├── config.yaml                # Production config template
│   └── run-service.bat            # Windows Service installer
│   └── install-service.bat        # Setup script
├── docs/
│   ├── WINDOWS_DEPLOY_SETUP.md
│   └── TROUBLESHOOTING.md
└── README-DEPLOY.txt
```

### Step 1: Pre-build Frontend

```bash
cd C:\ehelp\frontend

# Build for production
npm run build

# Output: dist/ folder (10-20 MB)
# This is what goes in the zip
```

### Step 2: Build Backend

```bash
cd C:\ehelp\backend

# Activate venv (already created)
.\venv\Scripts\activate

# Install production dependencies
pip install -r requirements-prod.txt

# Or if using regular requirements.txt with minimal deps:
pip install fastapi uvicorn python-multipart

deactivate
```

### Step 3: Organize Deployment Package

```bash
mkdir C:\portable-deploy
mkdir C:\portable-deploy\Python
mkdir C:\portable-deploy\ehelp

# Copy Python
xcopy C:\temp\python-portable\* C:\portable-deploy\Python /E /I /Y

# Copy backend (venv included)
xcopy C:\ehelp\backend C:\portable-deploy\ehelp\backend /E /I /Y

# Copy frontend build output
mkdir C:\portable-deploy\ehelp\frontend
xcopy C:\ehelp\frontend\dist C:\portable-deploy\ehelp\frontend\dist /E /I /Y

# Copy data directory
mkdir C:\portable-deploy\ehelp\data

# Copy configs
copy C:\ehelp\config.yaml C:\portable-deploy\ehelp\
```

### Step 4: Create Installation Scripts

**install-service.bat:**
```batch
@echo off
setlocal enabledelayedexpansion

REM Run as Administrator check
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: This script must run as Administrator
    pause
    exit /b 1
)

cd /d "%~dp0"
set INSTALL_DIR=%cd%\ehelp
set PYTHON_EXE=%cd%\Python\python.exe

echo Installing eHelp as Windows Service...
echo Installation Directory: %INSTALL_DIR%
echo.

REM Create Windows Service
sc create eHelp binPath= "%PYTHON_EXE% -m uvicorn ehelp.app:app --host 0.0.0.0 --port 8123" start= auto

REM Set description
sc description eHelp "eHelp - Document Intelligence Platform"

REM Set working directory and other params
reg add "HKLM\SYSTEM\CurrentControlSet\Services\eHelp" /v ImagePath /t REG_EXPAND_SZ /d "\"%PYTHON_EXE%\" -m uvicorn ehelp.app:app --host 0.0.0.0 --port 8123" /f

echo Service installed successfully!
echo.
echo To start the service:
echo   net start eHelp
echo.
echo To stop the service:
echo   net stop eHelp
echo.
echo To remove the service:
echo   sc delete eHelp
echo.
pause
```

**run-service.bat:**
```batch
@echo off
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Run as Administrator
    pause
    exit /b 1
)

cd /d "%~dp0"
set PYTHON_EXE=%cd%\Python\python.exe
cd ehelp\backend

echo Starting eHelp server...
echo Access at: http://localhost:8123
echo.

%PYTHON_EXE% -m uvicorn ehelp.app:app --host 0.0.0.0 --port 8123 --workers 4

pause
```

### Step 5: Compress

```bash
# Using 7-Zip
7z a -tzip windows-deploy-portable.zip C:\portable-deploy\*

# Result: ~300-400 MB
```

---

## Part 5: Automate with build-artifacts.sh

The `build-artifacts.sh` script already automates this. To use it:

```bash
# On Windows (Git Bash or WSL):
cd /path/to/ehelp

# Run build script
./build-artifacts.sh

# Output in dist/:
# - ehelp-docker.tar.gz
# - windows-dev-portable.zip
# - windows-deploy-portable.zip
```

**Update build-artifacts.sh** to build Windows packages:

```bash
#!/bin/bash
set -e

echo "🏗️  Building eHelp Artifacts..."

# Frontend build
echo "📦 Building frontend..."
cd frontend
npm run build
cd ..

# Windows dev package
echo "📦 Packaging Windows dev portable..."
mkdir -p dist
# Script would call Python to create the zip programmatically
# Or use 7z if available

# Windows deploy package
echo "📦 Packaging Windows deploy portable..."
# Similar to above

# Docker image
echo "🐳 Building Docker image..."
docker build -f Dockerfile.rhel -t ehelp:latest .
docker save ehelp:latest | gzip > dist/ehelp-docker.tar.gz

echo "✅ All artifacts created in dist/"
ls -lh dist/
```

---

## Checklist: Before Publishing

- [ ] Node.js portable runs: `node --version`
- [ ] Python portable runs: `python --version`
- [ ] pip works: `pip --version`
- [ ] uv works: `uv --version`
- [ ] Frontend builds: `npm run build`
- [ ] Backend tests pass: `pytest`
- [ ] START.bat launches both servers
- [ ] Application accessible at http://localhost:8123
- [ ] Zip size reasonable (<1 GB for dev, <600 MB for deploy)
- [ ] No internet connection required after extraction

---

## Troubleshooting

### "npm: command not found"
- Node not in PATH
- **Solution**: Use full path `.\Node\npm.cmd install`

### "pip not recognized"
- Python portable missing pip
- **Solution**: Re-run `python -m pip install --upgrade pip`

### Large zip size
- node_modules or venv too large
- **Solution**: Use `.gitignore` to exclude during packaging

### Activation issues
- Venv paths hardcoded
- **Solution**: Use `python -m venv` to create fresh venv on first run

---

## Alternative: Pre-built Executables

For fully offline deployment without Python/Node runtime:

1. **Frontend**: Use Electron to package as standalone .exe
2. **Backend**: Use PyInstaller to compile Python + FastAPI to .exe
3. Result: Single .exe file (~150-200 MB)

See `WINDOWS_DEPLOY_SETUP.md` for PyInstaller approach.

---

**Next**: After creating packages, test them in a clean Windows VM without internet to verify portability.
