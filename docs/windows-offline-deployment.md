# OpsIntel Offline Windows Deployment

This runbook prepares OpsIntel on your **online Windows staging PC** and transfers it to your **offline Windows PC** without installing duplicate infrastructure.

This document covers installing/running OpsIntel on the target. For editing code, running tests/builds without internet, and returning commits to GitHub, use the [offline Windows development guide](windows-offline-development.md).

Your stated environment is:

- **Staging PC:** uv, Python, Node, Ollama, models, and project dependencies already present.
- **Offline PC:** Python 3.12.8, Node 22, and Git already installed.
- **Separate internal servers:** Gitea with its MySQL database, and Ollama with Qwen3 and nomic-embed-text models.

The recommended bundle contains only the approved OpsIntel checkout with the built frontend, a Windows/Python 3.12 wheelhouse, and checksums. The offline PC connects to the existing Gitea and Ollama servers over the internal network. Do not copy Gitea, MySQL, Ollama, or GGUF files for this topology.

## What Runs on the Offline PC

- Python 3.12.8 x64 and the OpsIntel backend, installed from the transferred wheelhouse.
- The prebuilt React frontend served by FastAPI. Node.js is already present, but the target does not need to run npm/Vite.
- Git for Windows, already present, for Gitea-backed clone/fetch operations.
- Ollama and its Qwen3/nomic-embed-text models remain on the separate internal Ollama server. The target needs network access to that server, not local Ollama or GGUF files.
- The separate Gitea server, with MySQL remaining behind Gitea. OpsIntel talks to Gitea's HTTP/API and Git endpoints; it does not connect to Gitea's MySQL database.
- SQLite is included with Python; no database server is required.

This assumes the offline PC can reach the internal Gitea and Ollama servers. If it cannot reach Gitea, transfer repository working trees and index them as local folders. Only if it also cannot reach Ollama should you install a local Ollama service and transfer its complete model store.

## 1. Prepare the Staging PC

Use the online Windows 10/11 x64 PC you already have. Since the target is Python 3.12.8 x64, build the wheelhouse using Windows Python 3.12 x64. You already have the required staging tools; verify their versions rather than reinstalling them:

- Git for Windows, to clone the approved OpsIntel commit.
- Python 3.12 x64, matching the target's 3.12.8 installation.
- uv.
- Node.js 22.12+ and npm.

Do not install or package another Gitea/MySQL server, Ollama, Node, Python, or model weights for the target in your current topology. Tesseract and LibreOffice are optional and only need packaging if the target must process scanned PDFs or legacy DOC/PPT files and they are not already installed there.

Record the versions and the OpsIntel Git commit being packaged:

```powershell
git --version
py -3.12 --version
uv --version
node --version
npm --version
Set-Location C:\path\to\OpsIntel
git rev-parse HEAD
```

Use a clean checkout of the pushed `master` branch (or pin an approved commit for a reproducible release). Include submodules and Git LFS objects if the OpsIntel checkout requires them:

```powershell
git clone --recurse-submodules --branch master <OPSINTEL_GITHUB_URL> C:\OpsIntel-Staging\OpsIntel
Set-Location C:\OpsIntel-Staging\OpsIntel
git rev-parse HEAD | Set-Content C:\OpsIntel-Staging\OPSINTEL_COMMIT.txt
git submodule update --init --recursive
```

You do not need to clone the application repositories onto the staging PC for transfer when the offline PC can reach the internal Gitea server. Do not copy a developer's live `backend\data` directory or `.env` into the deployment bundle.

## 2. Build the Frontend and Python Artifacts

Build the frontend on the staging PC so the target does not need Node or npm:

```powershell
Set-Location C:\OpsIntel-Staging\OpsIntel\frontend
npm ci
npm run build
```

Confirm the generated files exist under `backend\opsintel\static` before continuing.

Create a clean bundle directory, then export the locked runtime Python dependencies and build the OpsIntel wheel. Run these commands on **Windows with the target Python version/architecture**, so the wheelhouse contains compatible Windows wheels:

