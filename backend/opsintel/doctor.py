import asyncio
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import psutil

from opsintel import gitops, ollama
from opsintel.config import Settings
from opsintel.gitea import GiteaClient, GiteaError
from opsintel.parsers.pdf import find_tesseract
from opsintel.parsers.word import find_libreoffice


@dataclass
class Check:
    name: str
    level: str  # OK | WARN | FAIL
    detail: str


def run_checks(settings: Settings) -> list[Check]:
    checks: list[Check] = []

    py = sys.version_info
    checks.append(Check("python", "OK" if (3, 12) <= py[:2] < (3, 14) else "FAIL",
                        f"{platform.python_version()} ({sys.executable})"))
    checks.append(Check("platform", "OK", f"{platform.system()} {platform.release()} {platform.machine()}"))

    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        checks.append(Check("sqlite", "OK", f"{sqlite3.sqlite_version} with FTS5 + trigram"))
    except sqlite3.Error as exc:
        checks.append(Check("sqlite", "FAIL", f"{sqlite3.sqlite_version}: {exc} (need >= 3.34 with FTS5)"))

    git = shutil.which("git")
    if git:
        out = subprocess.run([git, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        ok = gitops.git_version() >= gitops.MIN_GIT_VERSION
        checks.append(Check("git", "OK" if ok else "FAIL",
                            out if ok else f"{out} (need >= {'.'.join(map(str, gitops.MIN_GIT_VERSION))})"))
    else:
        checks.append(Check("git", "FAIL", "git not found on PATH (required for Gitea sync)"))

    if settings.gitea_url:
        try:
            with GiteaClient(settings) as g:
                version, user = g.version(), g.current_user()
            role = "admin" if user.get("is_admin") else "user"
            checks.append(Check("gitea", "OK", f"{settings.gitea_url} v{version}, token user '{user.get('login')}'"
                                               f" ({role})"))
        except GiteaError as exc:
            checks.append(Check("gitea", "FAIL", f"{settings.gitea_url}: {exc}"))
    else:
        checks.append(Check("gitea", "WARN", "GITEA_URL not set (only local folders can be indexed)"))
    if settings.gitea_url and not settings.gitea_webhook_secret.get_secret_value():
        checks.append(Check("webhook", "WARN", "GITEA_WEBHOOK_SECRET not set; push webhooks are rejected, "
                                               "changes are picked up by polling only"))

    data_dir = settings.opsintel_data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=data_dir):
            pass
        free_gb = shutil.disk_usage(data_dir).free / 1024**3
        checks.append(Check("data_dir", "OK" if free_gb > 5 else "WARN",
                            f"{data_dir.resolve()} ({free_gb:.1f} GB free)"))
    except OSError as exc:
        checks.append(Check("data_dir", "FAIL", f"{data_dir}: {exc}"))

    soffice = find_libreoffice(settings.libreoffice_path)
    checks.append(Check("libreoffice", "OK" if soffice else "WARN",
                        soffice or "not found; legacy .doc files are recorded as unsupported (set LIBREOFFICE_PATH)"))
    tesseract = find_tesseract(settings.tesseract_path)
    if tesseract:
        detail = f"{tesseract}; OCR {'enabled' if settings.ocr_enabled else 'disabled (set OCR_ENABLED=true)'}"
        checks.append(Check("tesseract", "OK" if settings.ocr_enabled else "WARN", detail))
    else:
        level = "FAIL" if settings.ocr_enabled else "WARN"
        detail = "not found; set TESSERACT_PATH or add it to PATH" if settings.ocr_enabled \
            else "not found; optional unless OCR_ENABLED=true"
        checks.append(Check("tesseract", level, detail))
    try:
        import pymupdf

        checks.append(Check("pymupdf", "OK", f"PyMuPDF {pymupdf.VersionBind} (AGPL-3.0 licensed)"))
    except ImportError as exc:
        checks.append(Check("pymupdf", "FAIL", f"PDF parsing unavailable: {exc}"))

    vm = psutil.virtual_memory()
    avail_mb = vm.available / 1024**2
    checks.append(Check("memory", "OK" if avail_mb > settings.worker_min_free_ram_mb else "WARN",
                        f"{vm.total / 1024**3:.1f} GB total, {avail_mb / 1024:.1f} GB available"))

    if not settings.ai_enabled:
        checks.append(Check("ollama", "OK", "AI disabled (AI_ENABLED=false)"))
    else:
        st = asyncio.run(ollama.status(settings.ollama_base_url, settings.ollama_chat_model,
                                       settings.ollama_min_version))
        if not st["reachable"]:
            checks.append(Check("ollama", "WARN", f"{settings.ollama_base_url} unreachable: {st['error']}"))
        else:
            level = "OK" if st["version_ok"] and st["model_present"] else "WARN"
            detail = f"version {st['version']} (min {settings.ollama_min_version}), model " \
                     f"'{st['model']}' {'present' if st['model_present'] else 'MISSING'}"
            checks.append(Check("ollama", level, detail))
    return checks
