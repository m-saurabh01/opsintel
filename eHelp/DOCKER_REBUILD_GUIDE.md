# Docker Image Rebuild Guide

## Overview

This guide explains how to rebuild the eHelp Docker image after adding new features, modules, or dependencies in development.

---

## Quick Start: Rebuild Docker Image

After making changes to code or dependencies:

```bash
# 1. Commit your code changes
git add -A
git commit -m "Add new module: <module-name>"

# 2. Rebuild Docker image (from project root)
docker build -f Dockerfile.rhel -t ehelp:latest .

# 3. Test the new image locally
docker run -d -p 8123:8123 -v $(pwd)/data:/data ehelp:latest

# 4. Access at http://localhost:8123

# 5. Export updated image to tar
docker save ehelp:latest | gzip > ehelp-docker-updated.tar.gz

# 6. (Optional) Push to registry
docker tag ehelp:latest your-registry/ehelp:v1.0.0
docker push your-registry/ehelp:v1.0.0
```

---

## Detailed Workflow: Adding a New Module

### Step 1: Develop Locally

```bash
# Frontend: Add new React component/page
frontend/src/pages/MyNewModule.jsx

# Backend: Add new FastAPI endpoint
backend/ehelp/routes/my_new_module.py

# Update dependencies if needed
# Frontend:
cd frontend
npm install some-new-library
npm install -D some-dev-tool

# Backend:
cd backend
pip install new-package
# Update requirements.txt or pyproject.toml
pip freeze > requirements.txt
```

### Step 2: Test Locally (Before Docker)

```bash
# Test backend
cd backend
uv run ehelp --port 8123

# In another terminal, test frontend
cd frontend
npm run dev
# Vite runs on :5173, proxies API to :8123

# Test all features, verify no errors
```

### Step 3: Commit Changes

```bash
git add -A
git commit -m "feat: add MyNewModule

- Backend: new /api/my-module endpoint
- Frontend: new MyNewModule page
- Dependencies: added new-package (backend), some-library (frontend)
"
```

### Step 4: Rebuild Docker Image

```bash
# From project root where Dockerfile.rhel exists
docker build -f Dockerfile.rhel -t ehelp:latest .

# Output:
# [1/X] FROM redhat/ubi9/ubi-minimal:latest
# [2/X] RUN microdnf install -y nodejs python3.12 npm
# ...
# [X/X] RUN uvicorn ehelp.app:app --port 8123
# => exporting to image
# => naming to docker.io/library/ehelp:latest
# => => exporting layers
# Successfully tagged ehelp:latest
```

### Step 5: Verify Build Success

```bash
# Check image was created
docker images | grep ehelp
# Output:
# ehelp    latest    abc123def456    2 minutes ago    800MB

# Check image size (should be ~800MB-1GB)
docker inspect ehelp:latest | grep -i size
```

### Step 6: Test Docker Image Locally

```bash
# Start container
docker run -d \
  --name ehelp-test \
  -p 8123:8123 \
  -v $(pwd)/data:/data \
  ehelp:latest

# Check container is running
docker ps | grep ehelp-test

# Check logs for startup errors
docker logs ehelp-test

# Access application
curl http://localhost:8123
# or open browser: http://localhost:8123

# Test API endpoints
curl http://localhost:8123/api/health
curl http://localhost:8123/api/search?q=test

# Stop container
docker stop ehelp-test
docker rm ehelp-test
```

### Step 7: Export to Tar (For Offline Deployment)

```bash
# Save image to compressed tar file
docker save ehelp:latest | gzip > ehelp-docker-updated.tar.gz

# Verify file size (should be 300-400 MB)
ls -lh ehelp-docker-updated.tar.gz

# Transfer to target machine and load:
# docker load < ehelp-docker-updated.tar.gz
```

---

## Understanding the Dockerfile

### File: `Dockerfile.rhel`

```dockerfile
# Stage 1: Base image with minimal runtime
FROM redhat/ubi9/ubi-minimal:latest

# Install runtime dependencies
RUN microdnf install -y \
    nodejs npm \
    python3.12 pip \
    && microdnf clean all

# Set working directory
WORKDIR /app

# Copy source code
COPY . .

# Install dependencies
RUN npm --prefix frontend ci
RUN pip install -r backend/requirements.txt

# Build frontend
RUN npm --prefix frontend run build

# Expose port
EXPOSE 8123

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8123/api/health')"

# Run backend server
CMD ["python3", "-m", "uvicorn", "ehelp.app:app", "--host", "0.0.0.0", "--port", "8123", "--workers", "4"]
```

