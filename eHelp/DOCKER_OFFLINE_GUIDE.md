# Docker Offline Tinkering & Image Customization

## Scenario: You Have `ehelp-docker.tar.gz` and No Internet

### Step 1: Load the Docker Image
```bash
# Decompress (if compressed)
gzip -d ehelp-docker.tar.gz  # Result: ehelp-docker.tar

# Load into Docker
docker load < ehelp-docker.tar

# Verify
docker images | grep ehelp
# Expected: ehelp:latest  <tag>  <size>  <date>
```

### Step 2: Run a Container for Tinkering
```bash
# Mount a data volume and start bash shell
docker run -it \
  -p 8123:8123 \
  -v /var/ehelp-data:/data \
  -v /var/ehelp-mods:/mods \
  --name ehelp-dev \
  ehelp:latest \
  /bin/bash
```

### Step 3: Modify Inside the Container
Examples:

**Add Custom Category**
```bash
# Inside container:
cd /opt/ehelp/backend
python3 << 'EOF'
from ehelp.db import get_db
db = get_db()
db.execute("INSERT INTO categories (name, slug, description) VALUES (?, ?, ?)", 
           ("Custom", "custom", "Custom documents"))
db.commit()
print("Category added!")
EOF
```

**Edit Configuration**
```bash
# Inside container:
vi /opt/ehelp/backend/ehelp/config.py
# Change: AI_ENABLED = True
# Save and exit
```

**Copy Custom Files**
```bash
# From your host, copy before running container:
docker cp ./my-document.pdf ehelp-dev:/data/uploads/
```

**Restart App After Changes**
```bash
# Inside container:
pkill -f "uvicorn"
python3 -m uvicorn ehelp.app:app --host 0.0.0.0 --port 8123 --reload
```

### Step 4: Commit Changes to a New Image
```bash
# From your host (stop container first):
docker stop ehelp-dev
docker commit ehelp-dev ehelp:custom-v1

# Verify new image
docker images | grep ehelp
# Expected: ehelp:custom-v1  ...
#           ehelp:latest     ...
```

### Step 5: Save the Modified Image
```bash
# Export as tar (compressed)
docker save ehelp:custom-v1 | gzip > ehelp-custom-v1.tar.gz

# Export as tar (uncompressed, for large networks)
docker save ehelp:custom-v1 > ehelp-custom-v1.tar

# Check file size
ls -lh ehelp-custom-v1.tar.gz
```

### Step 6: Deploy the Modified Image
**On Another Machine:**
```bash
# Transfer the tar file (via USB, network share, etc.)
scp ehelp-custom-v1.tar.gz user@server:/tmp/

# On target machine:
gzip -d /tmp/ehelp-custom-v1.tar.gz
docker load < /tmp/ehelp-custom-v1.tar

# Run
docker run -d -p 8123:8123 -v /data:/data ehelp:custom-v1
```

---

## Workflow: Layered Customization

### Layer 1: Base Image (from tar)
```bash
docker load < ehelp-docker.tar
```

### Layer 2: Configuration
```bash
docker run -it --name cfg-layer ehelp:latest bash
# Inside: Edit /opt/ehelp/config, then exit
docker commit cfg-layer ehelp:configured
```

### Layer 3: Custom Docs
```bash
docker run -it --name doc-layer -v /host/docs:/import ehelp:configured bash
# Inside: cp /import/*.pdf /data/uploads/
docker commit doc-layer ehelp:with-docs
```

### Layer 4: Final Image
```bash
docker save ehelp:with-docs | gzip > ehelp-final.tar.gz
# This can be deployed on airgapped networks
```

---

## Tips & Tricks

### Interactive Inspection
```bash
# See what's inside the image
docker run --rm -it ehelp:latest ls -la /opt/ehelp/

# Check dependencies
docker run --rm -it ehelp:latest pip list

# View logs of running container
docker logs -f ehelp-dev
```

### Minimal Offline Transfer
If tar is too large (>500 MB):
1. Compress more: `docker save ehelp:latest | xz > ehelp.tar.xz` (~200 MB)
2. Split for USB: `split -b 500M ehelp.tar.xz ehelp-part-` → Copy parts → Recombine on target
3. Use Docker layer caching: Push to private registry (if internal network available)

### Persistent Configuration
```bash
# Instead of modifying inside container, mount config:
docker run -d \
  -p 8123:8123 \
  -v /data:/data \
  -v /host/config.ini:/opt/ehelp/config.ini \
  ehelp:latest
```

### Rollback
```bash
# Keep old images:
docker tag ehelp:latest ehelp:backup-2024-11-20
docker tag ehelp:custom-v1 ehelp:latest

# Rollback if needed:
docker stop ehelp-container
docker run -d -p 8123:8123 -v /data:/data ehelp:backup-2024-11-20
```

---

## Security Considerations

### Don't Ship Production Secrets in Image
- Use environment variables: `docker run -e AI_API_KEY=... ehelp:latest`
- Or mounted volumes: `-v /secrets/apikey:/run/secrets/apikey:ro`

### Network Isolation
```bash
# Create isolated network
docker network create ehelp-net
docker run -d --network ehelp-net ehelp:latest
```

### Read-Only Filesystem (For Immutable Deployment)
```bash
docker run -d \
  --read-only \
  -v /data:/data \
  --tmpfs /tmp \
  ehelp:latest
```
