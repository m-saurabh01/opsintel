# OpsIntel — Implementation Plan

Derived from [plan.md](plan.md). Target: a Windows 11–compatible, offline-first Gitea search and knowledge platform. It runs natively (no Docker) with FastAPI on Uvicorn, a React frontend and a local Ollama instance. Development begins on the current macOS machine and must continue on Windows PCs without code changes.

---

## 1. Environment Findings and Deviations From plan.md

### 1.1 Current dev machine (inspected 2026-10-28)

| Item | Found | Impact |
|---|---|---|
| OS | macOS (Apple Silicon M1, arm64) | Dev only; Windows 11 x64 is the production target |
| RAM | **8 GB** | Cannot run a ~9B model alongside indexing. Use a small dev model (see 1.3) |
| Disk free | 252 GB | Sufficient |
| Python | 3.12.8 at `/usr/local/bin/python3.12` (3.14.2 is the default `python3`) | Create the venv explicitly with 3.12: `uv venv --python 3.12` |
| Node | 18.20.8 (EOL) | **Upgrade to Node 22 LTS.** Current Vite needs Node ≥ 20.19 |
| Docker | Not installed | Matches the new direction: native Uvicorn, no containers for now |
| Ollama | Client 0.9.6 installed, **server not running** ("could not find ollama app"), `~/.ollama/models` is empty | Run `ollama serve` (CLI) or reinstall the Ollama app |
| Dev model | `./model/`: Phi-3-mini-4k-instruct (2.4 GB), Mistral-7B-Instruct v0.1 (4.4 GB), Llama-3.2-3B base (1.9 GB) | **Phi-3-mini is the primary dev model.** Mistral 7B is optional (see 1.3) |
| Git CLI | 2.43.0 | OK |
| uv | Installed (`~/.local/bin/uv`) | Use it for Python 3.12 and the venv |
| Gitea | Not installed | A local test Gitea will be set up under `devtools/gitea/` (M2) |

### 1.2 Deviations from plan.md (approved by the new direction)

- **Deployment:** use native processes started by Uvicorn plus a separate worker process, instead of Docker Compose. Containerization is deferred, but the code stays container-friendly: configuration comes from environment variables and all data lives under one data directory.
- **Target OS:** Windows 11 is first-class. Every code path must also run on macOS and Linux for development.

### 1.3 Ollama and models

**Target (Windows):** Ollama **0.10.0**. It supports everything the design needs: `/api/chat` streaming, `/api/embed`, `/api/tags`, `/api/ps`, `/api/version`, `keep_alive` and `options.num_ctx`. No legacy fallbacks are needed. The client checks `/api/version` (minimum 0.10.0) and `/api/tags` (configured model present) at startup, and reports a clear status if either check fails.

**Dev models (this Mac, all in `./model/`, inspected via GGUF metadata):**

| File | Size | Type | Context | Use |
|---|---|---|---|---|
| `Phi-3-mini-4k-instruct-q4.gguf` | 2.4 GB | Instruct, embedded chat template | 4k | **Primary dev model:** `opsintel-dev` |
| `mistral-7b-instruct-v0.1.Q4_K_M.gguf` | 4.4 GB | Instruct (no system role) | 32k (run at 4k) | Optional 7B check: `opsintel-dev-7b`. Tight on 8 GB, so close other apps |
| `Llama-3.2-3B.Q4_K_M.gguf` | 1.9 GB | **Base**, no chat template | 128k | Not used; it does not follow instructions |

Why Phi-3-mini: it is instruction-tuned, small enough to run alongside the API, worker and Gitea on 8 GB, and good at following rules like "cite only evidence IDs". Its 4k context matches `AI_NUM_CTX=4096`. Mistral 7B is a closer proxy for the Windows model size, for occasional answer-quality checks.

```text
ollama serve                                                    # separate terminal
ollama create opsintel-dev    -f devtools/ollama/Modelfile.dev      # Phi-3-mini
ollama create opsintel-dev-7b -f devtools/ollama/Modelfile.mistral  # optional
```
The Modelfiles in [devtools/ollama/](devtools/ollama/) set each model's chat template and stop tokens, `num_ctx 4096` and `temperature 0.2`.

`.env`: `OLLAMA_CHAT_MODEL=opsintel-dev`, `AI_NUM_CTX=4096`. The retrieval token budget is derived from `AI_NUM_CTX`, so the dev and Windows configurations use the same code.

- `model/` is added to `.gitignore`. Model files are never committed.
- The Windows chat model is configured separately through `OLLAMA_CHAT_MODEL`. AI answer quality and resource profiling (M6/M8) must be validated on Windows with that model, not with the dev models.

**Embedding model:** none is installed. Semantic search (M7) stays disabled until an embedding model is provisioned and approved (for example `nomic-embed-text` or `all-minilm` via Ollama). This avoids PyTorch on Windows.

