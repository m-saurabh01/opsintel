import asyncio
import hashlib
import json
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from ehelp import ai
from ehelp.auth import User, current_user, require_admin
from ehelp.config import Config, load_config
from ehelp.db import DEFAULT_SETTINGS, connect, get_settings, init_db, tags_of, transaction
from ehelp.indexing import VIDEO_EXTS, Indexer, mime_for, slugify
from ehelp.parsers.registry import ParserRegistry
from ehelp.search import MARK_CLOSE, MARK_OPEN, search_documents, tokens_of  # noqa: F401
from ehelp.cache import CACHE_API_DEFAULT, CACHE_SEARCH, CACHE_DOC_META, set_cache_headers, set_etag

SORTS = {
    "newest": "d.created_at DESC",
    "oldest": "d.created_at ASC",
    "modified": "d.updated_at DESC",
    "title": "d.title COLLATE NOCASE ASC",
    "popular": "d.views DESC, d.created_at DESC",
    "size": "d.size DESC",
}
INLINE_TYPES = {"pdf": "application/pdf", "txt": "text/plain; charset=utf-8", "mp4": "video/mp4",
                "m4v": "video/mp4", "webm": "video/webm"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
DOC_SELECT = ("SELECT d.*, c.name AS category_name, c.slug AS category_slug "
              "FROM documents d LEFT JOIN categories c ON c.id = d.category_id")
STATIC_DIR = Path(__file__).parent / "static"


def doc_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "title": row["title"], "description": row["description"],
        "category_id": row["category_id"], "category": row["category_name"], "category_slug": row["category_slug"],
        "filename": row["filename"], "ext": row["ext"], "size": row["size"], "tags": tags_of(row),
        "revision": row["revision"], "page_count": row["page_count"], "views": row["views"],
        "index_status": row["index_status"], "index_error": row["index_error"],
        "created_at": row["created_at"], "updated_at": row["updated_at"], "uploaded_by": row["uploaded_by"],
    }


def category_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "slug": row["slug"], "name": row["name"], "description": row["description"],
            "icon": row["icon"], "banner": row["banner"], "sort_order": row["sort_order"],
            "count": row["count"] if "count" in row.keys() else 0}


