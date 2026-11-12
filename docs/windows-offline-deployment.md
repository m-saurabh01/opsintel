# OpsIntel Offline Windows Deployment

This runbook prepares a complete, repeatable bundle on an **online Windows staging PC**, transfers it to an **offline Windows 10/11 x64 PC**, and installs OpsIntel without public-network access. The staging PC must use the same Windows architecture and Python minor version as the target.

## What Runs on the Offline PC

- Python 3.12 or 3.13 x64 and the OpsIntel backend.
- Git for Windows only if the offline PC can reach an internal Gitea server and will sync from it. Local-folder indexing does not require Git.
- Ollama plus locally transferred model files if AI is required.
- The prebuilt React frontend served by FastAPI. Node.js, npm, Vite, and `node_modules` are **not** needed on the target.
- SQLite is included with Python; no database server is required.

If the offline PC has **no network path to Gitea**, do not configure Gitea polling there. Transfer working-tree copies of repositories and index them as local folders instead. Ollama runs locally; no external AI endpoint is used.

## 1. Prepare the Staging PC

Use an online Windows 10/11 x64 machine. Install these staging tools:

- Git for Windows.
- Python 3.12 x64 (recommended to match production) or 3.13 x64.
- uv.
- Node.js 22.12+ and npm.
- Ollama only if you will stage local models.

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

Use a clean checkout of the exact approved commit. Include submodules and Git LFS objects if the repositories require them:

```powershell
git clone --recurse-submodules <OPSINTEL_GITHUB_URL> C:\OpsIntel-Staging\OpsIntel
Set-Location C:\OpsIntel-Staging\OpsIntel
git checkout <APPROVED_COMMIT>
git submodule update --init --recursive
```

For each source repository to carry to a fully disconnected target, populate all required files first. For example, clone it recursively, check out the approved branch/commit, and run `git lfs pull` when applicable. Do not copy a developer's live `backend\data` directory or `.env` into the deployment bundle.

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

## 3. Stage Windows Installers and Ollama Models

Download the official, signed Windows installers into `bundle\installers` and record their versions:

- Python 3.12 x64 installer.
- Git for Windows x64 installer if Gitea sync is required on the target.
- Ollama for Windows installer if local AI is required.
- Tesseract installer plus English language data only if scanned-PDF OCR is required.
- LibreOffice installer only if legacy `.doc` or `.ppt` extraction is required.

On the staging PC, install the approved chat and (optionally) embedding models into Ollama and verify the actual tags:

```powershell
ollama pull <APPROVED_CHAT_MODEL_TAG>
ollama pull <APPROVED_EMBEDDING_MODEL_TAG> # optional
ollama list
```

Copy the **entire Ollama model store**, not just the large model blob; manifests and related blobs are needed. Ollama's default Windows model store is `%USERPROFILE%\.ollama\models`. Stop/exit Ollama completely before copying it. Use the built-in Windows `tar.exe` to avoid ZIP size limitations on multi-gigabyte model files:

```powershell
New-Item -ItemType Directory -Force C:\OpsIntel-Staging\bundle\ollama | Out-Null
tar.exe -cf C:\OpsIntel-Staging\bundle\ollama\models.tar `
  -C $env:USERPROFILE\.ollama models
```

Do not include model files unless AI/semantic search is required. Model files can be several gigabytes.

## 4. Assemble the Offline Bundle

A suggested bundle layout:

```text
bundle\
  app\OpsIntel\                 # approved source checkout and built static frontend
  python\requirements.txt
  python\wheelhouse\             # runtime wheels and OpsIntel wheel
  installers\                    # official Windows installers needed at the target
  ollama\models.tar               # optional, whole Ollama model store
  repositories\                   # optional working trees for fully disconnected use
  SHA256SUMS.txt
```

Copy the source checkout while excluding developer state and secrets. For example, from the staging PC:

```powershell
robocopy C:\OpsIntel-Staging\OpsIntel C:\OpsIntel-Staging\bundle\app\OpsIntel /E `
  /XD .git .venv node_modules data /XF .env
```