---

## 2. Key Technical Decisions

| Concern | Decision | Rationale |
|---|---|---|
| API server | FastAPI + Uvicorn (`--workers 1`), no `uvloop` | uvloop does not support Windows. Use the default asyncio loop |
| Background work | Separate process: `python -m opsintel.worker` | Keeps indexing CPU and RAM away from the API. Both Windows and macOS spawn it the same way |
| Job queue | **SQLite-backed persistent queue** (own table, `BEGIN IMMEDIATE` leasing) | Redis and Celery are not native on Windows and are unjustified for a single host |
| Metadata + FTS | **SQLite (WAL mode) + FTS5** | Zero install, cross-platform, and FTS5 ships with Python's sqlite3. Benchmark before considering OpenSearch |
| Vector store (optional) | Start with float32 BLOBs plus NumPy brute force per repo filter. Evaluate `sqlite-vec` if more than ~1M chunks | No extra service needed |
| Repo sync | `git` CLI mirror clones (`git fetch` + `git diff --name-status -M <old>..<new>`). Use the Gitea REST API for discovery, permissions and webhooks | Exact add/modify/rename/delete detection with rename support |
| Process I/O | `subprocess.run([...], shell=False)` with argument lists only | Safe and portable. No shell-specific syntax |
| Paths | `pathlib` everywhere. Store **POSIX-style relative paths** in the database | Same database is meaningful across operating systems. Guards against traversal |
| Line endings | Count lines on `\n` after universal-newline decode. Add `.gitattributes` to the repo | CRLF must not shift line numbers |
| Config | `pydantic-settings` + `.env` | Same mechanism on every OS |
| Resource monitoring | `psutil` | Cross-platform RSS, CPU and available RAM |
| Ollama client | `httpx` async calls to `OLLAMA_BASE_URL` (`/api/chat`, `/api/embed`, `/api/tags`, `/api/ps`) | No SDK lock-in. Supports timeouts and cancellation |
| Legacy DOC/XLS | XLS: `xlrd`. DOC: **LibreOffice headless** (`soffice --convert-to docx`) if configured, otherwise record as unsupported | antiword and catdoc are not readily available on Windows |
| OCR (optional) | Tesseract via `pytesseract`, with a configurable path to `tesseract.exe` | Available on both operating systems. Off by default |
| Frontend | React + Vite (JavaScript, ES2020+), built to static files and served by FastAPI | One port in production, no Node.js at runtime, no CDNs |
| Python tooling | `uv` (or `pip` + `venv`) with a lockfile | Reproducible, fast, and supports offline wheelhouse installs |
| Task runner | `python -m opsintel.cli <cmd>` (Typer) instead of Makefile or bash | Identical commands on Windows PowerShell and macOS zsh |

### Cross-platform rules (enforced in code review and CI)

- No `fcntl`, `os.fork`, signals other than SIGINT/SIGTERM, or `/tmp` literals. Use `tempfile`.
- Multiprocessing must use the `spawn` start method explicitly, which is the Windows default.
- Open text files with an explicit `encoding=`. Detect encodings with `charset-normalizer`.
- Handle Windows file locking: close handles before replace or delete, and use `os.replace` for atomic swaps.
- Long paths: document enabling `LongPathsEnabled` and set `git config core.longpaths true` on mirror clones.
- Case-insensitive filesystems: treat case-only renames from `git diff` as renames.
- CI matrix: `windows-latest` + `macos-latest` running the full test suite.

---

## 3. Resource Budgets (initial; validate by benchmark)

| Component | Windows target (≈50 GB) | Mac dev (8 GB) |
|---|---|---|
| OS + headroom (reserved) | 8 GB | 3 GB |
| Ollama chat model (7B Q4 + 8k ctx) | ~6–8 GB | ~1.5–3 GB (1.5B/3B model) |
| Ollama embedding model | ~0.5 GB | ~0.5 GB |
| API process (Uvicorn) | ≤ 1.5 GB | ≤ 0.5 GB |
| Worker process (parsers) | ≤ 4 GB, 4 extraction workers | ≤ 1 GB, 1 worker |
| SQLite page cache | 512 MB | 128 MB |
| In-memory caches (total) | ≤ 512 MB | ≤ 128 MB |
| AI concurrency | 1 | 1 |
| Throttle indexing when available RAM < | 6 GB | 1.5 GB |

All values are `.env` settings. The worker checks `psutil.virtual_memory().available` before leasing each job and pauses when it falls below the threshold.

---

## 4. Repository Structure

