# eHelp README

**eHelp** is an *Air Force Document Intelligence* platform—a login-free, offline-capable document portal for indexed PDF, DOCX, XLSX, PPTX, TXT, and video files.

## Features

- **Global Search**: Full-text search across all indexed documents
- **Category Browsing**: Organize documents by categories (Aviation, Engineering, Maintenance, etc.)
- **In-App Previews**: PDF, DOCX, XLSX, PPTX, TXT, CSV, images, and video playback (no download required)
- **AI Assistant**: Ask questions and get cited answers from your documents
- **CBT Support**: Upload and play training videos alongside documents
- **Offline Capable**: Service Worker caches searches, PDFs, and static assets
- **Admin Panel**: Bulk upload, categorize, manage AI settings, customize theme
- **Air Force Theme**: Dark IAF-inspired design with custom branding

## Quick Start

### Local Development

```bash
# Backend (FastAPI)
cd eHelp/backend
uv run ehelp --port 8123

# Frontend (React, in another terminal)
cd eHelp/frontend
npm run dev
# Vite runs on http://localhost:5173, proxies API to :8123
```

Then open **http://localhost:8123** in Chrome.

### Docker

```bash
docker load < ehelp-docker.tar.gz
docker run -d -p 8123:8123 -v /data:/data ehelp:latest
# Access at http://localhost:8123
```

### Windows (Offline)

1. Extract `windows-dev-portable.zip` to `C:\ehelp-dev`
2. Run `setup-dev.bat`
3. Open `http://localhost:8123`

See **WINDOWS_DEV_SETUP.md** for details.

## Architecture

```
eHelp/
├── backend/
│   └── ehelp/
│       ├── app.py           # FastAPI server
│       ├── db.py            # SQLite FTS5 search
│       ├── ai.py            # LLM integration (Ollama)
│       ├── indexing.py      # File parsing (PDF, DOCX, etc.)
│       ├── parsers/          # Document renderers
│       └── static/           # Built frontend
├── frontend/
│   ├── src/
│   │   ├── pages/           # SearchPage, AIPage, DocumentPage, etc.
│   │   ├── components/      # Markdown, FilePreview, Pager, etc.
│   │   ├── styles.css       # IAF theme + responsive UI
│   │   └── App.jsx          # Router
│   ├── public/
│   │   └── sw.js            # Service Worker (offline caching)
│   └── dist/                # Production build (tracked in git)
├── DEPLOYMENT_PLAN.md       # Performance & caching overview
├── PRODUCTION_CHECKLIST.md  # Load testing (1000-3000 users)
├── Dockerfile.rhel          # RHEL 9 production container
├── WINDOWS_DEV_SETUP.md     # Offline Windows dev guide
├── WINDOWS_DEPLOY_SETUP.md  # Offline Windows deployment
└── DOCKER_OFFLINE_GUIDE.md  # Offline Docker customization
```

## Admin Features

- **Upload Documents**: Drag-and-drop or bulk upload (PDF, DOCX, XLSX, PPTX, TXT, CSV, MP4, WebM)
- **Manage Categories**: Create, edit, delete document categories
- **Customize Appearance**: 3+ built-in themes + fully custom color picker
- **AI Mode**: Enable/disable AI assistant, set daily usage limits
- **Document Reindex**: Rebuild search index after edits

Access via **Admin** button (top right) → requires `admin` in `iv-groups` header.

## Deployment

### For 1000 Concurrent Users
- Backend: Uvicorn 4-8 workers
- Database: SQLite FTS5 (single machine)
- Frontend: Static assets with Service Worker caching

```bash
uv run ehelp --port 8123 --workers 8
```

### For 2000-3000 Concurrent Users
- **Load Balancer**: Nginx (least-conn algorithm)
- **Database**: PostgreSQL (replace SQLite)
- **Storage**: NFS or S3 (shared uploads/)
- **Cache**: Redis (search results, AI responses)
- **Scaling**: 3-5 backend instances

