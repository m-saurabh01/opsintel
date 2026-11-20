#!/bin/bash
# Build all deployment artifacts for eHelp
# Usage: ./build-artifacts.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  eHelp Build Artifacts"
echo "=========================================="
echo

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# Function to print step
step() {
  echo -e "${BLUE}[*]${NC} $1"
}

# Function to print success
success() {
  echo -e "${GREEN}[✓]${NC} $1"
}

# 1. Build Frontend
step "Building frontend..."
cd frontend
export PATH=$HOME/.nvm/versions/node/v22.23.4/bin:$PATH
npx vite build > /dev/null 2>&1
success "Frontend build complete (output: dist/)"
cd ..

# 2. Build Docker Image
step "Building Docker image (eHelp)..."
docker build -f Dockerfile.rhel -t ehelp:latest . > /tmp/docker-build.log 2>&1 || {
  echo "Docker build failed. Check /tmp/docker-build.log"
  exit 1
}
success "Docker image built (size: $(docker images ehelp:latest --format='{{.Size}}'))"

# 3. Export Docker Tar
step "Exporting Docker image as tar..."
mkdir -p dist
docker save ehelp:latest | gzip > dist/ehelp-docker.tar.gz
success "Docker tar created (size: $(du -h dist/ehelp-docker.tar.gz | cut -f1))"

# 4. Create Windows Dev Package
step "Creating Windows dev package..."
mkdir -p build/windows-dev
# Note: In production, include portable Node, Python, UV
# For now, create directory structure
mkdir -p build/windows-dev/{backend,frontend,node-v22.23.4-win-x64,python-3.11.9-embed-amd64,uv-latest}
cp -r backend/ehelp build/windows-dev/backend/
cp -r frontend/{public,src,index.html,package.json,vite.config.js,tsconfig.json} build/windows-dev/frontend/
cp setup-dev.bat backend/run-dev.bat build/windows-dev/
cp -r backend/.env.example build/windows-dev/backend/ || true
# Note: User must download portable runtimes separately
echo "✓ See WINDOWS_DEV_SETUP.md for portable runtime download links" > build/windows-dev/RUNTIMES.txt
cd build/windows-dev
zip -rq ../../dist/windows-dev-portable.zip . > /dev/null 2>&1
cd ../../
success "Windows dev package created (size: $(du -h dist/windows-dev-portable.zip | cut -f1))"

# 5. Create Windows Deploy Package
step "Creating Windows deploy package..."
mkdir -p build/windows-deploy/frontend
# Copy production build
cp -r frontend/dist/* build/windows-deploy/frontend/
mkdir -p build/windows-deploy/backend
cp -r backend/ehelp build/windows-deploy/backend/
cp backend/pyproject.toml build/windows-deploy/backend/
# Note: User must bundle PyInstaller-compiled exe
echo "✓ See WINDOWS_DEPLOY_SETUP.md for executable bundle instructions" > build/windows-deploy/INSTRUCTIONS.txt
cd build/windows-deploy
zip -rq ../../dist/windows-deploy-portable.zip . > /dev/null 2>&1
cd ../../
success "Windows deploy package created (size: $(du -h dist/windows-deploy-portable.zip | cut -f1))"

# 6. Summary
echo
echo "=========================================="
echo "  Build Complete"
echo "=========================================="
echo
echo "Output directory: dist/"
echo
ls -lh dist/
echo
echo "Next steps:"
echo "1. Docker: docker load < dist/ehelp-docker.tar.gz"
echo "2. Windows Dev: Extract dist/windows-dev-portable.zip and run setup-dev.bat"
echo "3. Windows Deploy: See WINDOWS_DEPLOY_SETUP.md"
echo
echo "Documentation:"
echo "  - DEPLOYMENT_PLAN.md: Overview & caching strategy"
echo "  - PRODUCTION_CHECKLIST.md: Load testing & scaling"
echo "  - Dockerfile.rhel: RHEL production container"
echo "  - WINDOWS_DEV_SETUP.md: Windows development guide"
echo "  - WINDOWS_DEPLOY_SETUP.md: Windows production deployment"
echo "  - DOCKER_OFFLINE_GUIDE.md: Offline customization workflow"
echo
