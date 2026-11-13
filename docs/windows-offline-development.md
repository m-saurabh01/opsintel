# OpsIntel Offline Windows Development

Use this path when you need to **edit, test, and build OpsIntel on a Windows PC with no public internet**, while still reaching your internal Gitea and Ollama servers. It is separate from the smaller runtime deployment bundle: offline development also needs Git history, Python development packages, and a cached npm package set.

## Your Environment

This workflow assumes:

- Offline PC: Windows x64, Python 3.12.8, Node 22/npm, and Git for Windows already installed.
- Internal services: Gitea and Ollama are reachable over the private network; Ollama already has Qwen3 and nomic-embed-text.
- Online staging PC: can reach GitHub and npm/Python package sources, and has the same Windows architecture, Python 3.12, Node/npm versions, and Git.

The offline PC does **not** need `uv`, a local Gitea/MySQL server, a local Ollama service, or model weights in this topology.

## 1. Prepare the Development Bundle Online

Start from a clean checkout of the exact source commit you intend to continue from. Record its full commit hash:

```powershell
git clone --branch master <OPSINTEL_GITHUB_URL> C:\OpsIntel-Staging\OpsIntel
Set-Location C:\OpsIntel-Staging\OpsIntel
git rev-parse HEAD | Set-Content C:\OpsIntel-Staging\OPSINTEL_BASE_COMMIT.txt
```

Create a Git bundle containing the `master` history. This allows local commits on the disconnected PC and later transfers only the commits back to staging:

```powershell
New-Item -ItemType Directory -Force C:\OpsIntel-Staging\bundle | Out-Null
git bundle create C:\OpsIntel-Staging\bundle\OpsIntel.bundle master
git bundle verify C:\OpsIntel-Staging\bundle\OpsIntel.bundle
```

Export all locked runtime and development Python dependencies, then download compatible Windows x64 wheels with Python 3.12. This includes the project's test and lint tools:

```powershell
New-Item -ItemType Directory -Force C:\OpsIntel-Staging\bundle\python\wheelhouse | Out-Null
Set-Location C:\OpsIntel-Staging\OpsIntel\backend
uv export --locked --all-groups --no-emit-project --format requirements-txt `
  --output-file C:\OpsIntel-Staging\bundle\python\requirements-dev.txt
py -3.12 -m pip download --only-binary=:all: `
  --dest C:\OpsIntel-Staging\bundle\python\wheelhouse `
  -r C:\OpsIntel-Staging\bundle\python\requirements-dev.txt
```

If `pip download --only-binary=:all:` fails, resolve the missing Windows wheel on the staging PC before transfer. Do not solve it by allowing internet access on the offline PC.

Cache the frontend packages using the exact Node/npm version expected on the target:

```powershell
Set-Location C:\OpsIntel-Staging\OpsIntel\frontend
node --version | Set-Content C:\OpsIntel-Staging\bundle\NODE_VERSION.txt
npm --version | Set-Content C:\OpsIntel-Staging\bundle\NPM_VERSION.txt
npm ci --cache C:\OpsIntel-Staging\bundle\npm-cache
npm run build
```

Keep the Git bundle, wheelhouse, requirements file, npm cache, version notes, and checksum manifest together. Do not include `.env`, `.venv`, `node_modules`, runtime databases, Git mirrors, Ollama model weights, or credentials. Create/check the same SHA-256 manifest procedure as in [the offline deployment guide](windows-offline-deployment.md#4-assemble-the-offline-bundle).

## 2. Transfer and Prepare the Offline PC

Verify the bundle hash manifest through your approved media process. Clone the source from the Git bundle so the offline working copy has the full commit history:

```powershell
New-Item -ItemType Directory -Force C:\OpsIntel\source | Out-Null
git clone E:\bundle\OpsIntel.bundle C:\OpsIntel\source\OpsIntel
Set-Location C:\OpsIntel\source\OpsIntel
git status --short --branch
```

The cloned `origin` points to the local bundle file, not GitHub. Do not expect `git push` to work from the disconnected machine; use the return-bundle workflow below.

Install development dependencies entirely from local cache/wheels:

```powershell
Set-Location C:\OpsIntel\source\OpsIntel\backend
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --no-index `
  --find-links E:\bundle\python\wheelhouse `
  -r E:\bundle\python\requirements-dev.txt