```
OpsIntel/
├─ backend/
│  ├─ pyproject.toml            # Python 3.12, deps, ruff, pytest config
│  ├─ opsintel/
│  │  ├─ main.py                # FastAPI app factory; mounts static frontend
│  │  ├─ config.py              # pydantic-settings
│  │  ├─ cli.py                 # serve | worker | migrate | sync | reindex | bench | doctor
│  │  ├─ db/                    # connection mgmt, migrations (plain SQL files), repositories
│  │  ├─ gitea/                 # REST client, webhook verification, permission fetch
│  │  ├─ sync/                  # git mirror mgmt, diff → change set
│  │  ├─ discovery/             # file type detection, exclusions, size limits
│  │  ├─ parsers/               # base.py (contract) + one module per format
│  │  ├─ indexing/              # chunk writer, atomic replace, FTS maintenance
│  │  ├─ jobs/                  # SQLite queue, leasing, retry/backoff, dead-letter
│  │  ├─ worker/                # worker loop, resource governor
│  │  ├─ search/                # FTS query builder, filters, snippets, ranking
│  │  ├─ semantic/              # embeddings via Ollama, vector search, RRF fusion
│  │  ├─ ai/                    # retrieval, prompt building, citation validation, admission
│  │  ├─ cache/                 # bounded LRU/TTL, single-flight
│  │  ├─ auth/                  # sessions, Gitea-backed identity, permission scope
│  │  ├─ admin/                 # metrics, controls, audit log
│  │  └─ api/                   # routers: search, files, ai, admin, webhooks, health
│  └─ tests/
│     ├─ fixtures/              # sample files for every format (incl. malformed)
│     ├─ unit/  integration/  load/
├─ frontend/
│  ├─ package.json  vite.config.js
│  └─ src/  (pages: Search, Viewer, Ask, Admin)
├─ scripts/
│  ├─ dev.ps1  dev.sh           # thin wrappers that call opsintel.cli
├─ devtools/
│  ├─ gitea/                    # pinned binary + app.ini + data/ (git-ignored)
│  └─ ollama/Modelfile.dev      # imports the local Phi-3 GGUF
├─ docs/                        # architecture, API, ops, provisioning (deliverables)
├─ .env.example
├─ .gitattributes               # * text=auto eol=lf for source
└─ plan.md  IMPLEMENTATION_PLAN.md
```

Runtime data lives in a single directory, `OPSINTEL_DATA_DIR` (default `./data`; on Windows prod, for example, `D:\OpsIntel\data`):
`opsintel.db`, `mirrors/<repo_id>.git`, `cache/`, `logs/`.

---

## 5. Data Model (core tables)

```sql
repositories(id, gitea_id, owner, name, default_branch, clone_url, is_private, enabled,
             last_synced_sha, last_synced_at, sync_status)
branches(id, repo_id, name, head_sha, indexed_sha, indexed_at)
files(id, repo_id, branch_id, path_posix, content_hash, size, file_type, parser_name,
      parser_version, parse_options_hash, status, error, commit_sha, indexed_at,
      UNIQUE(branch_id, path_posix))
chunks(id, file_id, ordinal, text, text_hash,
       coord_kind,            -- line | page | cell | row | section | jsonpath
       start_line, end_line, page, sheet, cell_ref, row_num, section_path, key_path,
       bbox_json, extra_json)
chunks_fts                    -- FTS5(text, path, content='chunks', tokenize='unicode61 remove_diacritics 2' + trigram table for identifiers)
embeddings(chunk_id, model_id, text_hash, dim, vector BLOB, PRIMARY KEY(chunk_id, model_id))
parse_cache(content_hash, parser_name, parser_version, options_hash, payload BLOB, created_at)
jobs(id, queue, dedupe_key UNIQUE, payload_json, status, priority, attempts, max_attempts,
     run_after, leased_until, worker_id, last_error, created_at, started_at, finished_at)
webhook_deliveries(delivery_id PRIMARY KEY, repo_id, received_at, processed)
users(id, username UNIQUE, auth_source,          -- local | gitea_oauth
      password_hash NULL, gitea_username NULL, is_admin, is_active,
      failed_logins, locked_until, created_at, last_login_at)
sessions(id_hash PRIMARY KEY, user_id, csrf_token, created_at, last_seen_at, expires_at)
user_repo_grants(user_id, repo_id)               -- explicit grants for unlinked local users
user_repo_access(user_id, repo_id, refreshed_at) -- resolved effective access (cache)
ai_cache(key PRIMARY KEY, answer_json, evidence_versions_json, created_at, expires_at)
audit_log(id, user_id, action, target, details_json, at)
settings(key PRIMARY KEY, value_json)          -- runtime-adjustable limits
```

**Atomic file reindex:** in one transaction, delete the old chunks and FTS rows for `file_id`, insert the new chunks, then update `files.content_hash/status`. Readers never see a partial file.

