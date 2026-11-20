# eHelp - Offline Windows Development Setup

## Prerequisites
- **Minimum**: 4 GB RAM, 2 GB disk space
- **Recommended**: 8 GB RAM, 5 GB disk space
- Windows 10 or later

## Package Contents
- `node-v22.23.4-win-x64` (portable Node.js)
- `python-3.11.9-embed-amd64` (portable Python)
- `uv-latest-windows` (UV package manager)
- `ehelp-dev-bundle.zip` (source + dependencies)

## Setup Steps

### 1. Extract the Archive
```batch
cd C:\ehelp-dev
# Extract: windows-dev-portable.zip
```

### 2. Run Setup Script
```batch
cd C:\ehelp-dev
setup-dev.bat
```

This will:
- Verify Node.js and Python installations
- Install dependencies (npm, uv)
- Build frontend (Vite)
- Seed backend database

### 3. Start Development Server
```batch
cd C:\ehelp-dev\backend
run-dev.bat
```

The app will start on `http://localhost:8123`

### 4. Frontend Development (Optional Hot Reload)
In a new terminal:
```batch
cd C:\ehelp-dev\frontend
npm run dev
# Vite runs on http://localhost:5173
# Proxy configured to http://localhost:8123
```

## Troubleshooting

### "Python not found"
- Ensure `python-3.11.9-embed-amd64\python.exe` exists
- Run: `C:\ehelp-dev\python-3.11.9-embed-amd64\python.exe --version`

### "npm command not found"
- Ensure `node-v22.23.4-win-x64\npm.cmd` exists
- Add to PATH: `C:\ehelp-dev\node-v22.23.4-win-x64`

### Port 8123 Already in Use
- Change in `backend/ehelp/config.py`: `PORT=8124`
- Or kill process: `netstat -ano | findstr :8123` → `taskkill /PID <PID> /F`

## Project Structure
```
C:\ehelp-dev\
├── backend/           # FastAPI + SQLite
├── frontend/          # React + Vite
├── node-v22.23.4/
├── python-3.11.9/
├── uv-latest/
├── setup-dev.bat
└── run-dev.bat
```

## First Run After Setup
1. Navigate to `http://localhost:8123`
2. Click **Admin** (top right)
3. Upload a document (PDF, DOCX, XLSX, etc.)
4. Assign a category
5. Click **Search** to test global search

## Stop Development Server
- In the terminal: `Ctrl + C`
- Or: `taskkill /IM python.exe /F`

## Notes
- Database stored in `%APPDATA%\ehelp\data` (persistent)
- Frontend build cached in `frontend\node_modules` and `frontend\dist`
- No internet required after initial setup (all packages bundled)