`robocopy` exit codes 0 through 7 indicate success or success with differences; 8 or greater indicates a copy failure. Ensure `backend\opsintel\static` was copied. Copy offline repository working trees under `bundle\repositories\<name>\` if no Gitea server will be reachable.

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
  Copy-Item E:\bundle\repositories C:\OpsIntel\repos -Recurse
}
if (Test-Path E:\bundle\ollama\models.tar) {
  Copy-Item E:\bundle\ollama\models.tar C:\OpsIntel\install\ollama\models.tar
}
```

Run required installers from `C:\OpsIntel\install\installers` before ejecting the media. Budget disk space for repository working copies or Git mirrors, the SQLite index/cache, the complete Ollama model store, and at least one backup; installed model size can exceed the archive size.

## 6. Install on the Offline PC

Install from the copied installers. Use the same Python architecture/version as the staging machine. Install Git, Ollama, Tesseract, or LibreOffice only if they are in scope. Node.js and uv are not required on the target when installing from the wheelhouse and serving the prebuilt UI.

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

Create `C:\OpsIntel\app\OpsIntel\backend\.env` from `.env.example`, then edit it for this machine. Do not copy the staging `.env`. Example for a fully disconnected PC indexing local copies:

```dotenv
OPSINTEL_DATA_DIR=C:/OpsIntel/data
API_HOST=127.0.0.1
API_PORT=8000
LOCAL_REPO_ALLOWED_ROOTS=["C:/OpsIntel/repos"]
AI_ENABLED=true
AI_DAILY_REQUEST_LIMIT=20
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=<EXACT_TAG_FROM_OLLAMA_LIST>
SEMANTIC_SEARCH_ENABLED=false
OCR_ENABLED=false
```

For a machine that can reach an **internal, offline Gitea service**, set `GITEA_URL` to that internal address and provision a least-privilege token locally in `.env`. If there is no Gitea network route, leave `GITEA_URL` empty and add the transferred working trees as local repositories. Enable semantic search only when an embedding model was bundled and its exact tag is configured. Enable OCR only when Tesseract and its English data were installed.

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

- [ ] Windows x64 staging OS matches the target's architecture and Python minor version.
- [ ] Approved OpsIntel commit is recorded; required submodules and LFS files are present.
- [ ] Frontend was built and `backend\opsintel\static` is in the bundle.
- [ ] `uv.lock` was exported with `--locked`; Windows wheels were downloaded for Python 3.12/3.13 x64.
- [ ] OpsIntel wheel and all runtime wheels are in the bundle.
- [ ] Required official Windows installers and versions are recorded.
- [ ] Required Ollama model tags are listed; the whole model store is copied if AI is required.
- [ ] Repository working trees are copied if no internal Gitea will be reachable.
- [ ] `.env`, `.venv`, `node_modules`, developer databases, credentials, and tokens are excluded.
- [ ] SHA-256 manifest is created and verified after transfer.

### Offline PC

- [ ] Python and optional Git/Ollama/Tesseract/LibreOffice installers came from trusted sources and are installed as needed.
- [ ] Python virtual environment was created locally; no staging `.venv` was copied.
- [ ] Pip installed the project wheel/dependencies with `--no-index` from the wheelhouse.
- [ ] `.env` was created locally with the correct data path, allowed roots, and model tags; secrets were entered locally.
- [ ] Ollama model tags match `OLLAMA_CHAT_MODEL` and optional `OLLAMA_EMBED_MODEL`.
- [ ] API binds only to `127.0.0.1`; no public or LAN bind/firewall rule was enabled.
- [ ] `opsintel doctor`, `/api/health`, a repository search, and worker status pass with public networking disconnected.
- [ ] A first-admin account is created on the target; no staging user/session database was copied.
- [ ] Backup location and access protection for `OPSINTEL_DATA_DIR` are documented.