**Idempotency:** the job `dedupe_key = queue:repo:branch:path:content_hash`. Webhook `delivery_id` values are stored, so repeated deliveries are no-ops.

---

## 6. Parser Contract

```python
@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    coord: Coord          # kind + format-specific fields; never inferred later
    extra: dict

class Parser(Protocol):
    name: str
    version: str          # bump → triggers targeted reindex
    def supports(self, path: PurePosixPath, head: bytes) -> bool: ...
    def parse(self, src: BinaryIO, ctx: ParseContext) -> Iterator[Chunk]: ...   # streaming
```

| Format | Library | Coordinates |
|---|---|---|
| Code / text / logs / SQL / JSP / shell | built-in (+ `charset-normalizer`) | line range, ~40-line windows with overlap |
| JSON / YAML / XML / TOML / INI / properties | `json`, `ruamel.yaml`, `lxml`, `tomllib`, `configparser` | line + key path |
| Markdown / RST / HTML | built-in / `lxml` | line + heading path |
| PDF | `PyMuPDF` | page (+ bbox); scanned detection → OCR job |
| DOCX | `python-docx` | heading path + paragraph / table index |
| DOC | LibreOffice headless → DOCX parser | same as DOCX, flagged as converted |
| XLSX | `openpyxl` (read_only, two passes: values + formulas) | sheet + cell + row context |
| XLS | `xlrd` | sheet + cell |
| ODS | `odfpy` / `pandas-odf`, evaluate | sheet + cell |
| CSV / TSV | `csv` (streaming, sniffed dialect) | row number + header names |

Every parser runs under a wall-clock timeout and a maximum size. Failures are recorded on `files.status/error`, never skipped silently.

---

## 7. API Surface (v1)

| Method & Path | Purpose |
|---|---|
| `GET /api/health` | API, database, worker heartbeat and Ollama status |
| `POST /api/auth/login` ; `POST /api/auth/logout` ; `GET /api/auth/me` | Internal ID and password login |
| `GET /api/auth/gitea/start` ; `GET /api/auth/gitea/callback` | Gitea OAuth2 login |
| `GET /api/search?q=&mode=exact|phrase|fulltext|semantic|hybrid&repo=&branch=&type=&page=` | Search with highlighted snippets and coordinates |
| `GET /api/files/{file_id}` | File metadata |
| `GET /api/files/{file_id}/content?around=` | Source viewer payload (line range, PDF page, sheet window, CSV rows) |
| `GET /api/files/{file_id}/raw` | Original bytes (permission-checked) for the PDF viewer |
| `POST /api/ai/ask` → `{job_id}` ; `GET /api/ai/ask/{job_id}` (SSE stream) ; `DELETE` to cancel | Question answering with citations. Returns 429/503 when busy |
| `POST /api/webhooks/gitea` | HMAC-verified push events |
| `GET/POST /api/admin/...` | repos, sync, pause/resume, retry, reindex, settings, metrics, audit, diagnostics |

The full OpenAPI specification is generated by FastAPI. Examples go in `docs/api.md`.

---

## 8. Milestones

**Updated execution order (2026-10-29): M6 → M7 → M8 → M5.** Authentication, permissions and admin are explicitly the final milestone. Until M5 passes, run only on `127.0.0.1`; do not bind the unauthenticated API to a LAN interface. M6-M8 are single-local-user only, and their evidence/cache scope must be invalidated/revalidated when M5 adds permission scopes.

Each milestone ends with tests passing on **macOS and Windows** and a short benchmark note.

### M0 — Foundations
- Use the existing Python 3.12 and Git. Install Node 22 LTS. Start Ollama.
- Scaffold `backend/` and `frontend/`, along with `.env.example`, `.gitattributes`, ruff, pytest and CI (Windows + macOS).
- `opsintel doctor` command: checks Python version, git, SQLite FTS5 availability, data directory writability, Ollama reachability and models, LibreOffice/Tesseract (optional), and free RAM and disk.
- **Exit:** `opsintel doctor` is green on both operating systems. `uvicorn opsintel.main:app` serves `/api/health`.

### M1 — Full-text search on a local folder (first useful product)
- Database migrations, parser contract, and text/code/structured parsers.
- Indexer with content hashing, atomic replace and FTS5 (unicode61 + trigram for identifiers).
- Search API: exact, phrase and full-text, with filters, snippets, pagination and coordinates.
- Minimal React UI: search bar, filters, result cards and a code viewer that opens at the matching line.
- `opsintel index-path <dir>` for indexing without Gitea.
- **Exit:** search a 10k-file sample. Line numbers are verified by tests, including CRLF files. p95 exact-search latency is recorded.

