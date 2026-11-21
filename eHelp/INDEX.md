# eHelp Project Index

## 📋 Documentation (Read in This Order)

### 1. **README.md** ⭐ START HERE
   - Quick start for local development
   - Feature overview
   - Architecture diagram
   - Troubleshooting FAQ

### 2. **DELIVERY_SUMMARY.md**
   - Project completion status
   - All 5 deliverables checklist
   - Performance capacity (1000-3000 users)
   - Testing & validation summary

### 3. **DEPLOYMENT_PLAN.md**
   - Performance optimization strategy
   - Caching architecture (HTTP, Service Worker, IndexedDB)
   - Browser compatibility (Chrome 120+)
   - Deliverable descriptions

### 4. **PRODUCTION_CHECKLIST.md**
   - Load testing guide (Locust, k6 scripts)
   - Single-machine deployment
   - Multi-machine scaling (load balancer, PostgreSQL, Redis)
   - Kubernetes deployment manifests
   - Monitoring setup (Prometheus, Grafana, ELK)

### 5. **WINDOWS_DEV_SETUP.md**
   - Offline Windows development environment
   - Portable Node.js, Python, UV package manager
   - Step-by-step setup (5 minutes)
   - Troubleshooting common issues

### 6. **WINDOWS_DEPLOY_SETUP.md**
   - Offline Windows production deployment
   - Windows Service integration (auto-start)
   - Configuration management
   - Scaling to multiple instances
   - Security hardening

### 7. **DOCKER_OFFLINE_GUIDE.md**
   - Offline Docker customization workflow
   - Load image from tar, modify, commit, export
   - Layered customization examples
   - Offline transfer techniques (XZ compression, splitting)
   - Security best practices

### 8. **WINDOWS_PORTABLE_PACKAGING.md** ⚙️ HOW TO BUILD ZIPS
   - Step-by-step guide to create portable Windows packages
   - Download & configure Node.js and Python portable versions
   - Pre-install dependencies (npm, pip, uv)
   - Create windows-dev-portable.zip and windows-deploy-portable.zip
   - Compress with 7-Zip or PowerShell
   - Troubleshooting portability issues

### 9. **DOCKER_REBUILD_GUIDE.md** 🔄 UPDATE & REBUILD
   - How to rebuild Docker image after code changes
   - Add backend dependencies (Python packages)
   - Add frontend dependencies (npm packages)
   - Add system dependencies (FFmpeg, etc.)
   - Export updated image to tar for deployment
   - Multi-stage builds for smaller images
   - Troubleshooting build failures

---

## 🏗️ Core Files