```powershell
New-Item -ItemType Directory -Force C:\OpsIntel-Staging\bundle\python\wheelhouse | Out-Null
Set-Location C:\OpsIntel-Staging\OpsIntel\backend
uv export --locked --no-dev --no-emit-project --format requirements-txt `
  --output-file C:\OpsIntel-Staging\bundle\python\requirements.txt
uv build --wheel --out-dir C:\OpsIntel-Staging\bundle\python\wheelhouse
py -3.12 -m pip download --only-binary=:all: `
  --dest C:\OpsIntel-Staging\bundle\python\wheelhouse `
  -r C:\OpsIntel-Staging\bundle\python\requirements.txt
```

The `--only-binary` download is intentional: it fails on the staging PC if any runtime package lacks a compatible wheel, rather than discovering a compiler/build dependency on the offline PC. Resolve that before transfer. Do not use the staging PC's `.venv` as the deployment environment; virtual environments are not portable.

## 3. Optional Fallback Installers and Models

For your stated setup, **skip this section**: Python, Node, and Git are already on the target, while Gitea/MySQL and Ollama with Qwen3/nomic-embed-text are on separate internal servers. Do not copy their installers, database, Ollama service, or GGUF files into the default bundle.

Only if a target dependency is missing and cannot be installed by your normal IT process, download its official Windows installer on the staging PC and add it to `bundle\installers`. Tesseract plus English data is only needed for scanned-PDF OCR; LibreOffice is only needed for legacy `.doc`/`.ppt` parsing.

Only if the target cannot reach the Ollama server should you install Ollama locally. In that case, verify the approved model tags with `ollama list`, stop Ollama, and archive its complete model store (manifests and blobs), not only the GGUF file. Model weights can be several gigabytes.

## 4. Assemble the Offline Bundle

A suggested bundle layout:

```text
bundle\
  app\OpsIntel\                 # approved source checkout and built static frontend
  python\requirements.txt
  python\wheelhouse\             # runtime wheels and OpsIntel wheel
  installers\                    # optional fallback installers only
  ollama\models.tar               # only if the target cannot reach Ollama
  repositories\                   # only if the target cannot reach Gitea
  SHA256SUMS.txt
```

Copy the source checkout while excluding developer state and secrets. For example, from the staging PC:

```powershell
robocopy C:\OpsIntel-Staging\OpsIntel C:\OpsIntel-Staging\bundle\app\OpsIntel /E `
  /XD .git .venv node_modules data /XF .env
```

`robocopy` exit codes 0 through 7 indicate success or success with differences; 8 or greater indicates a copy failure. Ensure `backend\opsintel\static` was copied. With your current topology, omit `repositories\` and `ollama\models.tar`; the target will use the separate internal Gitea and Ollama servers. Add local working trees/model files only if those servers will not be reachable from the target.

Create a hash manifest after the bundle is complete:

```powershell
Get-ChildItem C:\OpsIntel-Staging\bundle -File -Recurse |
  Get-FileHash -Algorithm SHA256 |
  ForEach-Object { "$($_.Hash)  $($_.Path.Substring('C:\OpsIntel-Staging\bundle\'.Length))" } |
  Set-Content C:\OpsIntel-Staging\bundle\SHA256SUMS.txt