### M2 — Gitea sync + persistent jobs + incremental indexing
- Gitea client (token from `.env`): discover repos, then bare mirror clone to `mirrors/`.
- Change sets from `git diff --name-status -M`, covering add, modify, rename and delete. File content is read through `git cat-file --batch`, so no worktree checkout is needed.
- SQLite job queue: leasing, dedupe, exponential backoff, dead-letter, crash recovery (expired leases are re-queued).
- Worker process with a resource governor (RAM/CPU thresholds, pause/resume).
- Webhook endpoint (HMAC, delivery dedupe) plus a scheduled poll reconciler.
- **Local test Gitea:** already installed by the user at `http://localhost:12345` (`/api/v1/version` reports `28.2.0`). It is managed outside this project, so no `devgitea` start/stop commands are needed.
  - Test repo `saurabh/test` (public, branch `master`) contains a sample "fleet portal" with 23 files: Java, Python, JS, JSP, CSS, SQL, shell, a CRLF `.bat` file, YAML/properties/JSON/XML, Markdown, a log, a CSV, a PNG, a vendored `node_modules` file (exclusion test) and a prompt-injection runbook (M6 test). The local working copy is `~/opsintel-sample`.
  - `opsintel devgitea seed` (still to build) uses the Gitea API with an admin token from `.env` to add users `alice` and `bob`, a private repo, an org with a team, a webhook pointing to `http://127.0.0.1:8000/api/webhooks/gitea`, and an OAuth2 application. Fixture repos for every format are added in M3.
- **Exit:** acceptance criteria 3, 4, 5 and 9 are shown by integration tests against the local test Gitea.

### M3 — Document and spreadsheet parsers
- PDF (PyMuPDF, scanned detection), DOCX, DOC (LibreOffice optional), XLSX/XLS/ODS, CSV/TSV.
- Parse cache keyed by content hash, parser version and options.
- Viewer endpoints for PDF pages, sheet windows, CSV rows and DOCX sections.
- **Exit:** a fixture for every format, including malformed, empty and large files. Coordinate-accuracy tests pass, and memory stays bounded on a 200 MB CSV and a 50-sheet workbook.

### M4 — Frontend completion
- Viewers: PDF (bundled `pdfjs-dist`, no CDN), sheet grid, CSV table, DOCX sections, structured text.
- Keyboard navigation, preserved search state, empty and error states. All assets are bundled locally.
- `npm run build` outputs to `backend/opsintel/static/`, served by FastAPI.
- **Exit:** acceptance criteria 1 and 2 are demonstrated end to end.

### M6 — AI question answering (Ollama) (done)
- Ollama health, version and model checks (see 1.3) at startup and before each request. `AI_ENABLED` flag.
- Persistent SQLite AI queue with one consumer per configured slot, a bounded admission limit, and 429 when full. The consumer starts in the API lifespan; its running state and failures are exposed by `/api/health`.
- Retrieval: top-K FTS chunks (hybrid after M7), deduplicated and fitted to a token budget.
- Default evidence budget is **6,000 characters** for the 4K-context Phi-3 development model; configure `AI_CONTEXT_CHARS` with the selected model's context in mind.
- Prompt: system rules, delimited untrusted evidence blocks with IDs, and an instruction to cite IDs only.
- **Citation validator:** any cited ID that was not in the evidence set is stripped and the answer is flagged. Locations are rendered from the database, never from model text.
- Streaming (SSE), cancellation (closing the Ollama request), timeouts, and configurable `keep_alive`.
- AI cache keyed by question, retrieval parameters, model, evidence versions and permission scope (`local-single-user` until M5).
- Citation locations are selected from the most relevant matching source line, not merely the first line of the retrieved chunk.
- **Verification:** Assistant route opens without a runtime error; one Assistant instance is rendered; a live question against `saurabh/test` returned `db2.connection.timeout=90` with a citation to `config/db2.properties` line 5.
- **Exit:** acceptance criteria 6 and 8. Prompt-injection fixtures pass; answer IDs are citation-validated. Queue startup, leasing, cancellation and context limits have regression tests.

### M7 — Semantic and hybrid search (optional layer)
- **Lexical metadata experiment (isolated prototype):** `opsintel experimental metadata-index --repo saurabh/test` builds a separate `data/experiments/metadata-shadow.sqlite3`; `opsintel experimental metadata-search "File with tail number" --repo saurabh/test` searches parser metadata and normalized identifiers. It finds CSV/XLSX headers without modifying the live SQLite database, FTS triggers, search API, or running worker. Evaluate this shadow index before deciding whether to adopt its projection into production.
- Embedding queue using the Ollama `/api/embed` endpoint, with an embedding cache keyed by text hash and model.
- Vector search with repository and permission prefiltering. RRF fusion with full-text search.
- Evaluation set (around 50 queries with expected files) to measure MRR and recall against full-text only.
- **Exit:** acceptance criterion 7. Hybrid search improves the evaluation set, or it stays off by default.

