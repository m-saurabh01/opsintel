# eHelp Deployment & Performance Plan

## 1. Performance & Load Testing (2000-3000 concurrent users, min 1000)

### Backend Optimizations
- **Database**: SQLite FTS5 currently single-threaded. For production:
  - Add connection pooling (consider PostgreSQL for multi-threaded access)
  - Implement query caching with Redis
  - Add database query optimization and indexing analysis
  
- **API Optimization**:
  - Add compression (gzip) for all responses
  - Implement HTTP caching headers (ETag, Last-Modified)
  - Pagination is in place; ensure page sizes are reasonable
  - Consider rate limiting per user/IP
  
- **Concurrency**:
  - Use `uvicorn` with multiple workers: `--workers 4` minimum
  - Thread pool for I/O operations
  - Async file operations where possible

### Frontend Optimizations
- **Build Output**:
  - Current bundle needs analysis (webpack-bundle-analyzer)
  - Code splitting for routes (already in place via React Router)
  - Lazy load components for heavy features (AI, file previews)
  
- **Caching Strategies**:
  - **HTTP Caching**: Static assets (CSS, JS, images) → `Cache-Control: max-age=31536000` (1 year, with content hashing)
  - **Service Worker**: Cache API for offline capabilities, network-first for search results
  - **Browser Cache**: Document previews cached locally (IndexedDB for large files)
  - **CDN**: Distribute static assets
  
- **Browser Compatibility**:
  - Chrome 120-140: Most modern features supported
  - Polyfills needed: `fetch`, `Promise`, optional chaining (already used in modern code)
  - Use `@babel/preset-env` to target ES2020 (safe for Chrome 120+)
  - Test with Vite's `esbuild` target: `es2020`

## 2. Delivery Packages

### A. Offline Windows Development Setup
**File**: `WINDOWS_DEV_SETUP.md` + `windows-dev-portable.zip`

Contents:
- Node.js v22.23.4 (portable)
- Python 3.11+ (portable)
- UV package manager (portable)
- Pre-built `node_modules` and Python venv
- Setup batch script (`.bat`)
- Local docs (no internet required)

### B. Offline Windows Deployment
**File**: `WINDOWS_DEPLOY_SETUP.md` + `windows-deploy-portable.zip`

Contents:
- Same as dev + production build (vite output)
- Standalone backend binary (PyInstaller)
- Windows service wrapper
- Database seed (sample docs pre-indexed)
- Systemd/Windows Scheduler integration
- Admin panel pre-configured

### C. Dockerfile for RHEL
**File**: `Dockerfile.rhel`

```dockerfile
FROM rhel/rhel-server:9
# Install Python, Node, UV
# Copy app + build output
# EXPOSE 8123
# CMD ["python", "-m", "ehelp", "--port", "8123"]
```

### D. Docker Tar Image (Ready-to-Deploy)
**File**: `ehelp-docker.tar.gz`

Pre-built image:
- FastAPI + SQLite + indexed docs
- React build output (static/)
- All dependencies included
- Load: `docker load < ehelp-docker.tar.gz && docker run -p 8123:8123 ehelp:latest`

### E. Guide: Offline Docker Tinkering
**File**: `DOCKER_OFFLINE_GUIDE.md`

Steps:
1. Extract tar into Docker
2. Mount volume for `/data` (persistent docs)
3. Modify config inside running container
4. Commit changes: `docker commit <container> ehelp:v2`
5. Export: `docker save ehelp:v2 > ehelp-v2.tar.gz`

---

## 3. Caching Strategy Summary

| Layer | Technology | TTL | Use Case |
|-------|-----------|-----|----------|
| **Static Assets** | HTTP Cache + ETag | 1 year | CSS, JS, images |
| **API Responses** | Redis + ETags | 5 min | Search results, doc metadata |
| **Document Chunks** | In-memory LRU | 30 min | Full-text search index |
| **File Previews** | Browser IndexedDB | Until cleared | PDF, XLSX, DOCX renders |
| **AI Responses** | Redis | 1 hour | LLM output per question |

---

## 4. Browser Polyfills (Chrome 120+)
- Already modern; minimal polyfills needed
- Ensure no IE11 targeting
- Test with: `npx browserslist-ci "Chrome 120, Chrome 140"`

---

## 5. Load Testing Checklist
- [ ] Locust / k6 script for 1000-3000 concurrent users
- [ ] Database index analysis (SQLite FTS5 performance)
- [ ] Network bandwidth simulation (latency, packet loss)
- [ ] Memory and CPU profiling (backend + frontend)
- [ ] Cache hit rate monitoring
- [ ] API response time SLAs (<200ms p95)