```

Transfer the bundle over approved removable media. Scan the media and verify hashes after copying to the offline PC. Do not include passwords, Gitea tokens, private keys, a populated developer database, or an active developer `.env` in the bundle.

## 5. Copy from Removable Media

Assume the approved media mounts as `E:`. Compare the manifest's own SHA-256 through a separate trusted channel, then verify every bundled file against the manifest before installation. The removable media must not be its own trust anchor.

Print the manifest hash and compare it with the value sent over a separate trusted channel:

```powershell
(Get-FileHash E:\bundle\SHA256SUMS.txt -Algorithm SHA256).Hash
```

Then run the following from PowerShell to check every manifest entry; it stops on the first mismatch:

```powershell
$bundle = 'E:\bundle'
foreach ($line in Get-Content (Join-Path $bundle 'SHA256SUMS.txt')) {
  if ($line -match '^([0-9A-Fa-f]{64})\s+(.+)$') {
    $expected = $Matches[1]
    $path = Join-Path $bundle $Matches[2]
    $actual = (Get-FileHash $path -Algorithm SHA256).Hash
    if ($actual -ne $expected) { throw "Hash mismatch: $path" }
  }
}
```

Copy the app, Python wheelhouse, requirements file, and optional models to local fixed storage:

```powershell
New-Item -ItemType Directory -Force C:\OpsIntel\app, C:\OpsIntel\install, `
  C:\OpsIntel\install\python, C:\OpsIntel\install\ollama | Out-Null
Copy-Item E:\bundle\app\OpsIntel C:\OpsIntel\app\OpsIntel -Recurse
Copy-Item E:\bundle\python\wheelhouse C:\OpsIntel\install\python\wheelhouse -Recurse
Copy-Item E:\bundle\python\requirements.txt C:\OpsIntel\install\python\requirements.txt
if (Test-Path E:\bundle\installers) {
  Copy-Item E:\bundle\installers C:\OpsIntel\install\installers -Recurse
}
if (Test-Path E:\bundle\repositories) {
  Copy-Item E:\bundle\repositories\* C:\OpsIntel\repos -Recurse
}
if (Test-Path E:\bundle\ollama\models.tar) {
  Copy-Item E:\bundle\ollama\models.tar C:\OpsIntel\install\ollama\models.tar
}
```

Run required installers from `C:\OpsIntel\install\installers` before ejecting the media. Budget disk space for repository working copies or Git mirrors, the SQLite index/cache, the complete Ollama model store, and at least one backup; installed model size can exceed the archive size.

## 6. Install on the Offline PC

Verify the existing target runtimes before installing anything: Python should report 3.12.8 x64, Node 22.x, and Git should run from PowerShell. Do not reinstall Python, Node, Git, Gitea, MySQL, or Ollama for the current topology. Node is not needed to run the prebuilt UI, and `uv` is not needed on the target.

The app and installer files were copied in the previous step. Create the runtime data directories:

```powershell
New-Item -ItemType Directory -Force C:\OpsIntel\data, C:\OpsIntel\repos | Out-Null
```

Create a fresh virtual environment and install only from the copied local wheelhouse:

```powershell
Set-Location C:\OpsIntel\app\OpsIntel\backend
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --no-index `
  --find-links C:\OpsIntel\install\python\wheelhouse `
  -r C:\OpsIntel\install\python\requirements.txt `
  C:\OpsIntel\install\python\wheelhouse\opsintel-0.1.0-py3-none-any.whl
& .\.venv\Scripts\python.exe -m pip check
```

If the wheel filename differs, use the actual `opsintel-*.whl` file in the wheelhouse. `--no-index` prevents pip from contacting a package index. If installation reports a missing distribution, stop and rebuild the Windows wheelhouse on the staging PC; do not remove `--no-index` on the offline target.

## 7. Restore Models and Configure the Target

If transferring Ollama models, install and start Ollama once, stop it, and extract the model store into the target account's default location:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ollama" | Out-Null
tar.exe -xf C:\OpsIntel\install\ollama\models.tar -C "$env:USERPROFILE\.ollama"
```

Start Ollama and verify the transferred tags:

```powershell
ollama list
```

Create `C:\OpsIntel\app\OpsIntel\backend\.env` from `.env.example`, then enter the internal service addresses and token locally. Do not copy the staging `.env` or put the token in the transfer bundle. Example for your topology:

```dotenv
OPSINTEL_DATA_DIR=C:/OpsIntel/data
API_HOST=127.0.0.1
API_PORT=8000
LOCAL_REPO_ALLOWED_ROOTS=["C:/OpsIntel/repos"]
AI_ENABLED=true
AI_DAILY_REQUEST_LIMIT=20
GITEA_URL=http://<internal-gitea-host>:<port>
GITEA_TOKEN=<enter-the-read-capable-token-locally>
OLLAMA_BASE_URL=http://<internal-ollama-host>:11434
OLLAMA_CHAT_MODEL=<exact-Qwen3-tag-from-the-Ollama-server>
SEMANTIC_SEARCH_ENABLED=true
OLLAMA_EMBED_MODEL=<exact-nomic-embed-text-tag-from-the-Ollama-server>
OCR_ENABLED=false
```

