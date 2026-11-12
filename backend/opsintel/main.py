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
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from opsintel import __version__, jobs, ollama
from opsintel.ai_queue import AIDailyLimitReached, AIQueueFull, AIQueueRunner, enqueue_question
from opsintel.auth import (
    authenticate,
    create_session,
    create_user,
    login_is_limited,
    record_login_failure,
    record_login_success,
    revoke_session,
    verify_csrf,
    verify_password,
)
from opsintel.config import Settings, get_settings
from opsintel.db import connect, migrate, transaction
from opsintel.embeddings import EmbeddingError
from opsintel.gitea import GiteaClient, GiteaError
from opsintel.gitops import GitError
from opsintel.hybrid import SemanticUnavailable, hybrid_search, semantic_available
from opsintel.indexing import register_local_repo
from opsintel.locations import cells, heading, label, locate
from opsintel.search import InvalidQuery, SearchRequest, search
from opsintel.sync import register_gitea_repo, remove_repository
from opsintel.tasks import PRIORITY_WEBHOOK, enqueue_repo_sync, get_setting, indexing_paused

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
WEBHOOK_MAX_BYTES = 5 * 1024 * 1024
WORKER_STALE_S = 60
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    repo_ids: list[int] | None = Field(default=None, max_length=100)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class CreateUserRequest(Credentials):
    role: Literal["admin", "user"] = "user"
    repo_ids: list[int] = Field(default_factory=list, max_length=1000)
    ai_enabled: bool = True
    ai_daily_limit: int = Field(default=0, ge=0, le=10000)


class LocalRepoRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    name: str | None = Field(default=None, max_length=255)


class GiteaRepoRequest(BaseModel):
    full_name: str = Field(min_length=3, max_length=255)


class UpdateUserRequest(BaseModel):
    enabled: bool | None = None
    role: Literal["admin", "user"] | None = None
    repo_ids: list[int] | None = Field(default=None, max_length=1000)
    ai_enabled: bool | None = None
    ai_daily_limit: int | None = Field(default=None, ge=0, le=10000)


class RepositoryStateRequest(BaseModel):
    enabled: bool


class RemoveRepositoryRequest(BaseModel):
    confirm: bool


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect(request.app.state.settings)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
router = APIRouter(prefix="/api")
SESSION_COOKIE = "opsintel_session"
CSRF_COOKIE = "opsintel_csrf"
PUBLIC_API_PATHS = {"/api/health", "/api/webhooks/gitea", "/api/auth/status", "/api/auth/bootstrap",
                    "/api/auth/login", "/api/auth/register"}


def _session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def _set_session_cookies(response: Response, request: Request, token: str, csrf_token: str, ttl_s: int) -> None:
    secure = request.url.scheme == "https"
    response.set_cookie(SESSION_COOKIE, token, max_age=ttl_s, httponly=True, secure=secure, samesite="strict",
                        path="/")
    response.set_cookie(CSRF_COOKIE, csrf_token, max_age=ttl_s, httponly=False, secure=secure, samesite="strict",
                        path="/")


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, samesite="strict")


def _audit(conn: sqlite3.Connection, actor_id: int | None, action: str, target_type: str,
           target_id: str | int | None, details: dict | None = None) -> None:
    conn.execute("INSERT INTO audit_events(actor_user_id, action, target_type, target_id, details_json) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (actor_id, action, target_type, str(target_id) if target_id is not None else None,
                  json.dumps(details or {}, separators=(",", ":"))))


def _require_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "authentication required")
    return user


def _require_admin(request: Request) -> dict:
    user = _require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "administrator role required")
    return user


def _require_repo_access(conn: sqlite3.Connection, user: dict, repo_id: int) -> None:
    if user["role"] == "admin":
        return
    if not conn.execute("SELECT 1 FROM repository_access WHERE user_id = ? AND repo_id = ?",
                        (user["id"], repo_id)).fetchone():
        raise HTTPException(404, "repository not found")


def _visible_repo_ids(conn: sqlite3.Connection, user: dict) -> list[int]:
    if user["role"] == "admin":
        return [row[0] for row in conn.execute("SELECT id FROM repositories")]
    return [row[0] for row in conn.execute(
        "SELECT r.id FROM repositories r JOIN repository_access a ON a.repo_id = r.id "
        "WHERE a.user_id = ? AND r.enabled = 1", (user["id"],))]