### M8 — Hardening and deliverables
- Load tests (`locust` or a custom asyncio harness): concurrent search plus AI plus indexing under memory pressure.
- Profiling of the real Windows target with the production Qwen model (RSS, tokens/s, time to first token).
- Windows service setup (NSSM or Task Scheduler) for `serve` and `worker`. Backup (`sqlite3 .backup` plus mirrors) and recovery documentation.
- Offline provisioning: Python wheelhouse (`pip download` for win_amd64 and macOS), npm build artifacts, Ollama model files.
- **Exit:** all 15 acceptance criteria are documented with evidence, plus a list of known limitations.

### M5 — Auth, permissions, admin (final milestone)
- **Two login methods, both enabled by configuration** (`AUTH_GITEA_OAUTH_ENABLED`, `AUTH_LOCAL_ENABLED`):
  1. **Gitea OAuth2:** authorization-code flow with PKCE and a `state` check against the internal Gitea. The access token is stored server-side only and used to fetch the user's accessible repos.
  2. **Internal login (user ID + password):** local accounts in the `users` table. Passwords are hashed with **Argon2id** (`argon2-cffi`). Includes login rate limiting and lockout after N failures, an admin-created first user via `opsintel user create --admin`, and password change and reset by an admin. No external dependency, so it works fully offline.
- **Permissions for internal users:** each local account is either linked to a Gitea username (permissions resolved through an admin service token with the `Sudo` header), or receives explicit repository grants from an admin.
- Sessions: opaque server-side IDs in `HttpOnly`, `SameSite=Lax` cookies (`Secure` over HTTPS), CSRF protection, and idle/absolute timeouts.
- **Every** search, viewer, embedding and AI request is filtered by the user's allowed repository IDs. Admin controls require the admin role; webhooks continue to use HMAC.
- Dashboard: index/queue/resource/model status, retry/reindex/pause controls, configuration and audit log.
- M6/M7 AI cache entries are re-scoped or invalidated when M5 permissions change.
- **Exit:** acceptance criteria 14 and 15. Private-repo leakage tests pass across search, viewers, AI retrieval, cache and citations.

---

## 9. Dev Workflow (identical on macOS and Windows)

```text
# one-time (Python 3.12 must already be installed)
cd backend
uv venv --python 3.12 && uv sync       # backend/.venv on Python 3.12
cd ../frontend && npm ci
copy/cp .env.example .env              # set GITEA_URL, GITEA_TOKEN, OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL

ollama create opsintel-dev -f ../devtools/ollama/Modelfile.dev
uv run opsintel devgitea setup && uv run opsintel devgitea seed
uv run opsintel user create admin --admin

# run (4–5 terminals)
ollama serve
uv run opsintel devgitea start         # Gitea on 127.0.0.1:3000
uv run opsintel serve --reload         # uvicorn on 127.0.0.1:8000
uv run opsintel worker
npm run dev                            # Vite on :5173, proxies /api → :8000

# test
uv run pytest
```

Key `.env` entries:
`OPSINTEL_DATA_DIR`, `API_HOST`, `API_PORT`, `GITEA_URL`, `GITEA_TOKEN`, `GITEA_WEBHOOK_SECRET`,
`AUTH_LOCAL_ENABLED`, `AUTH_GITEA_OAUTH_ENABLED`, `GITEA_OAUTH_CLIENT_ID`, `GITEA_OAUTH_CLIENT_SECRET`, `SESSION_IDLE_MIN`, `LOGIN_MAX_FAILURES`,
`OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`, `OLLAMA_KEEP_ALIVE=10m`,
`AI_ENABLED`, `SEMANTIC_ENABLED`, `AI_MAX_CONCURRENCY=1`, `AI_MAX_QUEUE=4`, `AI_TIMEOUT_S`, `AI_NUM_CTX`, `AI_MAX_TOKENS`,
`WORKER_EXTRACT_CONCURRENCY`, `WORKER_MIN_FREE_RAM_MB`, `MAX_FILE_SIZE_MB`, `PARSE_TIMEOUT_S`,
`CACHE_SEARCH_MAX_ENTRIES`, `CACHE_SEARCH_TTL_S`, `LIBREOFFICE_PATH`, `TESSERACT_PATH`, `OCR_ENABLED`.

---

## 10. Open Questions / Assumptions