See **PRODUCTION_CHECKLIST.md** for load testing scripts and architecture.

## Offline Capabilities

The app works offline for:
- Cached search results (1 minute TTL via HTTP headers)
- Previewed documents (until cleared)
- Browsing categories (static pages cached)
- Downloading documents

No login required—everyone has the same access.

## Browser Support

- **Chrome 120-140**: Fully supported
- **Firefox 121+**: Likely works (not tested)
- **Safari 17+**: Likely works (not tested)
- **IE 11**: Not supported

## Configuration

### Backend Environment Variables
```bash
EHELP_DATA_DIR=/path/to/data           # Where docs & DB are stored
EHELP_DEV_ADMIN=1                      # Dev mode: bypass auth
EHELP_OLLAMA_URL=http://localhost:11434 # LLM server
EHELP_OLLAMA_MODEL=opsintel-dev        # LLM model name
```

### Frontend (Vite)
- Target: ES2020 (Chrome 120+)
- Build output: `dist/` → copied to `backend/ehelp/static/`
- Service Worker: `public/sw.js` → auto-registered on page load

## Performance

### Caching Strategy
| Layer | TTL | Method |
|-------|-----|--------|
| Static Assets | 1 year | HTTP Cache-Control + Vite hash |
| API Responses | 1-60 min | HTTP ETag + Cache-Control |
| Search Results | 60s | Service Worker network-first |
| File Previews | Until cleared | Service Worker cache-first |

### Response Times (Target)
- Search: p95 < 200 ms
- Document fetch: p95 < 100 ms
- File download: depends on size

## Development

### Adding a New Document Parser
1. Create `frontend/src/parsers/MyFormat.jsx` to render in-browser
2. Add file extension to `util.jsx`: `FILE_TYPES`, `KINDS`
3. Update backend `backend/ehelp/parsers/registry.py` for indexing
4. Test upload & preview in Admin panel

### Customizing the Theme
1. Admin → **Appearance** tab
2. Choose preset theme or custom colors
3. Colors persist in SQLite `settings` table

### Adding Categories
1. Admin → **Categories** tab
2. Click **New category**
3. Upload documents, assign to category

## Troubleshooting

### "No documents found after upload"
- Check Admin → Documents tab
- Reindex: Admin → Documents → click Re-index on each doc
- Verify category assigned

### "Search returns nothing"
- Ensure index_status = "indexed" (Admin → Documents)
- Try exact substring search (toggle in Search page)

### "Service Worker not caching"
- Clear browser cache: Ctrl + Shift + Delete
- Unregister: DevTools → Application → Service Workers → Unregister
- Restart app

### "High memory usage"
- Reduce Uvicorn workers: `--workers 4`
- Clear browser cached files: DevTools → Application → Cache Storage

## API Endpoints

### Search
- `GET /api/search?q=<query>&mode=smart|exact&category=<slug>&page=1&page_size=10`

### Documents
- `GET /api/documents/<id>` — metadata
- `GET /api/documents/<id>/related` — similar docs
- `GET /file/<id>` — download

### Admin (requires auth)
- `POST /api/admin/documents` — upload
- `PUT /api/admin/documents/<id>` — edit
- `DELETE /api/admin/documents/<id>` — delete
- `GET /api/admin/settings` — get config
- `PUT /api/admin/settings` — set config

### AI (if enabled)
- `GET /api/ai/status` — check if AI is on
- `POST /api/ai/ask` — ask question (SSE stream)

## Support & Issues

For bugs or feature requests, file an issue on GitHub.

For offline deployments or airgapped environments, see:
- **WINDOWS_DEPLOY_SETUP.md** — Windows production guide
- **DOCKER_OFFLINE_GUIDE.md** — Offline Docker workflow
- **Dockerfile.rhel** — RHEL container for airgapped networks

## License

(Internal use only)

---

**eHelp** | Air Force Document Intelligence  
Built with ❤️ for mission-critical operations.
