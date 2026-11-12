# OpsIntel Windows Setup Guide

This guide sets up OpsIntel natively on Windows 10/11. WSL and Docker are not required. Run the backend, worker, and frontend from their specified folders; the backend reads `.env` relative to its working directory.

## 1. Required software

| Software | Version / purpose |
| --- | --- |
| Windows | Windows 10 or 11, 64-bit |
| Git for Windows | Required for Gitea mirrors and repository sync |
| Python | 3.12 or 3.13, 64-bit; the project requires `>=3.12,<3.14` |
| uv | Creates the virtual environment and installs the locked Python dependencies |
| Node.js and npm | Node.js `>=22.12`; npm is included and builds the React/Vite frontend |

Install from an elevated or regular PowerShell terminal, according to your organization's software policy:

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
```

Install uv with its official PowerShell installer:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell after installation, then verify the tools:

```powershell
git --version
py -3.12 --version
uv --version
node --version
npm --version
```

Node must report `v22.12.0` or newer. If `py -3.12` is unavailable, install Python 3.12 from python.org and enable the Python launcher during setup.

## 2. Optional software by feature

| Software | Needed when |
| --- | --- |
| Ollama for Windows | Needed for local AI answers. Lexical/exact search works without it. |
| An Ollama chat model | Needed for AI answers. Set `OLLAMA_CHAT_MODEL` to an installed tag. |
| An Ollama embedding model | Needed only for semantic/hybrid retrieval; set `OLLAMA_EMBED_MODEL` and enable semantic search. |
| Tesseract OCR with English data | Needed for OCR of scanned PDFs. Text-based PDFs do not need OCR. |
| LibreOffice | Needed for legacy `.doc` and `.ppt` extraction. DOCX, PPTX, PDF, and spreadsheet parsers do not require it. |
| Gitea server and read-capable token | Needed to register, clone, and sync Gitea repositories. Local-folder indexing does not need Gitea. |

Install Ollama from the official Windows installer at `https://ollama.com/download/windows`. Start Ollama and check its installed models:

```powershell
ollama --version
ollama list
```

Do not assume the development model alias exists on Windows. Set `OLLAMA_CHAT_MODEL` to the exact tag shown by `ollama list`. If an approved model is not installed and network policy permits downloading it, install it explicitly, for example:

```powershell
ollama pull <approved-chat-model-tag>
```

For optional semantic search, install an approved embedding model separately (for example `nomic-embed-text`) and configure its exact tag. OpsIntel does not download models automatically. Keep chat and embedding models separate.

For OCR, install Tesseract with the English language data. A common Windows distribution is documented at `https://github.com/UB-Mannheim/tesseract/wiki`. For legacy Office formats, install LibreOffice from `https://www.libreoffice.org/download/download-libreoffice/`.

## 3. Install project dependencies

Open PowerShell in the repository root, then install the backend dependencies from the lock file:

```powershell
Set-Location C:\path\to\OpsIntel\backend
uv sync --locked
```

This creates `backend\.venv` and installs the runtime and development Python dependencies declared in `pyproject.toml`/`uv.lock`, including FastAPI, Uvicorn, SQLite support, document/spreadsheet parsers, and tests/lint tools.

Install the frontend dependencies from the npm lock file:

```powershell
Set-Location C:\path\to\OpsIntel\frontend
npm ci
```

No separate global React, Vite, or Python parser installs are required.

## 4. Configure the backend

Create a private local configuration file and edit it:

```powershell
Set-Location C:\path\to\OpsIntel\backend
Copy-Item .env.example .env
notepad .env
```

Keep `.env` private and do not commit it. The most important settings are:

```dotenv
# Keep the persistent index outside the source checkout if desired.
OPSINTEL_DATA_DIR=C:/OpsIntel/data
API_HOST=127.0.0.1
API_PORT=8000

# Gitea: omit/use an empty token only for public repositories.
GITEA_URL=http://gitea.internal:3000
GITEA_TOKEN=replace-with-a-read-capable-token
# Optional if the browser reaches Gitea at a different URL or under a path prefix.
# GITEA_WEB_URL=https://gitea.example.internal/gitea

# Required only for local-folder indexing from the admin UI.
LOCAL_REPO_ALLOWED_ROOTS=["C:/OpsIntel/repos"]

# Optional local AI. Use tags shown by `ollama list`.
AI_ENABLED=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=your-installed-chat-model
AI_DAILY_REQUEST_LIMIT=20

# Optional semantic search; requires an installed embedding model.
SEMANTIC_SEARCH_ENABLED=false
# OLLAMA_EMBED_MODEL=nomic-embed-text

# Optional scanned-PDF OCR.
OCR_ENABLED=false
# TESSERACT_PATH=C:/Program Files/Tesseract-OCR/tesseract.exe

# Needed only for legacy DOC/PPT files.
# LIBREOFFICE_PATH=C:/Program Files/LibreOffice/program/soffice.exe
```