def parse_tags(raw: str) -> list[str]:
    return [t for t in dict.fromkeys(p.strip() for p in re.split(r"[,\n]", raw)) if t][:30]


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    for d in (config.data_dir, config.files_dir, config.assets_dir):
        d.mkdir(parents=True, exist_ok=True)
    boot = connect(config.db_path)
    init_db(boot)
    index_conn = boot
    indexer = Indexer(index_conn, ParserRegistry(config.libreoffice_path))
    index_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        indexer.close()
        boot.close()

    app = FastAPI(title="eHelp", lifespan=lifespan)
    app.state.config = config

    def db() -> Iterator[sqlite3.Connection]:
        conn = connect(config.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def get_doc(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row:
        row = conn.execute(f"{DOC_SELECT} WHERE d.id = ?", (doc_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        return row

    def categories_with_counts(conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute(
            "SELECT c.*, (SELECT count(*) FROM documents d WHERE d.category_id = c.id) AS count "
            "FROM categories c ORDER BY c.sort_order, c.name").fetchall()
        return [category_dict(r) for r in rows]

    # ---------- identity & settings ----------
    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return user.public()

    @app.get("/api/settings")
    def settings(conn: sqlite3.Connection = Depends(db)):
        return get_settings(conn)

    @app.put("/api/admin/settings")
    def update_settings(body: dict, _: User = Depends(require_admin), conn: sqlite3.Connection = Depends(db)):
        unknown = set(body) - set(DEFAULT_SETTINGS)
        if unknown:
            raise HTTPException(422, f"Unknown settings: {', '.join(sorted(unknown))}")
        if "ai_daily_limit" in body:
            try:
                body["ai_daily_limit"] = str(max(0, int(body["ai_daily_limit"])))
            except (TypeError, ValueError):
                raise HTTPException(422, "AI daily limit must be a whole number (0 = unlimited)") from None
        if "ai_enabled" in body:
            body["ai_enabled"] = "1" if str(body["ai_enabled"]) in ("1", "true", "True") else "0"
        with transaction(conn):
            for key, value in body.items():
                conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)[:1000]))
        return get_settings(conn)

    @app.post("/api/admin/assets")
    def upload_asset(file: UploadFile = File(...), _: User = Depends(require_admin)):
        ext = Path(file.filename or "").suffix.lower().lstrip(".")
        if ext not in IMAGE_EXTS:
            raise HTTPException(422, "Only png, jpg, jpeg, webp and gif images are allowed")
        name = f"{uuid.uuid4().hex}.{ext}"
        with (config.assets_dir / name).open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return {"url": f"/uploads/{name}"}

    # ---------- categories ----------
    # ---------- AI mode ----------
    ai_state = {"waiting": 0}
    ai_gate = asyncio.Semaphore(1)

    @app.get("/api/ai/status")
    async def ai_status(conn: sqlite3.Connection = Depends(db)):
        cfg = get_settings(conn)
        enabled = cfg["ai_enabled"] == "1"
        limit = int(cfg["ai_daily_limit"] or 0)
        used = ai.usage_today(conn)
        out = {"enabled": enabled, "limit": limit, "used": used,
               "remaining": None if not limit else max(0, limit - used)}
        if enabled:
            out.update(await ai.status(config.ollama_url, config.ollama_model))
        return out

    class AskBody(BaseModel):
        question: str
        category: str | None = None

    @app.post("/api/ai/ask")
    async def ai_ask(body: AskBody, conn: sqlite3.Connection = Depends(db)):
        cfg = get_settings(conn)
        if cfg["ai_enabled"] != "1":
            raise HTTPException(403, "AI mode is turned off by the administrator")
        question = body.question.strip()
        if len(question) < 3:
            raise HTTPException(422, "Question must contain at least 3 characters")
        st = await ai.status(config.ollama_url, config.ollama_model)
        if not st["reachable"]:
            raise HTTPException(503, "The AI engine (Ollama) is not reachable")
        if not st["model_present"]:
            raise HTTPException(503, f"AI model '{config.ollama_model}' is not installed")
        if ai_state["waiting"] >= config.ai_max_queue:
            raise HTTPException(429, "AI is busy; try again in a moment")
        try:
            ai.reserve_request(conn, int(cfg["ai_daily_limit"] or 0))
        except ai.AILimitReached:
            raise HTTPException(429, "The daily AI request limit has been reached") from None
        evidence = ai.retrieve(conn, question, config.ai_top_k, config.ai_context_chars, body.category or None)

        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        async def stream():
            if not evidence:
                yield sse("done", {"answer": ai.INSUFFICIENT, "citations": [], "citation_warning": None})
                return
            ai_state["waiting"] += 1
            try:
                async with ai_gate:
                    yield sse("stage", {"stage": "generating"})
                    parts: list[str] = []
                    reason = None
                    async for token, done in ai.generate(
                            config.ollama_url, config.ollama_model, ai.build_prompt(question, evidence),
                            config.ai_num_ctx, config.ai_max_tokens, config.ai_timeout_s, "10m"):
                        if done:
                            reason = done
                        else:
                            parts.append(token)
                            yield sse("token", {"text": token})
                    result = ai.validate("".join(parts), evidence)
                    if reason == "length":
                        result["citation_warning"] = ((result["citation_warning"] or "") +
                                                      " The model reached its output limit; the answer may be incomplete.").strip()
                    yield sse("done", result)
            except Exception as exc:  # noqa: BLE001 - report any engine failure to the client
                yield sse("error", {"message": f"{type(exc).__name__}: {exc}"[:300]})
            finally:
                ai_state["waiting"] -= 1

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/categories")
    def list_categories(conn: sqlite3.Connection = Depends(db)):
        return categories_with_counts(conn)

    @app.post("/api/admin/categories", status_code=201)
    def create_category(body: dict, _: User = Depends(require_admin), conn: sqlite3.Connection = Depends(db)):
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(422, "Category name is required")
        slug = slugify(name)
        if conn.execute("SELECT 1 FROM categories WHERE slug = ?", (slug,)).fetchone():
            raise HTTPException(409, "A category with this name already exists")
        order = conn.execute("SELECT coalesce(max(sort_order), -1) + 1 FROM categories").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO categories(slug, name, description, icon, banner, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
            (slug, name, str(body.get("description", "")), str(body.get("icon") or "folder"),
             str(body.get("banner", "")), int(body.get("sort_order", order))))
        return next(c for c in categories_with_counts(conn) if c["id"] == cur.lastrowid)

    @app.put("/api/admin/categories/{category_id}")
    def update_category(category_id: int, body: dict, _: User = Depends(require_admin),
                        conn: sqlite3.Connection = Depends(db)):
        row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Category not found")
        name = str(body.get("name", row["name"])).strip() or row["name"]
        conn.execute(
            "UPDATE categories SET name = ?, description = ?, icon = ?, banner = ?, sort_order = ? WHERE id = ?",
            (name, str(body.get("description", row["description"])), str(body.get("icon", row["icon"])),
             str(body.get("banner", row["banner"])), int(body.get("sort_order", row["sort_order"])), category_id))
        return next(c for c in categories_with_counts(conn) if c["id"] == category_id)

    @app.delete("/api/admin/categories/{category_id}", status_code=204)
    def delete_category(category_id: int, _: User = Depends(require_admin), conn: sqlite3.Connection = Depends(db)):
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))

    # ---------- documents (read) ----------
    @app.get("/api/home")
    def home(conn: sqlite3.Connection = Depends(db)):
        recent = conn.execute(f"{DOC_SELECT} ORDER BY d.created_at DESC LIMIT 6").fetchall()
        popular = conn.execute(f"{DOC_SELECT} WHERE d.views > 0 ORDER BY d.views DESC LIMIT 6").fetchall()
        total = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        return {"categories": categories_with_counts(conn), "recent": [doc_dict(r) for r in recent],
                "popular": [doc_dict(r) for r in popular], "total": total}

    @app.get("/api/documents")
    def list_documents(category: str | None = None, q: str = "", type: str | None = None,
                       sort: str = "newest", modified_days: int | None = Query(None, ge=1),
                       page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=100),
                       conn: sqlite3.Connection = Depends(db)):
        where, args = [], []
        category_id = None
        if category:
            cat = conn.execute("SELECT id FROM categories WHERE slug = ?", (category,)).fetchone()
            if cat is None:
                raise HTTPException(404, "Category not found")
            category_id = cat["id"]
            where.append("d.category_id = ?")
            args.append(category_id)
        if type:
            where.append("d.ext = ?")
            args.append(type.lower())
        if modified_days:
            where.append("d.updated_at >= ?")
            args.append(time.time() - modified_days * 86400)
        if q.strip():
            ids = [h.doc_id for h in search_documents(conn, q, "smart", category_id, type)]
            where.append(f"d.id IN ({','.join('?' * len(ids)) or 'NULL'})")
            args.extend(ids)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        total = conn.execute(f"SELECT count(*) FROM documents d{clause}", args).fetchone()[0]
        rows = conn.execute(f"{DOC_SELECT}{clause} ORDER BY {SORTS.get(sort, SORTS['newest'])} LIMIT ? OFFSET ?",
                            [*args, page_size, (page - 1) * page_size]).fetchall()
        return {"total": total, "page": page, "page_size": page_size, "items": [doc_dict(r) for r in rows]}

    @app.get("/api/search")
    def search(q: str, mode: str = Query("smart", pattern="^(smart|exact)$"), category: str | None = None,
               type: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50),
               conn: sqlite3.Connection = Depends(db)):
        category_id = None
        if category:
            cat = conn.execute("SELECT id FROM categories WHERE slug = ?", (category,)).fetchone()
            category_id = cat["id"] if cat else -1
        hits = search_documents(conn, q, mode, category_id, type)
        window = hits[(page - 1) * page_size: page * page_size]
        items = []
        for hit in window:
            doc = doc_dict(get_doc(conn, hit.doc_id))
            items.append({"document": doc, "matches": hit.matches, "title_match": hit.title_match,
                          "snippets": hit.snippets})
        result = {"query": q, "mode": mode, "total": len(hits), "page": page, "page_size": page_size, "items": items,
                "mark": [MARK_OPEN, MARK_CLOSE]}
        response = Response(json.dumps(result), media_type="application/json")
        set_cache_headers(response, max_age=CACHE_SEARCH, public=False)
        return response

    @app.get("/api/documents/{doc_id}")
    def document(doc_id: int, conn: sqlite3.Connection = Depends(db)):
        response = Response(json.dumps(doc_dict(get_doc(conn, doc_id))), media_type="application/json")
        set_cache_headers(response, max_age=CACHE_DOC_META, public=True)
        return response

    @app.post("/api/documents/{doc_id}/view", status_code=204)
    def record_view(doc_id: int, conn: sqlite3.Connection = Depends(db)):
        get_doc(conn, doc_id)
        conn.execute("UPDATE documents SET views = views + 1 WHERE id = ?", (doc_id,))

    @app.get("/api/documents/{doc_id}/related")
    def related(doc_id: int, limit: int = Query(6, ge=1, le=20), conn: sqlite3.Connection = Depends(db)):
        doc = get_doc(conn, doc_id)
        manual = conn.execute(
            f"{DOC_SELECT} JOIN document_relations r ON r.related_id = d.id WHERE r.doc_id = ? ORDER BY r.position",
            (doc_id,)).fetchall()
        if manual:
            return {"manual": True, "items": [doc_dict(r) for r in manual]}
        words = {t.lower() for t in tokens_of(doc["title"]) if len(t) > 2} | {t.lower() for t in tags_of(doc)}
        candidates = conn.execute(f"{DOC_SELECT} WHERE d.id != ? AND d.category_id IS ?", (doc_id, doc["category_id"]))
        scored = []
        for row in candidates:
            other = {t.lower() for t in tokens_of(row["title"]) if len(t) > 2} | {t.lower() for t in tags_of(row)}
            scored.append((len(words & other), row["created_at"], row))
        scored.sort(key=lambda s: (-s[0], -s[1]))
        return {"manual": False, "items": [doc_dict(s[2]) for s in scored[:limit]]}

    def file_path(row: sqlite3.Row) -> Path:
        path = config.files_dir / row["stored_name"]
        if not path.is_file():
            raise HTTPException(404, "File is missing from storage")
        return path

    @app.get("/api/documents/{doc_id}/file")
    def view_file(doc_id: int, conn: sqlite3.Connection = Depends(db)):
        row = get_doc(conn, doc_id)
        inline = INLINE_TYPES.get(row["ext"])
        headers = {"X-Content-Type-Options": "nosniff"}
        if inline:
            return FileResponse(file_path(row), media_type=inline, headers=headers,
                                content_disposition_type="inline", filename=row["filename"])
        return FileResponse(file_path(row), media_type=mime_for(row["ext"]), filename=row["filename"], headers=headers)

    @app.get("/api/documents/{doc_id}/download")
    def download(doc_id: int, conn: sqlite3.Connection = Depends(db)):
        row = get_doc(conn, doc_id)
        return FileResponse(file_path(row), media_type=mime_for(row["ext"]), filename=row["filename"],
                            headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/api/documents/{doc_id}/text")
    def text(doc_id: int, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
             conn: sqlite3.Connection = Depends(db)):
        get_doc(conn, doc_id)
        total = conn.execute("SELECT count(*) FROM chunks WHERE doc_id = ?", (doc_id,)).fetchone()[0]
        rows = conn.execute("SELECT ordinal, page, label, text FROM chunks WHERE doc_id = ? ORDER BY ordinal "
                            "LIMIT ? OFFSET ?", (doc_id, limit, offset)).fetchall()
        return {"total": total, "items": [dict(r) for r in rows]}

    # ---------- documents (admin) ----------
    def save_upload(file: UploadFile) -> tuple[str, str, int, str, Path]:
        filename = Path(file.filename or "document").name
        ext = Path(filename).suffix.lower().lstrip(".")
        if not ext:
            raise HTTPException(422, "File needs an extension")
        stored = f"{uuid.uuid4().hex}.{ext}"
        path = config.files_dir / stored
        digest, size = hashlib.sha256(), 0
        with path.open("wb") as out:
            while block := file.file.read(1024 * 1024):
                size += len(block)
                if size > config.max_upload_bytes:
                    out.close()
                    path.unlink(missing_ok=True)
                    raise HTTPException(413, "File exceeds the upload size limit")
                digest.update(block)
                out.write(block)
        if size == 0:
            path.unlink(missing_ok=True)
            raise HTTPException(422, "File is empty")
        return filename, ext, size, digest.hexdigest(), path

    def index(doc_id: int, path: Path, ext: str) -> None:
        with index_lock:
            indexer.index_document(doc_id, path, ext)

    def set_relations(conn: sqlite3.Connection, doc_id: int, ids: list[int]) -> None:
        valid = [i for i in dict.fromkeys(ids) if i != doc_id and
                 conn.execute("SELECT 1 FROM documents WHERE id = ?", (i,)).fetchone()]
        conn.execute("DELETE FROM document_relations WHERE doc_id = ?", (doc_id,))
        conn.executemany("INSERT INTO document_relations(doc_id, related_id, position) VALUES (?, ?, ?)",
                         [(doc_id, rid, pos) for pos, rid in enumerate(valid)])

    def parse_ids(raw: str) -> list[int]:
        try:
            return [int(x) for x in json.loads(raw or "[]")]
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "related_ids must be a JSON list of document ids") from exc

    def check_category(conn: sqlite3.Connection, category_id: int | None) -> None:
        if category_id and not conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone():
            raise HTTPException(422, "Unknown category")

    @app.post("/api/admin/documents", status_code=201)
    def upload_document(file: UploadFile = File(...), title: str = Form(""), description: str = Form(""),
                        category_id: int | None = Form(None), tags: str = Form(""), revision: str = Form(""),
                        related_ids: str = Form("[]"), user: User = Depends(require_admin),
                        conn: sqlite3.Connection = Depends(db)):
        check_category(conn, category_id)
        rel = parse_ids(related_ids)
        filename, ext, size, sha, path = save_upload(file)
        now = time.time()
        cur = conn.execute(
            "INSERT INTO documents(title, description, category_id, filename, ext, mime, size, sha256, stored_name,"
            " tags, revision, uploaded_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title.strip() or Path(filename).stem, description, category_id, filename, ext, mime_for(ext), size, sha,
             path.name, json.dumps(parse_tags(tags)), revision, user.user_id, now, now))
        doc_id = cur.lastrowid
        set_relations(conn, doc_id, rel)
        index(doc_id, path, ext)
        return doc_dict(get_doc(conn, doc_id))

    @app.put("/api/admin/documents/{doc_id}")
    def update_document(doc_id: int, body: dict, _: User = Depends(require_admin),
                        conn: sqlite3.Connection = Depends(db)):
        row = get_doc(conn, doc_id)
        category_id = body.get("category_id", row["category_id"])
        check_category(conn, category_id)
        tags = body.get("tags", tags_of(row))
        if isinstance(tags, str):
            tags = parse_tags(tags)
        conn.execute(
            "UPDATE documents SET title = ?, description = ?, category_id = ?, tags = ?, revision = ?, "
            "updated_at = ? WHERE id = ?",
            (str(body.get("title", row["title"])).strip() or row["title"],
             str(body.get("description", row["description"])), category_id, json.dumps(tags),
             str(body.get("revision", row["revision"])), time.time(), doc_id))
        if "related_ids" in body:
            set_relations(conn, doc_id, [int(i) for i in body["related_ids"]])
        return doc_dict(get_doc(conn, doc_id))

    @app.get("/api/admin/documents/{doc_id}/relations")
    def get_relations(doc_id: int, _: User = Depends(require_admin), conn: sqlite3.Connection = Depends(db)):
        get_doc(conn, doc_id)
        rows = conn.execute("SELECT related_id FROM document_relations WHERE doc_id = ? ORDER BY position",
                            (doc_id,)).fetchall()
        return {"related_ids": [r["related_id"] for r in rows]}

    @app.post("/api/admin/documents/{doc_id}/file")
    def replace_file(doc_id: int, file: UploadFile = File(...), _: User = Depends(require_admin),
                     conn: sqlite3.Connection = Depends(db)):
        row = get_doc(conn, doc_id)
        filename, ext, size, sha, path = save_upload(file)
        old = config.files_dir / row["stored_name"]
        conn.execute("UPDATE documents SET filename = ?, ext = ?, mime = ?, size = ?, sha256 = ?, stored_name = ?, "
                     "updated_at = ?, page_count = NULL WHERE id = ?",
                     (filename, ext, mime_for(ext), size, sha, path.name, time.time(), doc_id))
        old.unlink(missing_ok=True)
        index(doc_id, path, ext)
        return doc_dict(get_doc(conn, doc_id))

    @app.post("/api/admin/documents/{doc_id}/reindex")
    def reindex(doc_id: int, _: User = Depends(require_admin), conn: sqlite3.Connection = Depends(db)):
        row = get_doc(conn, doc_id)
        index(doc_id, file_path(row), row["ext"])
        return doc_dict(get_doc(conn, doc_id))

    @app.delete("/api/admin/documents/{doc_id}", status_code=204)
    def delete_document(doc_id: int, _: User = Depends(require_admin), conn: sqlite3.Connection = Depends(db)):
        row = get_doc(conn, doc_id)
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        (config.files_dir / row["stored_name"]).unlink(missing_ok=True)

    app.mount("/uploads", StaticFiles(directory=config.assets_dir), name="uploads")
    if STATIC_DIR.is_dir():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            target = (STATIC_DIR / path).resolve()
            if path and target.is_file() and STATIC_DIR.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(STATIC_DIR / "index.html")
    return app