def _authorized_repo_ids(conn: sqlite3.Connection, user: dict, requested: list[int] | None) -> list[int]:
    visible = _visible_repo_ids(conn, user)
    if requested is None:
        return visible
    requested = sorted(set(requested))
    if not set(requested).issubset(visible):
        raise HTTPException(404, "repository not found")
    return requested


def _require_owned_ai_job(conn: sqlite3.Connection, job_id: int, user: dict) -> sqlite3.Row:
    row = jobs.get(conn, job_id)
    if row is None or row["queue"] != "ai" or row["owner_user_id"] != user["id"]:
        raise HTTPException(404, "AI request not found")
    return row


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    settings: Settings = request.app.state.settings
    if origin.rstrip("/") in {allowed.rstrip("/") for allowed in settings.auth_allowed_origins}:
        return
    origin_url = urlsplit(origin)
    request_url = request.url
    request_host = request_url.hostname or ""
    origin_host = origin_url.hostname or ""
    origin_port = origin_url.port or (443 if origin_url.scheme == "https" else 80)
    request_port = request_url.port or (443 if request_url.scheme == "https" else 80)
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    hosts_match = origin_host == request_host or (origin_host in loopback_hosts and request_host in loopback_hosts)
    valid_origin = (origin_url.scheme == request_url.scheme and origin_port == request_port and hosts_match
                    and origin_url.path in {"", "/"} and not origin_url.username and not origin_url.password
                    and not origin_url.query and not origin_url.fragment)
    if not valid_origin:
        raise HTTPException(403, "request origin is not allowed")


@router.get("/auth/status")
def auth_status(conn: Conn) -> dict:
    configured = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
    return {"setup_required": not configured}


