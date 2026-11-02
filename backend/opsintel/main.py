import asyncio
import hashlib
import hmac
import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from opsintel import __version__, jobs, ollama
from opsintel.ai_queue import AIQueueFull, AIQueueRunner, enqueue_question
from opsintel.config import Settings, get_settings
from opsintel.db import connect, migrate
from opsintel.gitops import GitError
from opsintel.locations import cells, heading, label, locate
from opsintel.search import InvalidQuery, SearchRequest, search
from opsintel.tasks import PRIORITY_WEBHOOK, enqueue_repo_sync, get_setting, indexing_paused

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
WEBHOOK_MAX_BYTES = 5 * 1024 * 1024
WORKER_STALE_S = 60
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    repo_ids: list[int] | None = Field(default=None, max_length=100)


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request) -> dict:
    s: Settings = request.app.state.settings
    conn = connect(s)
    worker = {"alive": False}
    ai_queue = {}
    try:
        conn.execute("SELECT 1 FROM repositories LIMIT 1")
        db = {"ok": True}
        ai_queue = jobs.stats(conn).get("queues", {}).get("ai", {})
        seen = float(get_setting(conn, "worker_seen_at", "0") or 0)
        worker = {"alive": time.time() - seen < WORKER_STALE_S, "paused": indexing_paused(conn),
                  "last_seen_s_ago": round(time.time() - seen) if seen else None}
    except sqlite3.Error as exc:
        db = {"ok": False, "error": str(exc)}
    finally:
        conn.close()
    ai = {"enabled": False} if not s.ai_enabled else {
        "enabled": True, **await ollama.status(s.ollama_base_url, s.ollama_chat_model, s.ollama_min_version)
    }
    ai_task = getattr(request.app.state, "ai_queue_task", None)
    if not s.ai_enabled:
        ai_consumer = {"enabled": False, "running": False}
    elif ai_task is None:
        ai_consumer = {"enabled": True, "running": False, "error": "consumer was not started"}
    elif ai_task.done():
        failure = None if ai_task.cancelled() else ai_task.exception()
        ai_consumer = {"enabled": True, "running": False,
                       "error": type(failure).__name__ if failure else "consumer stopped"}
    else:
        ai_consumer = {"enabled": True, "running": True}
    return {"version": __version__, "db": db, "worker": worker, "ai_queue": ai_queue,
        "features": {"metadata_search": s.metadata_search_enabled},
        "ai": ai, "ai_consumer": ai_consumer, "search_available": db["ok"]}