### Key Sections

| Section | Purpose | Update When |
|---------|---------|-------------|
| `FROM redhat/...` | Base OS image | Upgrading base OS |
| `RUN microdnf install` | System packages | Adding system dependencies |
| `COPY . .` | Copy source code | Always rebuilds code layer |
| `RUN npm ci` | Install frontend deps | Frontend `package.json` changes |
| `RUN pip install` | Install backend deps | Backend `requirements.txt` changes |
| `RUN npm run build` | Build frontend | Frontend code changes |
| `EXPOSE 8123` | Port mapping | Changing port |
| `HEALTHCHECK` | Container health | Changing health check endpoint |
| `CMD` | Startup command | Changing server config |

---

## Scenario 1: Add Backend Dependency

**What changed**: Backend code uses a new Python package

**Steps**:

```bash
# 1. Install locally
pip install new-package

# 2. Update requirements.txt
pip freeze > backend/requirements.txt

# 3. Test locally
uv run ehelp --port 8123

# 4. Commit
git add backend/requirements.txt backend/ehelp/my_new_code.py
git commit -m "feat: add new backend feature with new-package"

# 5. Rebuild Docker
docker build -f Dockerfile.rhel -t ehelp:latest .

# 6. Test
docker run -d -p 8123:8123 ehelp:latest
docker logs $(docker ps -q --filter="ancestor=ehelp:latest")

# 7. Verify endpoint works
curl http://localhost:8123/api/new-endpoint
```

---

## Scenario 2: Add Frontend Dependency

**What changed**: Frontend uses a new npm package

**Steps**:

```bash
# 1. Install locally
cd frontend
npm install new-react-library

# 2. Use in component
# src/components/MyComponent.jsx
import NewLib from 'new-react-library'

# 3. Test locally
npm run dev

# 4. Build for production
npm run build
# Check dist/ output

# 5. Commit
git add frontend/package.json frontend/package-lock.json frontend/src/components/MyComponent.jsx
git commit -m "feat: add MyComponent with new-react-library"

# 6. Rebuild Docker
docker build -f Dockerfile.rhel -t ehelp:latest .

# 7. Test
docker run -d -p 8123:8123 ehelp:latest
# Access http://localhost:8123, verify component renders

# 8. Check bundle size increased reasonably
docker exec $(docker ps -q) du -sh /app/frontend/dist
```

---

## Scenario 3: Add System Dependency

**What changed**: Code requires a system package (e.g., FFmpeg, ImageMagick)

**Steps**:

```bash
# 1. Update Dockerfile.rhel
# In RUN microdnf install line, add:
# ffmpeg imagemagick

# 2. Test image builds
docker build -f Dockerfile.rhel -t ehelp:latest .

# 3. Test system package is installed
docker run ehelp:latest ffmpeg -version

# 4. Use in backend code
# backend/ehelp/my_processor.py
import subprocess
result = subprocess.run(['ffmpeg', ...])

# 5. Test locally
# (requires ffmpeg installed on dev machine)
uv run ehelp --port 8123

# 6. Commit
git add Dockerfile.rhel backend/ehelp/my_processor.py
git commit -m "feat: add FFmpeg support for video processing"

# 7. Rebuild
docker build -f Dockerfile.rhel -t ehelp:latest .

# 8. Test
docker run -d -p 8123:8123 ehelp:latest
docker exec $(docker ps -q) ffmpeg -version
```

---

## Scenario 4: Update Config or Environment

**What changed**: Configuration or settings need to be different in Docker

**Steps**:

```bash
# 1. Update backend config
# backend/ehelp/config.py
# or backend/.env

DATABASE_PATH = "/data/ehelp.db"
LOG_LEVEL = "INFO"

# 2. Test with Docker environment variables
docker run -d \
  -p 8123:8123 \
  -e LOG_LEVEL=DEBUG \
  -v $(pwd)/data:/data \
  ehelp:latest

# 3. If Dockerfile changes needed:
# Update ENV or CMD sections

# 4. Rebuild if Dockerfile changed
docker build -f Dockerfile.rhel -t ehelp:latest .

# 5. Test with new config
docker run -d -p 8123:8123 -e LOG_LEVEL=DEBUG ehelp:latest
docker logs $(docker ps -q)
```

---

## Multi-Stage Build (Advanced)

For smaller, optimized images:

```dockerfile
# Stage 1: Build stage
FROM redhat/ubi9/ubi-minimal:latest as builder

WORKDIR /build
COPY . .

RUN microdnf install -y nodejs npm python3.12 pip
RUN npm --prefix frontend ci && npm --prefix frontend run build
RUN pip install -r backend/requirements.txt

# Stage 2: Runtime (minimal)
FROM redhat/ubi9/ubi-minimal:latest

WORKDIR /app

# Copy only runtime dependencies and built artifacts
COPY --from=builder /build/frontend/dist ./frontend/dist
COPY --from=builder /build/backend ./backend
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

RUN microdnf install -y nodejs python3.12 && microdnf clean all

EXPOSE 8123
CMD ["python3", "-m", "uvicorn", "ehelp.app:app", "--host", "0.0.0.0", "--port", "8123"]
```

Result: Image size reduced from 1GB → 400-500 MB

---

## Optimization: Layer Caching

Docker caches layers. To speed up rebuilds:

**Good (cacheable layers first):**
```dockerfile
# System packages (rarely change)
RUN microdnf install ...

# Dependencies (change less often)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Source code (changes frequently)
COPY . .
```

**Bad (invalidates cache):**
```dockerfile
COPY . .
RUN pip install -r requirements.txt
# Changes code, invalidates cached pip layer
```

**Result**: First build: 3 minutes. Subsequent builds (code only): 20 seconds.

---

## Troubleshooting

### Build fails: "npm: command not found"
**Problem**: Node.js not installed in base image
**Solution**: Check `microdnf install -y nodejs npm` is in Dockerfile

### Build fails: "ModuleNotFoundError: No module named 'fastapi'"
**Problem**: Python dependencies not installed
**Solution**: Verify `pip install -r requirements.txt` is in Dockerfile

### Docker image too large (>1.5 GB)
**Problem**: node_modules or pip cache bloating image
**Solution**: 
```dockerfile
# After npm install
RUN npm cache clean --force

# After pip install
RUN pip cache purge
```

### Container won't start: "Port 8123 already in use"
**Solution**:
```bash
# Stop existing container
docker stop $(docker ps -q)

# Or use different port
docker run -d -p 9000:8123 ehelp:latest
```

### Changes don't appear in running container
**Problem**: Docker cached old layer
**Solution**: Use `--no-cache` flag
```bash
docker build -f Dockerfile.rhel -t ehelp:latest --no-cache .
```

---

## CI/CD Integration (Optional)

For automated Docker builds on GitHub push:

**.github/workflows/build-docker.yml**:
```yaml
name: Build Docker Image

on:
  push:
    branches: [spin-off-application]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build Docker image
        run: docker build -f Dockerfile.rhel -t ehelp:${{ github.sha }} .
      
      - name: Save to tar
        run: docker save ehelp:${{ github.sha }} | gzip > ehelp-${{ github.sha }}.tar.gz
      
      - name: Upload artifact
        uses: actions/upload-artifact@v3
        with:
          name: ehelp-docker
          path: ehelp-*.tar.gz
```

---

## Checklist: Before Pushing Image to Prod

- [ ] Code tested locally (backend + frontend)
- [ ] Dependencies updated (package.json, requirements.txt)
- [ ] Dockerfile builds without errors
- [ ] Container starts and responds to health check
- [ ] All API endpoints working
- [ ] File uploads working
- [ ] Search working
- [ ] AI features working
- [ ] Admin panel accessible
- [ ] No sensitive data in image
- [ ] Image size reasonable (<1 GB)
- [ ] Docker image tagged with version: `docker tag ehelp:latest ehelp:v1.0.0`

---

## Quick Reference

| Task | Command |
|------|---------|
| Build image | `docker build -f Dockerfile.rhel -t ehelp:latest .` |
| Run container | `docker run -d -p 8123:8123 ehelp:latest` |
| View logs | `docker logs <container-id>` |
| Stop container | `docker stop <container-id>` |
| Remove image | `docker rmi ehelp:latest` |
| Export to tar | `docker save ehelp:latest \| gzip > ehelp.tar.gz` |
| Load from tar | `docker load < ehelp.tar.gz` |
| List images | `docker images` |
| List containers | `docker ps -a` |
| Enter container | `docker exec -it <container-id> bash` |
| Check image size | `docker images --no-trunc` |

---

**After rebuilding**: Test thoroughly before deploying to production. Use a staging environment first if possible.