Replace every angle-bracket placeholder with your actual internal host, port, or exact model tag. `GITEA_URL` is the server root (OpsIntel appends `/api/v1`); the token must be read-capable for the repositories to be indexed. Ollama must expose its API to the offline PC. Keep `API_HOST=127.0.0.1`; do not expose OpsIntel itself to the LAN. If the offline PC cannot reach Gitea, leave `GITEA_URL` blank and index transferred local working trees. If it cannot reach Ollama, use the local-Ollama fallback in section 3. Enable OCR only if Tesseract and its English data are installed.

Before starting OpsIntel, test internal service reachability from the offline PC (replace hosts/ports):

```powershell
Test-NetConnection <internal-gitea-host> -Port <gitea-port>
Test-NetConnection <internal-ollama-host> -Port 11434
Invoke-RestMethod http://<internal-gitea-host>:<gitea-port>/api/v1/version
Invoke-RestMethod http://<internal-ollama-host>:11434/api/tags
```

## 8. Start and Verify

Use separate PowerShell windows. The working directory must be `backend` so `.env` is found.

Worker:

```powershell
Set-Location C:\OpsIntel\app\OpsIntel\backend
.\.venv\Scripts\opsintel.exe worker
```

API:

```powershell
Set-Location C:\OpsIntel\app\OpsIntel\backend
.\.venv\Scripts\opsintel.exe doctor
.\.venv\Scripts\opsintel.exe serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, create the first administrator, then add a transferred local repository or register an internal Gitea repository. Verify the app while disconnected from public internet:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
.\.venv\Scripts\opsintel.exe repos
.\.venv\Scripts\opsintel.exe jobs status
```

The health endpoint should report the database/search available and the worker alive. Exact/lexical search must work even if Ollama is disabled. Try one repository search and one AI question only if the chat model was included.

## 9. Final Offline Checklist

### Staging PC

- [ ] Windows x64 staging OS and Python 3.12 match the target's architecture/version.
- [ ] Approved OpsIntel commit is recorded; required submodules and LFS files are present.
- [ ] Frontend was built and `backend\opsintel\static` is in the bundle.
- [ ] `uv.lock` was exported with `--locked`; Windows wheels were downloaded for Python 3.12/3.13 x64.
- [ ] OpsIntel wheel and all runtime wheels are in the bundle.
- [ ] Only genuinely missing target installers are included; do not duplicate Python, Git, Node, Gitea/MySQL, or Ollama for the stated setup.
- [ ] The expected Qwen3 and nomic-embed-text tags are confirmed on the internal Ollama server; no GGUF/model store is copied for the normal setup.
- [ ] Repository working trees are copied only if the offline PC cannot reach internal Gitea.
- [ ] `.env`, `.venv`, `node_modules`, developer databases, credentials, and tokens are excluded.
- [ ] SHA-256 manifest is created and verified after transfer.

### Offline PC

- [ ] Existing Python 3.12.8, Node 22, and Git are verified; no unnecessary duplicate installers are run.
- [ ] Internal Gitea and Ollama hostnames resolve and their service ports are reachable from the target.
- [ ] Python virtual environment was created locally; no staging `.venv` was copied.
- [ ] Pip installed the project wheel/dependencies with `--no-index` from the wheelhouse.
- [ ] `.env` was created locally with the correct data path, allowed roots, and model tags; secrets were entered locally.
- [ ] `OLLAMA_CHAT_MODEL` and `OLLAMA_EMBED_MODEL` exactly match tags reported by the internal Ollama server.
- [ ] API binds only to `127.0.0.1`; no public or LAN bind/firewall rule was enabled.
- [ ] `opsintel doctor`, `/api/health`, a repository search, and worker status pass with public networking disconnected.
- [ ] A first-admin account is created on the target; no staging user/session database was copied.
- [ ] Backup location and access protection for `OPSINTEL_DATA_DIR` are documented.