Use forward slashes in Windows paths in `.env`. `LOCAL_REPO_ALLOWED_ROOTS` is a JSON array of trusted parent directories; the admin UI will only index local folders under one of these roots. Restart the API after changing `.env`.

`GITEA_URL` is the Gitea server root, not its `/api/v1` URL. OpsIntel appends `/api/v1` for API calls. A trailing slash is okay. The token must be allowed to read the repositories you register. Never put the token in a browser-facing URL.

## 5. Start and verify the backend

Open two PowerShell windows. In both, set the working directory to `backend` so `.env` is loaded.

Terminal 1, start the index worker:

```powershell
Set-Location C:\path\to\OpsIntel\backend
uv run opsintel worker
```

Terminal 2, check configuration and start the API on loopback:

```powershell
Set-Location C:\path\to\OpsIntel\backend
uv run opsintel doctor
uv run opsintel serve --host 127.0.0.1 --port 8000
```

The API is intentionally loopback-only until remote access has been properly secured. Do not bind it to `0.0.0.0` or expose it through a network proxy.

`opsintel doctor` checks the local environment, Gitea connectivity (when configured), Ollama, Git, Tesseract settings, and memory. Warnings for optional tools are expected when their corresponding features are disabled.

## 6. Start the frontend

For development, open a third PowerShell window:

```powershell
Set-Location C:\path\to\OpsIntel\frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` requests to `http://127.0.0.1:8000`.

For a production-style local run, build the frontend instead:

```powershell
Set-Location C:\path\to\OpsIntel\frontend
npm run build
```

The build is written to `backend\opsintel\static`. Then run the API as above and open `http://127.0.0.1:8000`.

## 7. First login and repository setup

1. Open the app and create the first administrator account. Use a unique password of at least 12 characters.
2. In **Administration**, register a Gitea repository with its `owner/repo` name. The API checks it with the configured Gitea token and queues an initial sync.
3. For a local checkout, first add its parent folder to `LOCAL_REPO_ALLOWED_ROOTS`, restart the API, then enter the checkout path under **Add local checkout**.
4. Indexing runs in the worker window. The admin repository row shows indexed coverage and live progress while work is active.
5. Create additional local accounts and grant access to repositories using the searchable repository selector.

You can also verify Gitea access from the backend directory:

```powershell
uv run opsintel gitea list
uv run opsintel repos
uv run opsintel jobs status
```

## 8. Common setup issues

- **`GITEA_URL is not configured`:** start `opsintel serve` and `opsintel worker` with `backend` as the current directory, and confirm `backend\.env` contains `GITEA_URL`.
- **Gitea `401`/`403`:** confirm the token is valid and can read the target repository through both the Gitea API and Git HTTP. Do not paste the token into logs or issue reports.
- **Local path rejected:** add a trusted parent directory to `LOCAL_REPO_ALLOWED_ROOTS`, restart the API, and make sure the selected folder is beneath that parent.
- **AI unavailable:** check that Ollama is running, `OLLAMA_BASE_URL` is reachable, and `OLLAMA_CHAT_MODEL` exactly matches an installed `ollama list` tag. AI can be disabled while search remains available.
- **Semantic search disabled:** install/configure the separate embedding model, then set `SEMANTIC_SEARCH_ENABLED=true` and `OLLAMA_EMBED_MODEL`.
- **Scanned PDFs are not searchable:** install Tesseract with English data, set `TESSERACT_PATH` if it is not on `PATH`, set `OCR_ENABLED=true`, then reindex the repository.
- **Legacy DOC/PPT files are unsupported:** install LibreOffice and set `LIBREOFFICE_PATH`, then reindex those files.
- **Worker pauses:** it is protecting memory according to `WORKER_MIN_FREE_RAM_MB`. Close memory-heavy programs or adjust the setting cautiously; Ollama and indexing share system memory.
- **Port already in use:** choose another port for the API and update Vite's `/api` proxy in `frontend/vite.config.js` to match.

## 9. Back up the index

The SQLite database, Git mirrors, and parser caches live under `OPSINTEL_DATA_DIR` (default: `backend\data`). For a simple consistent backup, stop both the API and worker, copy that directory to protected storage, then restart them. The directory can contain indexed private repository content and must be protected accordingly.
