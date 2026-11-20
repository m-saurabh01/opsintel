# eHelp Production Readiness Checklist

## Performance & Load Capacity (Target: 1000-3000 concurrent users)

### Backend (FastAPI + SQLite)
- [x] Multi-worker Uvicorn support (4+ workers)
- [x] Async request handling
- [x] Request/response compression (gzip via reverse proxy)
- [x] HTTP caching headers (ETag, Cache-Control, Expires)
- [x] Pagination on all list endpoints (default 10, max 50)
- [ ] Rate limiting per IP/user (requires Redis or in-memory store)
- [ ] Database connection pooling (consider PostgreSQL for production)
- [ ] Query logging and performance monitoring

### Frontend (React + Vite)
- [x] Code splitting via React Router
- [x] Lazy loading components (file previews, AI features)
- [x] Production build with minification
- [x] Service Worker for offline caching
- [x] Static asset hashing (Vite handles this)
- [x] No unminified dependencies in bundle
- [ ] Bundle analysis (run: `npm run build -- --analyze`)
- [ ] WebP image optimization

### Caching Strategy (Implemented)

| Layer | Type | TTL | Method |
|-------|------|-----|--------|
| **Static Assets** | HTTP | 1 year (with hashing) | Vite + Cache-Control |
| **API Responses** | HTTP | 60-3600s | Cache-Control header |
| **Search Results** | HTTP | 60s | Network-first SW |
| **File Previews** | Browser IndexedDB | Until cleared | Cache-first SW |
| **AI Responses** | In-memory* | 1 hour | (Optional Redis) |

*Future: add Redis for distributed caching at scale

### Browser Compatibility (Chrome 120-140)
- [x] ES2020 target (Vite `esbuild` default)
- [x] No IE11 polyfills needed
- [x] Tested features: fetch, Promise, optional chaining, destructuring
- [ ] Real device testing on Chrome 120 (oldest target)
- [ ] Performance audit with Chrome DevTools

---

## Load Testing Guide

### Prerequisite
1. Backend running: `uv run ehelp --port 8123`
2. Frontend built: `npm run build` (outputs to `dist/`)
3. Sample docs indexed: 10 docs across 6 categories

### Test 1: API Response Times (Locust)
**Goal**: Measure p50, p95, p99 latency under concurrent load

```bash
# Install
pip install locust

# Create locustfile.py:
from locust import HttpUser, task, between

class SearchUser(HttpUser):
    wait_time = between(1, 5)
    
    @task(3)
    def search(self):
        self.client.get("/api/search?q=hydraulic")
    
    @task(1)
    def doc(self):
        self.client.get("/api/documents/1")

# Run (100 users, 10/sec ramp-up)
locust -f locustfile.py -u 100 -r 10 --run-time 60s --headless
```

**Success Criteria**:
- p95 latency < 200 ms
- 95%+ requests succeed
- CPU <70%, Memory <500 MB

### Test 2: Concurrent Download (Apache Bench)
**Goal**: Measure throughput and connection limits

```bash
# Download 100 static files concurrently
ab -n 100 -c 20 http://localhost:8123/index.html

# Success: 5+ req/sec, <100ms median response
```

### Test 3: Database Lock Contention (Custom Script)
**Goal**: Verify SQLite FTS5 performance under multi-threaded access

```python
import sqlite3
import threading
import time

def search_worker(doc_id):
    conn = sqlite3.connect('/tmp/ehelp-run/data/documents.sqlite')
    for _ in range(10):
        conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()

# 50 threads, 10 queries each
threads = [threading.Thread(target=search_worker, args=(i % 10,)) for i in range(50)]
start = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
print(f"50 threads × 10 queries in {time.time() - start:.2f}s")
# Target: <5 seconds (50 total queries/sec)
```

### Test 4: Real Browser Load (k6 or Puppeteer)
**Goal**: Simulate real user flows

```bash
# Install k6 (or use Puppeteer + Jest)
brew install k6

# Create script.js
import http from 'k6/http';
import { sleep } from 'k6';

export let options = {
  vus: 500,
  duration: '5m',
  thresholds: {
    http_req_duration: ['p(95)<200', 'p(99)<500'],
  },
};

export default function () {
  http.get('http://localhost:8123/');
  sleep(2);
  http.get('http://localhost:8123/api/search?q=test');
  sleep(3);
}

# Run
k6 run script.js
```

---

## Scaling for 2000-3000 Concurrent Users

### Single Machine (up to 1000 users)
- **Backend**: Uvicorn with 4-8 workers
- **Database**: SQLite (single machine only)
- **Storage**: Local filesystem
- **Config**: `backend/ehelp/config.py` → `WORKERS=8`

```bash
uv run ehelp --port 8123 --workers 8
```

### Multi-Machine (1000-3000 users)
1. **Load Balancer**: Nginx or HAProxy
   ```nginx
   upstream ehelp {
       least_conn;
       server 10.0.1.10:8123;
       server 10.0.1.11:8123;
       server 10.0.1.12:8123;
   }
   server {
       listen 80;
       location / {
           proxy_pass http://ehelp;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

2. **Shared Database**: PostgreSQL (instead of SQLite)
   - Install `pip install psycopg2-binary`
   - Update `config.py`: `DATABASE_URL=postgresql://...`
   - Benefits: concurrent connections, full ACID, FTS5 equivalent

