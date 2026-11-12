# OpsIntel

OpsIntel is an offline-first search and knowledge workspace for local folders and Gitea repositories. It indexes source code, configuration, documents, spreadsheets, and operational files into a local SQLite/FTS5 index, with source locations preserved for result previews. Optional local Ollama models provide semantic retrieval and AI answers; lexical and exact search do not depend on AI.

## Features

- Incremental indexing and persistent background sync jobs.
- Smart, exact-substring, and phrase search, with repository/file filters and source previews.
- Gitea result links pinned to the indexed commit when available.
- PDF, DOCX, PPTX, spreadsheet, delimited, source-code, text, and structured-file parsing. Legacy DOC/PPT conversion and scanned-PDF OCR are optional.
- Local accounts, administrator-managed repository access, AI access/daily limits, and repository administration.
- Optional semantic search and AI question answering through local Ollama.

## Requirements

- Python 3.12 or 3.13 (the backend requires `>=3.12,<3.14`).
- `uv` for the backend environment.
- Node.js 22.12+ and npm for frontend development/builds.
- Git for Gitea mirror/sync operations.
- Ollama, Tesseract, and LibreOffice only when using their corresponding optional features.

## Development Setup

Create a private backend configuration and install dependencies:

```powershell
Set-Location backend
Copy-Item .env.example .env
uv sync --locked
```

Edit `backend/.env` for your environment. Keep it private; do not commit credentials or local data. The API and worker must run with `backend` as their working directory so the backend `.env` is loaded.

Start the worker and API in separate terminals:

```powershell
Set-Location backend
uv run opsintel worker
```

```powershell
Set-Location backend
uv run opsintel doctor
uv run opsintel serve --host 127.0.0.1 --port 8000
```

For frontend development, start Vite in another terminal:

```powershell
Set-Location frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. Vite proxies API requests to `http://127.0.0.1:8000`. For the bundled UI, build it with `npm run build` from `frontend`, then open `http://127.0.0.1:8000`.

The first visit creates the initial administrator account. The application is loopback-only; do not expose it on a network interface.

## Repository Administration

In **Administration**, an admin can register and sync a Gitea repository using its `owner/repo` name, sync an existing repository, disable it, or remove its OpsIntel index/mirror. Removing an index does not delete the source repository in Gitea.

To add a local checkout through the UI, configure `LOCAL_REPO_ALLOWED_ROOTS` in `backend/.env` with trusted parent directories and restart the API. Local folders outside those roots are rejected.

For Gitea, set `GITEA_URL` to the server root (OpsIntel appends `/api/v1`) and provision `GITEA_TOKEN` locally. If the browser uses a different address or path prefix, set `GITEA_WEB_URL`. Never put tokens in browser URLs or commit them.

## Optional Local AI

Ollama is optional. Set `AI_ENABLED=false` to turn off AI while retaining search. To enable AI, run Ollama locally, install the desired chat model, and set `OLLAMA_BASE_URL` and `OLLAMA_CHAT_MODEL` to the installed values. Semantic search additionally requires an installed embedding model plus `SEMANTIC_SEARCH_ENABLED=true` and `OLLAMA_EMBED_MODEL`.

The admin can enable/disable AI per account and set a per-user daily request limit. A limit of `0` inherits `AI_DAILY_REQUEST_LIMIT` from the backend configuration. Models are not downloaded automatically.

## Tests and Build

```powershell
Set-Location backend
uv run ruff check opsintel tests
uv run pytest -q
```

```powershell
Set-Location frontend
npm ci
npm run build
```

## Windows Guides

- [Windows development/setup guide](docs/windows-setup.md)
- [Offline Windows staging and deployment guide](docs/windows-offline-deployment.md)

The offline guide describes building a Windows-compatible wheelhouse and transferring approved installers/models. Those binaries and model weights are not stored in this repository.

## Local Data and Security

The default database and Git mirrors are under `backend/data` (or `OPSINTEL_DATA_DIR`). That directory may contain indexed private repository content; back it up and protect it accordingly. `.env`, local databases, model weights, caches, virtual environments, and generated frontend assets are excluded from Git.