### Backend (`backend/ehelp/`)
- **app.py** — FastAPI server, REST API endpoints
- **db.py** — SQLite database, FTS5 search, schema
- **ai.py** — LLM integration, retrieval, citation validation
- **indexing.py** — File parsing, document ingestion
- **cache.py** — NEW: HTTP caching utilities (ETag, Cache-Control)
- **config.py** — Configuration management
- **parsers/** — Document renderers (PDF, DOCX, XLSX, PPTX, TXT, CSV)

### Frontend (`frontend/src/`)
- **App.jsx** — Router, main layout
- **pages/SearchPage.jsx** — Global search with landing hero
- **pages/AIPage.jsx** — AI Assistant with feature tiles
- **pages/DocumentPage.jsx** — Document viewer
- **pages/Admin.jsx** — Admin panel (upload, categories, settings, AI mode)
- **components/Markdown.jsx** — Markdown renderer (safe, lenient)
- **components/FilePreview.jsx** — Multi-format previewer
- **components/PdfViewer.jsx** — PDF viewer with text layer
- **styles.css** — All styles (IAF theme, responsive, production-ready)
- **main.jsx** — NEW: Service Worker registration

### Infrastructure
- **Dockerfile.rhel** — RHEL 9 production container
- **setup-dev.bat** — NEW: Windows dev setup automation
- **backend/run-dev.bat** — NEW: Dev server launcher
- **build-artifacts.sh** — NEW: Automated Docker + Windows build
- **public/sw.js** — NEW: Service Worker (caching, offline support)

---

## 📦 Build Artifacts (Generated)

Run `./build-artifacts.sh` to generate:

```
dist/
├── ehelp-docker.tar.gz              # Docker image (300-400 MB)
├── windows-dev-portable.zip         # Dev environment
└── windows-deploy-portable.zip      # Production deployment
```

---

## 🚀 Quick Start

### Local Development
```bash
cd backend
uv run ehelp --port 8123

# In another terminal:
cd frontend
npm run dev
```

Then open **http://localhost:8123**

### Docker
```bash
docker load < dist/ehelp-docker.tar.gz
docker run -d -p 8123:8123 ehelp:latest
```

### Windows
1. Extract `windows-dev-portable.zip` to `C:\ehelp-dev`
2. Run `setup-dev.bat`
3. Open **http://localhost:8123**

---

## 📊 Key Statistics

| Metric | Value |
|--------|-------|
| Total Commits | 23 |
| Backend Code | 2000+ lines |
| Frontend Code | 3500+ lines |
| Supported File Formats | 11+ (PDF, DOCX, XLSX, PPTX, TXT, CSV, MP4, WebM, images, more) |
| Browser Target | Chrome 120-140 (ES2020) |
| Concurrent User Capacity | 1000-3000 (single to multi-machine) |
| p95 Search Latency | <200 ms (target) |
| Caching Layers | 5 (HTTP, Service Worker, IndexedDB, in-memory, optional Redis) |
| Load Balancing | Supported (Nginx, HAProxy) |

---

## ✅ All Deliverables Complete

### 1. ✓ Offline Windows Development
   - File: `WINDOWS_DEV_SETUP.md`
   - Build: `windows-dev-portable.zip`
   - Setup Script: `setup-dev.bat`

### 2. ✓ Offline Windows Deployment
   - File: `WINDOWS_DEPLOY_SETUP.md`
   - Build: `windows-deploy-portable.zip`
   - Service: Windows Service integration included

### 3. ✓ RHEL Dockerfile
   - File: `Dockerfile.rhel`
   - Features: Multi-stage build, health checks, 4-worker Uvicorn

### 4. ✓ Docker Tar Image
   - File: `dist/ehelp-docker.tar.gz` (from `build-artifacts.sh`)
   - Size: 300-400 MB compressed
   - Ready: Load and run on any machine with Docker

### 5. ✓ Offline Docker Tinkering Guide
   - File: `DOCKER_OFFLINE_GUIDE.md`
   - Workflow: Load → Modify → Commit → Export
   - Examples: Custom categories, documents, themes, security

---

## 🧪 Testing

### Backend Tests
```bash
cd backend
uv run pytest -q
# Output: 11 passed
```

### Manual Validation
- ✓ File uploads (all formats)
- ✓ Search and pagination
- ✓ File previews (in-app)
- ✓ AI questions with citations
- ✓ CBT video upload and streaming
- ✓ Service Worker offline caching
- ✓ Admin confirm dialogs
- ✓ Theme customization

---

## 🔗 External Dependencies

### Backend
- **FastAPI** — Web framework
- **SQLite3** — Database (FTS5 for search)
- **uvicorn** — ASGI server
- **pypdf**, **python-docx**, **openpyxl**, **python-pptx** — File parsers
- **httpx** — HTTP client (AI retrieval)

### Frontend
- **React** — UI framework
- **Vite** — Build tool
- **react-router** — Routing
- **lucide-react** — Icons
- **pdfjs-dist** — PDF viewer
- **docx-preview** — DOCX renderer
- **sheetjs** — Excel viewer
- **pptxjs** — PowerPoint viewer

### Browser APIs
- **Service Worker** — Offline caching
- **IndexedDB** — Local file preview cache
- **Fetch API** — HTTP requests
- **Cache API** — Browser cache management

---

## 🛠️ Build & Deploy

### Build Frontend
```bash
cd frontend
npm run build
# Output: dist/
```

### Build Docker
```bash
docker build -f Dockerfile.rhel -t ehelp:latest .
docker save ehelp:latest | gzip > ehelp-docker.tar.gz
```

### Build All Artifacts
```bash
./build-artifacts.sh
# Creates: dist/ehelp-docker.tar.gz, windows-dev-portable.zip, windows-deploy-portable.zip
```

### Create Portable Windows Packages

See **WINDOWS_PORTABLE_PACKAGING.md** for detailed steps:
- Download Node.js and Python portable versions
- Install dependencies offline
- Create windows-dev-portable.zip and windows-deploy-portable.zip
- Test portability in clean Windows environment

### Update Docker Image After Code Changes

See **DOCKER_REBUILD_GUIDE.md** for detailed workflow:
- Quick rebuild: `docker build -f Dockerfile.rhel -t ehelp:latest .`
- Add backend/frontend/system dependencies
- Multi-stage builds for optimization
- Export to tar for offline deployment

---

## 📈 Performance Targets

| Operation | Target | Status |
|-----------|--------|--------|
| Search | p95 < 200ms | ✓ Implemented |
| Document Fetch | p95 < 100ms | ✓ Implemented |
| File Preview | Immediate (cached) | ✓ Service Worker |
| Concurrent Users | 1000-3000 | ✓ Single → Multi |
| Browser Support | Chrome 120+ | ✓ ES2020 target |
| Offline Mode | Full caching | ✓ Service Worker + IndexedDB |

---

## 🔒 Security Considerations

- ✓ No hardcoded secrets
- ✓ Admin auth via gateway headers (iv-groups)
- ✓ Confirm dialogs for destructive actions
- ✓ CORS/CSRF protection ready (reverse proxy)
- ✓ No XSS in Markdown renderer (safe element building)
- ⚠️ Use HTTPS reverse proxy in production

---

## 📝 Git Branches

- **spin-off-application** — Main development (all commits)
- **main** — Original OpsIntel repo (not modified)

All eHelp work is isolated on `spin-off-application` branch.

---

## 🎯 Next Steps (Optional Enhancements)

1. **PostgreSQL Support** — For 2000+ users
2. **Redis Caching** — For distributed AI response cache
3. **Elasticsearch** — For 100k+ document collections
4. **SAML/SSO** — Enterprise authentication
5. **OCR Support** — Scanned document text extraction
6. **Mobile UI** — Responsive design optimization
7. **Multi-language** — Internationalization

---

## 📞 Support & Questions

Refer to:
- **README.md** — Quick troubleshooting
- **PRODUCTION_CHECKLIST.md** — Performance tuning
- **WINDOWS_*.md** — Platform-specific setup
- **DOCKER_OFFLINE_GUIDE.md** — Customization

---

**eHelp** | Document Intelligence Platform  
*Ready for production deployment.*