3. **Shared Storage**: NFS or S3
   - Mount `/data/uploads` to NFS: `mount -t nfs4 10.0.0.5:/exports/ehelp /data/uploads`
   - Or use S3 for uploads with presigned URLs

4. **Cache Layer**: Redis
   - `pip install redis`
   - Add to `config.py`: `REDIS_URL=redis://10.0.0.6:6379`
   - Cache AI responses, session data, search results

### Kubernetes Deployment (3000+ users)
```yaml
# deploy/ehelp-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ehelp
spec:
  replicas: 10
  selector:
    matchLabels:
      app: ehelp
  template:
    metadata:
      labels:
        app: ehelp
    spec:
      containers:
      - name: ehelp
        image: ehelp:latest
        ports:
        - containerPort: 8123
        env:
        - name: EHELP_DATA_DIR
          value: /mnt/data
        - name: EHELP_REDIS_URL
          value: redis://redis-service:6379
        livenessProbe:
          httpGet:
            path: /api/status
            port: 8123
          initialDelaySeconds: 10
          periodSeconds: 30
        resources:
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: ehelp-pvc
```

---

## Monitoring & Observability

### Key Metrics
1. **Response Time**: p50, p95, p99 latencies
2. **Throughput**: requests/sec
3. **Error Rate**: 4xx, 5xx percentages
4. **Resource**: CPU, memory, disk I/O, network
5. **Database**: lock contention, query times, connection count

### Tools
- **Local**: `htop`, `iotop`, Chrome DevTools
- **Production**:
  - **Prometheus** + **Grafana**: metrics & dashboards
  - **Jaeger**: distributed tracing
  - **ELK Stack**: logs (Elasticsearch, Logstash, Kibana)
  - **Sentry**: error tracking

### Sample Prometheus Config
```yaml
# ehelp-metrics.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'ehelp'
    static_configs:
      - targets: ['localhost:8123']
    metrics_path: '/metrics'
```

---

## Deployment Checklist

Before production:
- [ ] Load tested to 1000+ concurrent users
- [ ] All 5 Docker/Windows guides tested end-to-end
- [ ] Browser testing on Chrome 120, 130, 140
- [ ] HTTPS enabled (reverse proxy with SSL)
- [ ] Firewall rules: allow only trusted IPs
- [ ] Database backups configured (hourly)
- [ ] Logging enabled and monitored
- [ ] Health checks configured (`/api/status`)
- [ ] Rate limiting enabled (future: Redis-based)
- [ ] Offline mode tested (Service Worker)
- [ ] Admin auth verified (iv-groups header)

---

## Performance Tuning Tips

### Database (SQLite)
```sql
-- Optimize search performance
PRAGMA cache_size = 50000;  -- Increase page cache
PRAGMA synchronous = NORMAL;  -- Safe async writes
PRAGMA temp_store = MEMORY;   -- Use RAM for temp tables
CREATE INDEX IF NOT EXISTS idx_doc_category ON documents(category_id);
CREATE INDEX IF NOT EXISTS idx_doc_created ON documents(created_at DESC);
```

### Backend
```python
# config.py
WORKERS = 8  # Match CPU cores
REQUEST_TIMEOUT = 30
KEEPALIVE = 60
```

### Frontend
```bash
# Vite build optimizations
npm run build -- --minify esbuild --sourcemap=false

# Check bundle size
npm run build -- --analyze
```

---

## Disaster Recovery

### Backup Strategy
- **Database**: Daily snapshots to offsite storage
- **Uploads**: Versioned storage (S3 with versioning enabled)
- **Config**: Git-tracked in private repo

### Restore Procedure
1. Stop application
2. Restore database from last backup
3. Verify data consistency
4. Restart application
5. Run reindex: `python -m ehelp.cli reindex-all`

---

## Support & Troubleshooting

### Common Issues

**High Memory Usage**
- Reduce workers in config
- Clear browser cache
- Check for memory leaks in AI response streaming

**Slow Searches**
- Verify FTS5 index: `SELECT count(*) FROM documents_fts WHERE documents_fts MATCH 'test'`
- Rebuild index: `python -m ehelp.cli reindex-all`
- Increase database cache

**Connection Refused**
- Verify port is not in use: `netstat -tlnp | grep 8123`
- Check firewall rules

**Service Worker Issues**
- Clear browser cache: Ctrl + Shift + Delete → "All time"
- Unregister: DevTools → Application → Service Workers → Unregister

---

## Next Steps

1. Run load tests (Locust, k6) on your target environment
2. Document baseline metrics (latency, throughput, resources)
3. Configure monitoring (Prometheus + Grafana)
4. Plan scaling strategy (single-machine vs. multi-machine)
5. Set up CI/CD for automated deployments
6. Schedule disaster recovery drills