& .\.venv\Scripts\python.exe -m pip check
```

Install frontend packages in offline mode from the staged npm cache. Keep Node/npm at the versions recorded in the bundle:

```powershell
Set-Location C:\OpsIntel\source\OpsIntel\frontend
node --version
npm --version
New-Item -ItemType Directory -Force C:\OpsIntel\install | Out-Null
Copy-Item E:\bundle\npm-cache C:\OpsIntel\install\npm-cache -Recurse
npm ci --offline --cache C:\OpsIntel\install\npm-cache
```

If npm reports a missing cached package, stop and refresh the npm cache on the staging PC; do not remove `--offline` on the isolated PC.

## 3. Configure and Develop

Create a new local `backend\.env`; never transfer the staging PC's `.env`. Point it at the **internal servers** and a local development data directory:

```dotenv
OPSINTEL_DATA_DIR=C:/OpsIntel/dev-data
API_HOST=127.0.0.1
API_PORT=8000
GITEA_URL=http://<internal-gitea-host>:<port>
GITEA_TOKEN=<enter-the-read-capable-token-locally>
OLLAMA_BASE_URL=http://<internal-ollama-host>:11434
OLLAMA_CHAT_MODEL=<exact-Qwen3-tag-from-the-server>
AI_ENABLED=true
AI_DAILY_REQUEST_LIMIT=20
SEMANTIC_SEARCH_ENABLED=true
OLLAMA_EMBED_MODEL=<exact-nomic-embed-text-tag-from-the-server>
LOCAL_REPO_ALLOWED_ROOTS=["C:/OpsIntel/repos"]
```

Enter credentials locally. The offline PC still needs internal network routes, DNS, and any required internal CA certificates to reach Gitea/Ollama. Keep OpsIntel bound to loopback.

Open three PowerShell windows from the source checkout:

Worker:

```powershell
Set-Location C:\OpsIntel\source\OpsIntel\backend
.\.venv\Scripts\python.exe -c "from opsintel.cli import app; app()" worker
```

API:

```powershell
Set-Location C:\OpsIntel\source\OpsIntel\backend
.\.venv\Scripts\python.exe -m uvicorn opsintel.main:app --host 127.0.0.1 --port 8000
```

Frontend dev server:

```powershell
Set-Location C:\OpsIntel\source\OpsIntel\frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. To run checks and produce the bundled frontend while offline:

```powershell
Set-Location C:\OpsIntel\source\OpsIntel\backend
.\.venv\Scripts\python.exe -m ruff check opsintel tests
.\.venv\Scripts\python.exe -m pytest -q
Set-Location ..\frontend
npm run build
```

All Python dependencies and npm packages must already be in their offline stores before running these commands.

## 4. Return Offline Changes to GitHub

Create a branch for offline work and commit normally:

```powershell
Set-Location C:\OpsIntel\source\OpsIntel
git switch -c offline-work
# edit, test, and commit changes locally
git add -A
git commit -m "Describe offline development changes"
```

Create a bundle containing commits made after the recorded base `master` commit:

```powershell
New-Item -ItemType Directory -Force E:\return | Out-Null
git bundle create E:\return\OpsIntel-offline-changes.bundle master..offline-work
git bundle verify E:\return\OpsIntel-offline-changes.bundle
```

Transfer the return bundle to the online staging PC. There, fetch it into a review branch, inspect and test the changes, then merge and push through the normal approved GitHub process:

```powershell
Set-Location C:\OpsIntel-Staging\OpsIntel
git fetch E:\return\OpsIntel-offline-changes.bundle offline-work:offline-work
git log --oneline master..offline-work
git diff --stat master...offline-work
# Review, test, then merge/push using the team's normal workflow.
```

Never transfer `.env`, tokens, session databases, private keys, runtime indexes, or Ollama model data in the return bundle.

## Offline Development Checklist

- [ ] The Git bundle contains the intended base commit and branches.
- [ ] Python 3.12.8 x64 dev wheels are staged, including pytest, Ruff, and test fixtures' dependencies.
- [ ] The npm cache was populated with `npm ci` and corresponds to the target Node/npm versions.
- [ ] No internet fallback is used by pip or npm on the offline PC.
- [ ] The offline working copy has a new local `.env` pointing to the internal services.
- [ ] Tests, lint, and frontend build pass with public internet disconnected.
- [ ] Offline commits are exported as a return bundle and reviewed on staging before GitHub push.