| # | Question | Default assumption until answered |
|---|---|---|
| 1 | ~~Ollama on Windows~~ | **Resolved:** Ollama 0.10.0 |
| 1a | ~~Dev model~~ | **Resolved:** Phi-3-mini (primary), Mistral 7B (optional). The Windows chat model tag is set through `OLLAMA_CHAT_MODEL` |
| 2 | ~~Dev model files~~ | **Resolved:** in `./model/`, Modelfiles in `devtools/ollama/` |
| 3 | ~~Gitea~~ | **Resolved:** local test Gitea under `devtools/gitea/`. Production Gitea is offline and internal |
| 4 | ~~Authentication~~ | **Resolved:** Gitea OAuth2 + internal ID/password (Argon2id) |
| 4a | ~~Link internal users to Gitea~~ | **Assumed yes:** linked users use a Gitea admin token with `Sudo`. Unlinked users get explicit grants only |
| 4b | Embedding model for semantic search? | None. Semantic search stays off until one is provisioned |
| 5 | Which branches to index: default only, or configurable per repo? | Default branch, plus an optional list per repo |
| 6 | Expected repository size (files, GB) and number of concurrent users? | ≤ 200k files, ≤ 20 concurrent users, so SQLite FTS5 is sufficient |
| 7 | Is LibreOffice allowed on the Windows host for legacy DOC? | Optional. DOC is marked unsupported if absent |
| 8 | Is TypeScript approved for the frontend? | No. JavaScript + JSDoc |
| 9 | Should the API bind only to localhost or be LAN-exposed? | `127.0.0.1` by default. LAN binding requires auth (M5) |

---

## 11. Status and Next Steps

**Done (2026-10-28):**
- **Environment:** Node 22 via nvm, Ollama running, and `opsintel-dev` (Phi-3-mini) imported and answering at about 18 tokens/s.
- **M0:** backend scaffold (`uv`, Python 3.12), settings from `.env`, CLI (`serve`, `migrate`, `doctor`, `index-path`, `reindex`, `repos`, `search`), `.gitignore`, `.gitattributes` and `.nvmrc`.
- **M1:**
  - SQLite schema with FTS5 (unicode61 + trigram).
  - Line-preserving text parser that handles CRLF, CR, BOM, UTF-16, legacy encodings and very long lines.
  - Incremental local-folder indexer: unchanged, modified, deleted and renamed files, plus exclusions and size limits. Binary, unsupported and failed files are recorded.
  - Search API with full-text, phrase and exact-substring modes, filters, highlighted previews and a line viewer.
  - React UI built into FastAPI static files.
  - 18 automated tests.
- **Known M1 limitations:**
  - No authentication yet (M5). Bind to `127.0.0.1` only.
  - CSV and TSV are indexed as plain lines until M3.
  - The Windows run of the test suite has not been executed yet.
- **M2 (done):**
  - **Sync design:** each sync compares the branch tree from `git ls-tree` with the stored git blob SHAs, instead of using commit diffs. Every sync is therefore idempotent and self-reconciling, which covers crashes, missed webhooks, force-pushes and deleted branches.
  - **Git access:** bare mirror clones under `data/mirrors/`, with content streamed through `git cat-file --batch`. The token is passed through the `GIT_CONFIG_*` environment variables, so it never appears in argv or in the mirror's config.
  - **Job queue:** persistent SQLite queue with deduplication of queued jobs and priority upgrades. Each key runs only one job at a time, and the queue has a capacity limit. It also provides exponential backoff, a dead-letter state with retry, lease heartbeats, expired-lease recovery and release on graceful stop.
  - **Worker:** `opsintel worker` runs scheduled Gitea polling (`GITEA_POLL_INTERVAL_S`) and checks a pause flag and a RAM threshold between files. It reports liveness in `/api/health`.
  - **Failing files:** a file whose parser keeps failing is dead-lettered after `FILE_MAX_ATTEMPTS`, and is retried automatically when its content changes.
  - **Webhook:** `POST /api/webhooks/gitea` verifies the HMAC-SHA256 signature, deduplicates deliveries and ignores untracked branches. `GET /api/admin/status` is read-only.
  - **CLI:** `gitea list|add|add-all|webhook`, `sync [--now]`, `worker`, `jobs status|retry|pause|resume`. `doctor` now also checks the git version (2.31 or later) and the Gitea token.
  - **Verification:** 36 automated tests plus one live test against `saurabh/test`. A real push (modify, rename and delete) was reflected correctly at commit `027a6b3`.
- **Open item:** Gitea did not deliver the push webhook to `127.0.0.1:8000`. Gitea blocks loopback targets by default. Set `[webhook] ALLOWED_HOST_LIST = loopback,private` in Gitea's `app.ini` and restart Gitea. Until then, polling picks up changes.
  - **Resolved:** the webhook is now delivered end to end.