@router.post("/webhooks/gitea")
async def gitea_webhook(
    request: Request,
    x_gitea_event: Annotated[str, Header()] = "",
    x_gitea_delivery: Annotated[str, Header()] = "",
    x_gitea_signature: Annotated[str, Header()] = "",
) -> dict:
    s: Settings = request.app.state.settings
    secret = s.gitea_webhook_secret.get_secret_value()
    if not secret:
        raise HTTPException(503, "webhook secret is not configured")
    body = await request.body()
    if len(body) > WEBHOOK_MAX_BYTES:
        raise HTTPException(413, "payload too large")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_gitea_signature.strip().lower()):
        raise HTTPException(401, "invalid signature")
    if x_gitea_event != "push":
        return {"status": "ignored", "reason": f"event '{x_gitea_event}' not handled"}
    try:
        payload = json.loads(body)
        ref = payload.get("ref", "")
        gitea_id = int(payload["repository"]["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, "malformed push payload") from exc
    if not ref.startswith("refs/heads/"):
        return {"status": "ignored", "reason": "not a branch push"}
    branch = ref.removeprefix("refs/heads/")

    conn = connect(s)
    try:
        repo = conn.execute("SELECT * FROM repositories WHERE gitea_id = ? AND enabled = 1", (gitea_id,)).fetchone()
        if repo is None:
            return {"status": "ignored", "reason": "repository not registered"}
        if not conn.execute("SELECT 1 FROM repo_branches WHERE repo_id = ? AND branch = ?",
                            (repo["id"], branch)).fetchone():
            return {"status": "ignored", "reason": f"branch '{branch}' not tracked"}
        delivery = x_gitea_delivery or hashlib.sha256(body).hexdigest()
        cur = conn.execute("INSERT OR IGNORE INTO webhook_deliveries(delivery_id, event, repo_full_name) "
                           "VALUES (?, ?, ?)", (delivery, x_gitea_event, repo["name"]))
        if cur.rowcount == 0:
            return {"status": "duplicate", "delivery": delivery}
        try:
            [(job_id, created)] = enqueue_repo_sync(conn, s, repo, branch=branch, priority=PRIORITY_WEBHOOK)
        except jobs.QueueFull as exc:
            conn.execute("DELETE FROM webhook_deliveries WHERE delivery_id = ?", (delivery,))
            raise HTTPException(503, str(exc)) from exc
        conn.execute("UPDATE webhook_deliveries SET job_id = ? WHERE delivery_id = ?", (job_id, delivery))
        return {"status": "queued" if created else "already_queued", "job_id": job_id}
    finally:
        conn.close()


@router.get("/admin/status")
def admin_status(conn: Conn) -> dict:
    repos = [dict(r) for r in conn.execute(
        "SELECT r.id, r.name, r.kind, r.is_private, r.enabled, r.last_indexed_at, b.branch, b.head_sha, "
        "b.indexed_sha, b.indexed_at, b.last_sync_at, b.last_error "
        "FROM repositories r LEFT JOIN repo_branches b ON b.repo_id = r.id ORDER BY r.name, b.branch")]
    files = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM files GROUP BY status")}
    return {"paused": indexing_paused(conn), "repositories": repos, "files": files, "jobs": jobs.stats(conn),
            "recent_jobs": jobs.recent(conn, 20)}


def _require_local_ai(settings: Settings) -> None:
    if settings.api_host.lower() not in LOCAL_HOSTS:
        raise HTTPException(503, "AI is disabled on non-local interfaces until M5 authentication is enabled")


@router.post("/ai/ask", status_code=202)
async def ask_ai(body: AskRequest, request: Request, conn: Conn) -> dict:
    settings: Settings = request.app.state.settings
    _require_local_ai(settings)
    if not settings.ai_enabled:
        raise HTTPException(503, "AI question answering is disabled")
    question = body.question.strip()
    if len(question) < 3:
        raise HTTPException(422, "question must contain at least 3 non-space characters")
    repo_ids = sorted(set(body.repo_ids or [])) or None
    if repo_ids:
        marks = ",".join("?" * len(repo_ids))
        found = {row[0] for row in conn.execute(
            f"SELECT id FROM repositories WHERE enabled = 1 AND id IN ({marks})", repo_ids)}  # noqa: S608
        if found != set(repo_ids):
            raise HTTPException(404, "one or more selected repositories are unavailable")
    status = await ollama.status(settings.ollama_base_url, settings.ollama_chat_model, settings.ollama_min_version)
    if not status.get("reachable"):
        raise HTTPException(503, "Ollama is unavailable")
    if not status.get("version_ok"):
        raise HTTPException(503, f"Ollama {status.get('version')} is older than required {settings.ollama_min_version}")
    if not status.get("model_present"):
        raise HTTPException(503, f"Ollama model '{settings.ollama_chat_model}' is not installed")
    try:
        job_id, _ = enqueue_question(conn, settings, question, repo_ids)
    except AIQueueFull as exc:
        raise HTTPException(429, "AI queue is full; retry when a request finishes") from exc
    return {"job_id": job_id, "status": "queued", "events_url": f"/api/ai/ask/{job_id}/events"}


@router.get("/ai/ask/{job_id}/events")
async def ask_ai_events(job_id: int, request: Request, conn: Conn) -> StreamingResponse:
    if jobs.get(conn, job_id) is None:
        raise HTTPException(404, "AI request not found")

    async def stream():
        last_stage = None
        while True:
            if await request.is_disconnected():
                return
            row = jobs.get(conn, job_id)
            if row is None:
                yield "event: error\ndata: {\"message\":\"AI request not found\"}\n\n"
                return
            if row["progress"]:
                try:
                    stage = json.loads(row["progress"]).get("stage")
                except (TypeError, json.JSONDecodeError):
                    stage = None
                if stage and stage != last_stage:
                    last_stage = stage
                    yield f"event: stage\ndata: {json.dumps({'stage': stage})}\n\n"
            if row["status"] == "done":
                result = json.loads(row["result"] or "{}")
                answer = result.get("answer", "")
                for start in range(0, len(answer), 48):
                    token = json.dumps({"text": answer[start:start + 48]}, ensure_ascii=False)
                    yield f"event: token\ndata: {token}\n\n"
                final = {k: v for k, v in result.items() if k != "answer"}
                yield f"event: done\ndata: {json.dumps(final, ensure_ascii=False)}\n\n"
                return
            if row["status"] in {"dead", "cancelled"}:
                event = "cancelled" if row["status"] == "cancelled" else "error"
                payload = {"message": row["last_error"] or row["status"]}
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                return
            if row["status"] == "queued" and row["attempts"] > 0:
                yield f"event: stage\ndata: {json.dumps({'stage': 'retrying'})}\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })


@router.delete("/ai/ask/{job_id}")
def cancel_ai(job_id: int, conn: Conn) -> dict:
    status = jobs.cancel(conn, job_id)
    if status == "missing":
        raise HTTPException(404, "AI request not found")
    return {"job_id": job_id, "status": status}


@router.get("/repos")
def list_repos(conn: Conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.id, r.name, r.kind, r.default_branch, r.enabled, r.last_indexed_at,
               count(f.id) AS files,
               sum(f.status = 'indexed') AS indexed,
               sum(f.status = 'skipped') AS skipped,
               sum(f.status = 'unsupported') AS unsupported,
               sum(f.status = 'failed') AS failed
        FROM repositories r LEFT JOIN files f ON f.repo_id = r.id
        GROUP BY r.id ORDER BY r.name
        """
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/facets")
def facets(conn: Conn) -> dict:
    types = conn.execute(
        "SELECT file_type, count(*) n FROM files WHERE status = 'indexed' GROUP BY file_type ORDER BY n DESC"
    ).fetchall()
    langs = conn.execute(
        "SELECT language, count(*) n FROM files WHERE status = 'indexed' AND language IS NOT NULL "
        "GROUP BY language ORDER BY n DESC"
    ).fetchall()
    return {"file_types": [dict(r) for r in types], "languages": [dict(r) for r in langs]}


@router.get("/search")
def search_endpoint(
    request: Request,
    conn: Conn,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    mode: Annotated[str, Query(pattern="^(fulltext|phrase|exact|metadata)$")] = "fulltext",
    repo: Annotated[list[int] | None, Query()] = None,
    branch: str | None = None,
    type: Annotated[list[str] | None, Query()] = None,  # noqa: A002
    lang: Annotated[list[str] | None, Query()] = None,
    path: Annotated[str | None, Query(max_length=1000)] = None,
    case_sensitive: bool = False,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 20,
) -> dict:
    s: Settings = request.app.state.settings
    if mode == "metadata":
        if not s.metadata_search_enabled:
            raise HTTPException(503, "metadata search is disabled")
        if not s.metadata_search_path.is_file():
            raise HTTPException(503, "metadata shadow index is missing; run `opsintel experimental metadata-index`")
        from opsintel.experiments.metadata_search import MetadataShadowIndex

        shadow = MetadataShadowIndex(s.metadata_search_path)
        try:
            result = shadow.search(
                q, mode="fulltext", repo_ids=repo, branch=branch, file_types=type, languages=lang,
                path_prefix=path, page=page, page_size=min(page_size, s.search_page_size_max),
            )
            result["mode"] = "metadata"
            return result
        except InvalidQuery as exc:
            raise HTTPException(400, str(exc)) from exc
        except sqlite3.OperationalError as exc:
            raise HTTPException(503, f"metadata shadow index is unavailable: {exc}") from exc
        finally:
            shadow.close()
    req = SearchRequest(
        q=q, mode=mode, repo_ids=repo, branch=branch, file_types=type, languages=lang, path_prefix=path,
        case_sensitive=case_sensitive, page=page, page_size=min(page_size, s.search_page_size_max),
    )
    try:
        return search(conn, req)
    except InvalidQuery as exc:
        raise HTTPException(400, str(exc)) from exc
    except sqlite3.OperationalError as exc:
        raise HTTPException(400, f"invalid search expression: {exc}") from exc


def _file_row(conn: sqlite3.Connection, file_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT f.*, r.name AS repo_name, r.kind AS repo_kind, r.location AS repo_location FROM files f "
        "JOIN repositories r ON r.id = f.repo_id WHERE f.id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "file not found")
    return row


@router.get("/files/{file_id}")
def get_file(file_id: int, conn: Conn) -> dict:
    row = dict(_file_row(conn, file_id))
    row.pop("mtime_ns", None)
    row.pop("repo_kind", None)
    row.pop("repo_location", None)
    return row


@router.get("/files/{file_id}/raw.pdf")
def get_pdf(file_id: int, request: Request, conn: Conn) -> Response:
    f = _file_row(conn, file_id)
    if f["status"] != "indexed" or f["language"] != "pdf":
        raise HTTPException(415, "only indexed PDF files can be opened as PDF")
    settings: Settings = request.app.state.settings
    if f["size"] > settings.max_file_size_bytes:
        raise HTTPException(413, "PDF exceeds the configured file-size limit")

    if f["repo_kind"] == "local":
        try:
            root = Path(f["repo_location"]).resolve(strict=True)
            relative = PurePosixPath(f["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise HTTPException(404, "indexed PDF source is no longer available")
            source = root
            for part in relative.parts:
                source = source / part
                if source.is_symlink():
                    raise HTTPException(404, "indexed PDF source is no longer available")
            source = source.resolve(strict=True)
            if not source.is_relative_to(root) or not source.is_file():
                raise HTTPException(404, "indexed PDF source is no longer available")
        except OSError as exc:
            raise HTTPException(404, "indexed PDF source is no longer available") from exc
        if source.stat().st_size != f["size"]:
            raise HTTPException(409, "PDF changed since it was indexed; synchronize the repository")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != f["content_hash"]:
            raise HTTPException(409, "PDF changed since it was indexed; synchronize the repository")
    elif f["repo_kind"] == "gitea":
        from opsintel.gitops import Mirror

        token = settings.gitea_token.get_secret_value()
        mirror = Mirror(settings.mirrors_dir / f"{f['repo_id']}.git",
                        auth_header=f"Authorization: token {token}" if token else None,
                        timeout_s=settings.git_timeout_s)
        try:
            with mirror.cat_blobs() as blobs:
                data = blobs.read(f["content_hash"])
        except (GitError, OSError) as exc:
            raise HTTPException(409, "indexed PDF blob is unavailable; synchronize the repository") from exc
    else:
        raise HTTPException(404, "PDF source is unavailable")

    if len(data) != f["size"] or not data.startswith(b"%PDF-"):
        raise HTTPException(409, "PDF source no longer matches the indexed revision")
    filename = Path(f["path"]).name.replace('"', "")
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/files/{file_id}/lines")
def get_lines(
    request: Request,
    file_id: int,
    conn: Conn,
    start: Annotated[int, Query(ge=1)] = 1,
    end: Annotated[int | None, Query(ge=1)] = None,
) -> dict:
    """Return indexed text for a line range; content is the indexed revision, not the live file."""
    s: Settings = request.app.state.settings
    f = _file_row(conn, file_id)
    if f["status"] != "indexed" or not f["line_count"]:
        raise HTTPException(409, f"file has no indexed text (status: {f['status']})")
    last = min(end or start + s.viewer_max_lines - 1, f["line_count"], start + s.viewer_max_lines - 1)
    if start > f["line_count"]:
        raise HTTPException(416, "start beyond end of file")
    lines: dict[int, str] = {}
    for c in conn.execute(
        "SELECT text, start_line, end_line FROM chunks WHERE file_id = ? AND end_line >= ? AND start_line <= ? "
        "ORDER BY ordinal",
        (file_id, start, last),
    ):
        if c["start_line"] == c["end_line"]:
            lines[c["start_line"]] = lines.get(c["start_line"], "") + c["text"]
        else:
            for i, text in enumerate(c["text"].split("\n")):
                lines[c["start_line"] + i] = text
    return {
        "file_id": file_id,
        "path": f["path"],
        "repo_name": f["repo_name"],
        "language": f["language"],
        "line_count": f["line_count"],
        "start": start,
        "end": last,
        "lines": [{"line": n, "text": lines.get(n, "")} for n in range(start, last + 1)],
    }


@router.get("/files/{file_id}/chunks/{chunk_id}")
def get_chunk_context(
    file_id: int,
    chunk_id: int,
    conn: Conn,
    context: Annotated[int, Query(ge=0, le=5)] = 1,
    cell: Annotated[str | None, Query(pattern=r"^[A-Z]{1,3}[1-9][0-9]*$")] = None,
) -> dict:
    """Viewer payload for pages, sections, sheets and CSV rows: the matching chunk plus neighbouring chunks."""
    f = _file_row(conn, file_id)
    target = conn.execute("SELECT ordinal FROM chunks WHERE id = ? AND file_id = ?", (chunk_id, file_id)).fetchone()
    if target is None:
        raise HTTPException(404, "chunk not found in this file")
    rows = conn.execute(
        "SELECT * FROM chunks WHERE file_id = ? AND ordinal BETWEEN ? AND ? ORDER BY ordinal",
        (file_id, target["ordinal"] - context, target["ordinal"] + context),
    ).fetchall()
    total = conn.execute("SELECT count(*) FROM chunks WHERE file_id = ?", (file_id,)).fetchone()[0]
    chunks = []
    for c in rows:
        lines = c["text"].split("\n")
        location = locate(c, 0, lines[0])
        if c["id"] == chunk_id and cell:
            match = next((item for line in lines for item in cells(c, line) if item["cell"] == cell), None)
            if match:
                location.update({key: match[key] for key in ("cell", "row", "column", "header")})
        chunks.append({
            "chunk_id": c["id"],
            "ordinal": c["ordinal"],
            "is_target": c["id"] == chunk_id,
            "heading": heading(c),
            "location": location,
            "extra": json.loads(c["extra_json"]) if c["extra_json"] else {},
            "lines": [{"label": label(c, i, text), "text": text, "cells": cells(c, text)}
                      for i, text in enumerate(lines)],
        })
    return {"file_id": file_id, "path": f["path"], "repo_name": f["repo_name"], "file_type": f["file_type"],
            "language": f["language"], "chunk_count": total, "target_cell": cell, "chunks": chunks}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = connect(settings)
        try:
            migrate(conn)
        finally:
            conn.close()
        runner = AIQueueRunner(settings) if settings.ai_enabled else None
        task = asyncio.create_task(runner.run(), name="opsintel-ai-queue") if runner else None
        app.state.ai_runner = runner
        app.state.ai_queue_task = task
        if task:
            task.add_done_callback(_log_ai_consumer_failure)
        try:
            yield
        finally:
            if runner:
                runner.stop()
            if task:
                try:
                    await asyncio.wait_for(task, timeout=settings.ai_timeout_s + 10)
                except TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="OpsIntel", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(router)

    if (STATIC_DIR / "index.html").is_file() and (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(STATIC_DIR / "index.html")

    return app


def _log_ai_consumer_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        log.error("AI queue consumer stopped unexpectedly", exc_info=(type(error), error, error.__traceback__))


app = create_app()