@router.post("/auth/bootstrap", status_code=201)
def auth_bootstrap(body: Credentials, request: Request, response: Response, conn: Conn) -> dict:
    _check_origin(request)
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        raise HTTPException(403, "initial administrator setup is available only from this machine")
    try:
        with transaction(conn):
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise HTTPException(409, "initial administrator is already configured")
            user = create_user(conn, body.username, body.password, "admin")
            token, csrf_token = create_session(conn, user["id"], request.app.state.settings.auth_session_ttl_s)
            _audit(conn, user["id"], "auth.bootstrap", "user", user["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _set_session_cookies(response, request, token, csrf_token, request.app.state.settings.auth_session_ttl_s)
    user["ai_enabled"] = True
    user["ai_daily_limit"] = 0
    return {"user": user}


@router.post("/auth/register", status_code=201)
def auth_register(body: Credentials, request: Request, conn: Conn) -> dict:
    _check_origin(request)
    if request.client is None or request.client.host not in LOCAL_HOSTS:
        raise HTTPException(403, "local account registration is available only from this machine")
    if not conn.execute("SELECT 1 FROM users WHERE role = 'admin' AND enabled = 1 LIMIT 1").fetchone():
        raise HTTPException(409, "initial administrator setup is required")
    try:
        user = create_user(conn, body.username, body.password, "user")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"user": user}


@router.post("/auth/login")
def auth_login(body: Credentials, request: Request, response: Response, conn: Conn) -> dict:
    _check_origin(request)
    username = body.username.strip()
    if login_is_limited(conn, username):
        raise HTTPException(429, "too many login attempts; try again later")
    row = conn.execute("SELECT id, username, password_hash, role, ai_enabled, ai_daily_limit FROM users "
                        "WHERE username = ? COLLATE NOCASE AND enabled = 1", (username,)).fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        record_login_failure(conn, username)
        raise HTTPException(401, "invalid username or password")
    record_login_success(conn, row["id"], row["username"])
    token, csrf_token = create_session(conn, row["id"], request.app.state.settings.auth_session_ttl_s)
    _set_session_cookies(response, request, token, csrf_token, request.app.state.settings.auth_session_ttl_s)
    return {"user": {"id": row["id"], "username": row["username"], "role": row["role"],
                      "ai_enabled": bool(row["ai_enabled"]), "ai_daily_limit": row["ai_daily_limit"]}}


@router.get("/auth/me")
def auth_me(request: Request) -> dict:
    return {"user": _require_user(request)}


@router.post("/auth/logout")
def auth_logout(request: Request, response: Response, conn: Conn) -> dict:
    _check_origin(request)
    _require_user(request)
    revoke_session(conn, _session_token(request))
    _clear_session_cookies(response)
    return {"status": "logged_out"}


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
        "features": {"metadata_search": s.metadata_search_enabled, "semantic_search": semantic_available(s)},
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
def admin_status(request: Request, conn: Conn) -> dict:
    _require_admin(request)
    repos = [dict(r) for r in conn.execute(
        "SELECT r.id, r.name, r.kind, r.is_private, r.enabled, r.last_indexed_at, b.branch, b.head_sha, "
        "b.indexed_sha, b.indexed_at, b.last_sync_at, b.last_error "
        "FROM repositories r LEFT JOIN repo_branches b ON b.repo_id = r.id ORDER BY r.name, b.branch")]
    files = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM files GROUP BY status")}
    indexing: dict[int, list[dict]] = {}
    for job in jobs.recent(conn, 100):
        repo_id = job["payload"].get("repo_id")
        if job["queue"] == "sync" and job["status"] in {"queued", "running"} and repo_id is not None:
            indexing.setdefault(repo_id, []).append({
                "id": job["id"],
                "status": job["status"],
                "branch": job["payload"].get("branch"),
                "progress": job["progress"],
            })
    audit = [dict(row) for row in conn.execute(
        "SELECT a.id, u.username AS actor, a.action, a.target_type, a.target_id, a.created_at "
        "FROM audit_events a LEFT JOIN users u ON u.id = a.actor_user_id ORDER BY a.id DESC LIMIT 50")]
    return {"paused": indexing_paused(conn), "repositories": repos, "files": files, "jobs": jobs.stats(conn),
            "recent_jobs": jobs.recent(conn, 20), "indexing": indexing, "audit": audit}


@router.get("/admin/users")
def admin_users(request: Request, conn: Conn) -> list[dict]:
    _require_admin(request)
    settings: Settings = request.app.state.settings
    day_start = int(time.time() // 86400) * 86400
    users = [dict(row) for row in conn.execute(
        "SELECT id, username, role, enabled, ai_enabled, ai_daily_limit, created_at, last_login_at "
        "FROM users ORDER BY username")]
    for user in users:
        user["repo_ids"] = [row[0] for row in conn.execute(
            "SELECT repo_id FROM repository_access WHERE user_id = ? ORDER BY repo_id", (user["id"],))]
        user["ai_requests_today"] = conn.execute(
            "SELECT count(*) FROM jobs WHERE queue = 'ai' AND owner_user_id = ? AND created_at >= ?",
            (user["id"], day_start),
        ).fetchone()[0]
        user["ai_effective_daily_limit"] = user["ai_daily_limit"] or settings.ai_daily_request_limit
    return users


@router.post("/admin/users", status_code=201)
def admin_create_user(body: CreateUserRequest, request: Request, conn: Conn) -> dict:
    actor = _require_admin(request)
    repo_ids = sorted(set(body.repo_ids))
    existing = {row[0] for row in conn.execute("SELECT id FROM repositories")}
    if not set(repo_ids).issubset(existing):
        raise HTTPException(404, "one or more repositories were not found")
    try:
        with transaction(conn):
            user = create_user(conn, body.username, body.password, body.role)
            conn.execute("UPDATE users SET ai_enabled = ?, ai_daily_limit = ? WHERE id = ?",
                         (int(body.ai_enabled), body.ai_daily_limit, user["id"]))
            if body.role == "user":
                conn.executemany("INSERT INTO repository_access(user_id, repo_id, granted_by) VALUES (?, ?, ?)",
                                 [(user["id"], repo_id, actor["id"]) for repo_id in repo_ids])
            _audit(conn, actor["id"], "user.create", "user", user["id"], {
                "role": body.role, "ai_enabled": body.ai_enabled, "ai_daily_limit": body.ai_daily_limit,
            })
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return user


@router.patch("/admin/users/{user_id}")
def admin_update_user(user_id: int, body: UpdateUserRequest, request: Request, conn: Conn) -> dict:
    actor = _require_admin(request)
    target = conn.execute("SELECT id, username, role, enabled, ai_enabled, ai_daily_limit FROM users "
                          "WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        raise HTTPException(404, "user not found")
    role = body.role or target["role"]
    enabled = target["enabled"] if body.enabled is None else int(body.enabled)
    ai_enabled = target["ai_enabled"] if body.ai_enabled is None else int(body.ai_enabled)
    ai_daily_limit = target["ai_daily_limit"] if body.ai_daily_limit is None else body.ai_daily_limit
    if target["role"] == "admin" and (role != "admin" or not enabled):
        remaining = conn.execute("SELECT count(*) FROM users WHERE role = 'admin' AND enabled = 1 AND id != ?",
                                 (user_id,)).fetchone()[0]
        if remaining == 0:
            raise HTTPException(409, "cannot disable or demote the last active administrator")
    repo_ids = sorted(set(body.repo_ids or [])) if body.repo_ids is not None else None
    if repo_ids is not None:
        existing = {row[0] for row in conn.execute("SELECT id FROM repositories")}
        if not set(repo_ids).issubset(existing):
            raise HTTPException(404, "one or more repositories were not found")
    with transaction(conn):
        conn.execute("UPDATE users SET role = ?, enabled = ?, ai_enabled = ?, ai_daily_limit = ? WHERE id = ?",
                 (role, enabled, ai_enabled, ai_daily_limit, user_id))
        if repo_ids is not None:
            conn.execute("DELETE FROM repository_access WHERE user_id = ?", (user_id,))
            if role == "user":
                conn.executemany("INSERT INTO repository_access(user_id, repo_id, granted_by) VALUES (?, ?, ?)",
                                 [(user_id, repo_id, actor["id"]) for repo_id in repo_ids])
        if not enabled:
            conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        _audit(conn, actor["id"], "user.update", "user", user_id,
               {"role": role, "enabled": bool(enabled), "ai_enabled": bool(ai_enabled),
                "ai_daily_limit": ai_daily_limit, "permissions_changed": repo_ids is not None})
    return {"id": user_id, "username": target["username"], "role": role, "enabled": bool(enabled),
            "ai_enabled": bool(ai_enabled), "ai_daily_limit": ai_daily_limit}


def _admin_repo(conn: sqlite3.Connection, repo_id: int) -> sqlite3.Row:
    repo = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
    if repo is None:
        raise HTTPException(404, "repository not found")
    return repo


def _queue_repo(conn: sqlite3.Connection, request: Request, repo: sqlite3.Row) -> list[int]:
    try:
        queued = enqueue_repo_sync(conn, request.app.state.settings, repo)
    except jobs.QueueFull as exc:
        raise HTTPException(429, str(exc)) from exc
    return [job_id for job_id, _ in queued]


@router.post("/admin/repos/local", status_code=202)
def admin_add_local_repo(body: LocalRepoRequest, request: Request, conn: Conn) -> dict:
    actor = _require_admin(request)
    try:
        root_path = Path(body.path).expanduser().resolve(strict=True)
        roots = [Path(root).expanduser().resolve(strict=True)
                 for root in request.app.state.settings.local_repo_allowed_roots]
    except OSError as exc:
        raise HTTPException(400, "repository path or configured root does not exist") from exc
    if not root_path.is_dir() or not roots or not any(root_path == root or root in root_path.parents for root in roots):
        raise HTTPException(403, "repository path must be inside a configured LOCAL_REPO_ALLOWED_ROOTS directory")
    try:
        repo_id = register_local_repo(conn, body.name or root_path.name, root_path)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc
    repo = _admin_repo(conn, repo_id)
    job_ids = _queue_repo(conn, request, repo)
    conn.execute("INSERT OR IGNORE INTO repository_access(user_id, repo_id, granted_by) VALUES (?, ?, ?)",
                 (actor["id"], repo_id, actor["id"]))
    _audit(conn, actor["id"], "repository.add_local", "repository", repo_id, {"name": repo["name"]})
    return {"repository_id": repo_id, "job_ids": job_ids}


@router.post("/admin/repos/gitea", status_code=202)
def admin_add_gitea_repo(body: GiteaRepoRequest, request: Request, conn: Conn) -> dict:
    actor = _require_admin(request)
    try:
        with GiteaClient(request.app.state.settings) as client:
            remote = client.get_repo(body.full_name)
    except GiteaError as exc:
        raise HTTPException(502, str(exc)) from exc
    try:
        repo_id = register_gitea_repo(conn, remote)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc
    repo = _admin_repo(conn, repo_id)
    job_ids = _queue_repo(conn, request, repo)
    conn.execute("INSERT OR IGNORE INTO repository_access(user_id, repo_id, granted_by) VALUES (?, ?, ?)",
                 (actor["id"], repo_id, actor["id"]))
    _audit(conn, actor["id"], "repository.add_gitea", "repository", repo_id, {"name": repo["name"]})
    return {"repository_id": repo_id, "job_ids": job_ids}


@router.post("/admin/repos/{repo_id}/sync", status_code=202)
def admin_sync_repo(repo_id: int, request: Request, conn: Conn) -> dict:
    actor = _require_admin(request)
    repo = _admin_repo(conn, repo_id)
    job_ids = _queue_repo(conn, request, repo)
    _audit(conn, actor["id"], "repository.sync", "repository", repo_id, {"job_ids": job_ids})
    return {"repository_id": repo_id, "job_ids": job_ids}


@router.patch("/admin/repos/{repo_id}")
def admin_set_repo_state(repo_id: int, body: RepositoryStateRequest, request: Request, conn: Conn) -> dict:
    actor = _require_admin(request)
    _admin_repo(conn, repo_id)
    conn.execute("UPDATE repositories SET enabled = ? WHERE id = ?", (int(body.enabled), repo_id))
    _audit(conn, actor["id"], "repository.state", "repository", repo_id, {"enabled": body.enabled})
    return {"repository_id": repo_id, "enabled": body.enabled}


@router.delete("/admin/repos/{repo_id}")
def admin_remove_repo(repo_id: int, body: RemoveRepositoryRequest, request: Request, conn: Conn) -> dict:
    actor = _require_admin(request)
    repo = _admin_repo(conn, repo_id)
    if not body.confirm:
        raise HTTPException(400, "confirm must be true to remove the local index and mirror")
    name = repo["name"]
    result = remove_repository(conn, request.app.state.settings, repo_id)
    _audit(conn, actor["id"], "repository.remove", "repository", repo_id, {"name": name})
    return result


def _require_local_ai(settings: Settings) -> None:
    if settings.api_host.lower() not in LOCAL_HOSTS:
        raise HTTPException(503, "AI is disabled on non-local interfaces until M5 authentication is enabled")


def _gitea_source_url(result: dict, base_url: str) -> str | None:
    repo = result["repo"]
    if not base_url or repo.get("kind") != "gitea":
        return None
    name = repo["name"].split("/")
    path = result["path"].split("/")
    if len(name) != 2 or not all(name) or not path or any(part in {"", ".", ".."} for part in path):
        return None
    if result.get("commit_sha"):
        ref_kind, ref = "commit", result["commit_sha"]
    elif result.get("branch"):
        ref_kind, ref = "branch", result["branch"]
    else:
        return None
    parts = [*name, "src", ref_kind, ref, *path]
    url = base_url.rstrip("/") + "/" + "/".join(quote(part, safe="") for part in parts)
    location = result.get("location", {})
    if location.get("kind") == "line" and isinstance(location.get("line"), int):
        url += f"#L{location['line']}"
    return url


def _add_source_urls(result: dict, settings: Settings) -> dict:
    base_url = settings.gitea_web_url or settings.gitea_url
    for hit in result.get("results", []):
        hit["source_url"] = _gitea_source_url(hit, base_url)
    return result


@router.post("/ai/ask", status_code=202)
async def ask_ai(body: AskRequest, request: Request, conn: Conn) -> dict:
    user = _require_user(request)
    settings: Settings = request.app.state.settings
    _require_local_ai(settings)
    if not settings.ai_enabled:
        raise HTTPException(503, "AI question answering is disabled")
    if not user["ai_enabled"]:
        raise HTTPException(403, "AI assistance is disabled for this account")
    question = body.question.strip()
    if len(question) < 3:
        raise HTTPException(422, "question must contain at least 3 non-space characters")
    repo_ids = _authorized_repo_ids(conn, user, body.repo_ids)
    if not repo_ids:
        raise HTTPException(404, "no repositories are available to this account")
    status = await ollama.status(settings.ollama_base_url, settings.ollama_chat_model, settings.ollama_min_version)
    if not status.get("reachable"):
        raise HTTPException(503, "Ollama is unavailable")
    if not status.get("version_ok"):
        raise HTTPException(503, f"Ollama {status.get('version')} is older than required {settings.ollama_min_version}")
    if not status.get("model_present"):
        raise HTTPException(503, f"Ollama model '{settings.ollama_chat_model}' is not installed")
    try:
        daily_limit = user["ai_daily_limit"] or settings.ai_daily_request_limit
        job_id, _ = enqueue_question(conn, settings, question, repo_ids, user["id"], daily_limit)
    except AIQueueFull as exc:
        raise HTTPException(429, "AI queue is full; retry when a request finishes") from exc
    except AIDailyLimitReached as exc:
        raise HTTPException(429, f"daily AI request limit reached ({daily_limit})") from exc
    return {"job_id": job_id, "status": "queued", "events_url": f"/api/ai/ask/{job_id}/events"}


@router.get("/ai/ask/{job_id}/events")
async def ask_ai_events(job_id: int, request: Request, conn: Conn) -> StreamingResponse:
    user = _require_user(request)
    if not user["ai_enabled"]:
        raise HTTPException(403, "AI assistance is disabled for this account")
    _require_owned_ai_job(conn, job_id, user)

    async def stream():
        last_stage = None
        while True:
            if await request.is_disconnected():
                return
            row = jobs.get(conn, job_id)
            if row is None or row["owner_user_id"] != user["id"]:
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
def cancel_ai(job_id: int, request: Request, conn: Conn) -> dict:
    user = _require_user(request)
    _require_owned_ai_job(conn, job_id, user)
    status = jobs.cancel(conn, job_id)
    if status == "missing":
        raise HTTPException(404, "AI request not found")
    return {"job_id": job_id, "status": status}


@router.get("/repos")
def list_repos(request: Request, conn: Conn) -> list[dict]:
    user = _require_user(request)
    repo_ids = _visible_repo_ids(conn, user)
    if not repo_ids:
        return []
    marks = ",".join("?" * len(repo_ids))
    rows = conn.execute(
        f"""
        SELECT r.id, r.name, r.kind, r.default_branch, r.enabled, r.last_indexed_at,
               count(f.id) AS files,
               sum(f.status = 'indexed') AS indexed,
               sum(f.status = 'skipped') AS skipped,
               sum(f.status = 'unsupported') AS unsupported,
               sum(f.status = 'failed') AS failed
        FROM repositories r LEFT JOIN files f ON f.repo_id = r.id
        WHERE r.id IN ({marks})
        GROUP BY r.id ORDER BY r.name
        """, repo_ids).fetchall()  # noqa: S608
    return [dict(r) for r in rows]


@router.get("/facets")
def facets(request: Request, conn: Conn) -> dict:
    repo_ids = _visible_repo_ids(conn, _require_user(request))
    if not repo_ids:
        return {"file_types": [], "languages": []}
    marks = ",".join("?" * len(repo_ids))
    types = conn.execute(
        f"SELECT file_type, count(*) n FROM files WHERE status = 'indexed' AND repo_id IN ({marks}) "  # noqa: S608
        "GROUP BY file_type ORDER BY n DESC", repo_ids).fetchall()
    langs = conn.execute(
        f"SELECT language, count(*) n FROM files WHERE status = 'indexed' AND language IS NOT NULL "  # noqa: S608
        f"AND repo_id IN ({marks}) GROUP BY language ORDER BY n DESC", repo_ids).fetchall()  # noqa: S608
    return {"file_types": [dict(r) for r in types], "languages": [dict(r) for r in langs]}


@router.get("/search")
def search_endpoint(
    request: Request,
    conn: Conn,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    mode: Annotated[str, Query(pattern="^(smart|fulltext|phrase|exact|metadata|semantic|hybrid)$")] = "smart",
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
    if mode in ("semantic", "hybrid") and not semantic_available(s):
        raise HTTPException(503, "semantic search is disabled")
    repo_ids = _authorized_repo_ids(conn, _require_user(request), repo)
    if not repo_ids:
        return {"query": q, "mode": "smart" if mode == "smart" else mode, "page": page,
                "page_size": min(page_size, s.search_page_size_max), "total": 0, "results": []}
    if mode in ("smart", "metadata", "semantic", "hybrid"):
        req = SearchRequest(
            q=q, repo_ids=repo_ids, branch=branch, file_types=type, languages=lang, path_prefix=path,
            page=page, page_size=min(page_size, s.search_page_size_max),
        )
        try:
            result = hybrid_search(conn, req, s, semantic_only=mode == "semantic")
            if mode in ("smart", "metadata"):
                result["mode"] = "smart"
            return _add_source_urls(result, s)
        except InvalidQuery as exc:
            raise HTTPException(400, str(exc)) from exc
        except (SemanticUnavailable, EmbeddingError) as exc:
            if mode in ("smart", "metadata"):
                try:
                    result = hybrid_search(conn, req, s, include_semantic=False)
                    result["mode"] = "smart"
                    return _add_source_urls(result, s)
                except InvalidQuery as invalid:
                    raise HTTPException(400, str(invalid)) from invalid
            raise HTTPException(503, f"semantic search is unavailable: {exc}") from exc
    req = SearchRequest(
        q=q, mode=mode, repo_ids=repo_ids, branch=branch, file_types=type, languages=lang, path_prefix=path,
        case_sensitive=case_sensitive, page=page, page_size=min(page_size, s.search_page_size_max),
    )
    try:
        return _add_source_urls(search(conn, req), s)
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
def get_file(file_id: int, request: Request, conn: Conn) -> dict:
    user = _require_user(request)
    file_row = _file_row(conn, file_id)
    _require_repo_access(conn, user, file_row["repo_id"])
    row = dict(file_row)
    row.pop("mtime_ns", None)
    row.pop("repo_kind", None)
    row.pop("repo_location", None)
    user = _require_user(request)
    _require_repo_access(conn, user, row["repo_id"])
    return row


@router.get("/files/{file_id}/raw.pdf")
def get_pdf(file_id: int, request: Request, conn: Conn) -> Response:
    f = _file_row(conn, file_id)
    _require_repo_access(conn, _require_user(request), f["repo_id"])
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
    user = _require_user(request)
    _require_repo_access(conn, user, f["repo_id"])
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
    request: Request,
    conn: Conn,
    context: Annotated[int, Query(ge=0, le=5)] = 1,
    cell: Annotated[str | None, Query(pattern=r"^[A-Z]{1,3}[1-9][0-9]*$")] = None,
) -> dict:
    """Viewer payload for pages, sections, sheets and CSV rows: the matching chunk plus neighbouring chunks."""
    f = _file_row(conn, file_id)
    user = _require_user(request)
    _require_repo_access(conn, user, f["repo_id"])
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

    @app.middleware("http")
    async def authenticate_api_request(request: Request, call_next):
        if not request.url.path.startswith("/api/") or request.url.path in PUBLIC_API_PATHS:
            response = await call_next(request)
        else:
            conn = connect(settings)
            try:
                session = authenticate(conn, _session_token(request))
                if session is None:
                    return JSONResponse({"detail": "authentication required"}, status_code=401,
                                        headers={"Cache-Control": "no-store"})
                user, csrf_hash = session
                request.state.user = user
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    _check_origin(request)
                    csrf_header = request.headers.get("x-csrf-token")
                    csrf_cookie = request.cookies.get(CSRF_COOKIE)
                    if not csrf_cookie or csrf_header != csrf_cookie or not verify_csrf(csrf_hash, csrf_header):
                        return JSONResponse({"detail": "valid CSRF token required"}, status_code=403,
                                            headers={"Cache-Control": "no-store"})
                response = await call_next(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                                    headers={"Cache-Control": "no-store"})
            finally:
                conn.close()
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

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