- **M3 (done):**
  - **Parsers:**
    - PDF via PyMuPDF 1.x, pinned below 2.0 because 2.0 pulls in onnxruntime and numpy. Gives the page plus the section path from the PDF outline. Scanned pages are detected and reported; OCR is not enabled.
    - DOCX via python-docx. Gives the heading path, paragraph number and table/row, in document order.
    - Legacy DOC via headless LibreOffice when it is installed; otherwise the file is recorded as unsupported with a reason.
    - XLSX via openpyxl in read-only mode. Indexes cached values and formulas separately and warns when a cached value is missing.
    - XLS via xlrd (values only) and ODS via odfpy (handles repeated rows and columns).
    - CSV/TSV with delimiter sniffing, quoted multi-line fields, encoding detection, record numbers and column names.
  - **Isolation:** document parsers run in a `spawn` sandbox process with `PARSE_TIMEOUT_S`. A hang or crash kills only that process, and the file is marked failed (and retried).
  - **Parse cache:** keyed by content hash and parser signature, LRU-bounded by `PARSE_CACHE_MAX_MB`. Identical documents at different paths, branches or repos are parsed once.
  - **Reparse on change:** changing a parser's version or settings changes its signature, so affected files are re-parsed on the next sync. This is how the existing `aircraft.csv` moved from line mode to row mode.
  - **Search locations:** results report the exact location for every kind — line, page and section, section and paragraph or table row, sheet and cell with its column header, and CSV row and column name. The chunk viewer API is `GET /api/files/{id}/chunks/{chunk_id}`, and the UI viewer highlights the exact matching line.
  - **Verification:** 52 tests, using fixtures generated in code (no binary files in the repo). A live push of PDF, DOCX, XLSX, XLS and ODS files to `saurabh/test` was indexed through the webhook with correct locations.
  - **Known M3 limitations:**
    - No OCR.
    - Word page numbers are not reported (by design).
    - XLS formulas are unavailable in xlrd.
    - A CSV value containing `" | "` can shift the reported column.
    - PyMuPDF is AGPL-3.0, so confirm this is acceptable for internal use.
- **M4 (done):**
  - **PDF viewer:** pdf.js is bundled locally and loaded only when a PDF is opened. The viewer fetches the indexed revision from `/api/files/{id}/raw.pdf`, renders the exact hit page to canvas, and provides page navigation, fit-width, zoom and an extracted-text toggle. The PDF worker is a local Vite asset; there are no CDN requests.
  - **PDF source safety:** local files must remain under the indexed repo root, may not traverse symlinks, and must still match the indexed size and SHA-256. Gitea PDFs are read from the indexed Git blob in the local mirror. Stale or deleted local sources return a conflict/not-found response, not a different file.
  - **Spreadsheet viewer:** XLSX/XLS/XLSM/ODS results open in a cell grid with sheet tabs, column headers, matching-cell emphasis and arrow-key navigation. CSV/TSV remain in the row-oriented viewer.
  - **Navigation:** query, file, chunk, page and cell are preserved in the URL, so browser history restores the selected viewer target.
  - **Visual redesign:** dark OpsIntel workspace shell with persistent Home, Global Search, Repositories and Index Health navigation. Home shows live index totals, repository rows and content-type filters; search uses a dense result list beside its source viewer. No unimplemented utility modules are presented as functional.
  - **Local visual asset:** the Home banner uses the NASA/JPL-Caltech Deep Space Station 14 photo bundled at `frontend/public/assets/deep-space-network.jpg`; runtime requests remain offline. The image credit is shown in the UI.
  - **Keyboard and responsive layout:** `Ctrl/Cmd+K` focuses global search; spreadsheet arrows move between cells. Verified at 390 px with no page-level horizontal overflow; the wide workbook grid scrolls inside its own pane and the mobile sidebar opens as a drawer.
  - **Theme:** the dark shell has a matching light palette. A header sun/moon toggle replaces the local-user block and persists the selection in browser local storage.
  - **Performance/offline:** PDF.js is code-split (base app JS ≈238 KB, PDF viewer chunk ≈433 KB, worker ≈1.27 MB) and all assets are bundled locally.
  - **Verification:** PDF page 2 and XLSX cell A3 were exercised in the browser; ArrowRight moved grid focus from A3 to B3. Backend lint passes; 55 tests pass, 1 live test is skipped by default.
  - **Known M4 limitations:** the rendered PDF page navigates to the matching page but does not draw a text-selection overlay for the query; the extracted-text view still highlights the matching text. A workbook viewer displays the target chunk and adjacent chunks, not the whole workbook at once.

**Next:**
1. **M7:** optional local embeddings and hybrid retrieval; keep it disabled until an embedding model is provisioned and evaluated.
2. **M8:** Windows 11 validation, load/resource profiling, offline provisioning and operations/recovery deliverables.
3. **M5 last:** Gitea OAuth2 and internal ID/password login, repository permissions and administration. Keep binding to `127.0.0.1` until then.

Corporate network note: `uv` needs `UV_SYSTEM_CERTS=1` to trust the TLS-inspection certificate.
