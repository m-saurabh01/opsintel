import logging
import re
import sqlite3
from pathlib import Path

from ehelp.db import transaction
from ehelp.parsers.base import ParseError, ParseResult
from ehelp.parsers.registry import ParserRegistry
from ehelp.parsers.sandbox import ParserSandbox

log = logging.getLogger(__name__)

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "csv": "text/csv",
    "txt": "text/plain",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "webm": "video/webm",
}
VIDEO_EXTS = {"mp4", "m4v", "webm"}


def mime_for(ext: str) -> str:
    return MIME.get(ext, "application/octet-stream")


def chunk_label(chunk) -> str:
    if chunk.sheet:
        return chunk.sheet + (f" {chunk.cell_ref}" if chunk.cell_ref else "")
    if chunk.section_path:
        return chunk.section_path
    return ""


class Indexer:
    def __init__(self, conn: sqlite3.Connection, registry: ParserRegistry, timeout_s: float = 120):
        self.conn = conn
        self.registry = registry
        self.sandbox = ParserSandbox(timeout_s)

    def index_document(self, doc_id: int, path: Path, ext: str) -> None:
        parser = None if ext in VIDEO_EXTS else self.registry.for_extension(ext)
        status, error, chunks, page_count = "indexed", "", [], None
        if ext in VIDEO_EXTS:
            pass  # CBT videos are found through title, description and tags
        elif parser is None:
            status, error = "unsupported", f"no text extraction for .{ext}; file is stored and downloadable"
        else:
            try:
                data = path.read_bytes()
                if getattr(parser, "isolated", False):
                    chunks, result = self.sandbox.run(parser, data)
                else:
                    result = ParseResult()
                    chunks = list(parser.parse(data, result))
                if result.warnings:
                    error = "; ".join(result.warnings)[:500]
            except ParseError as exc:
                status, error = "failed", str(exc)[:500]
            except Exception as exc:  # noqa: BLE001 - a bad document must never break the upload
                log.exception("indexing failed for document %s", doc_id)
                status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
        pages = [c.page for c in chunks if c.page]
        if pages:
            page_count = max(pages)
        with transaction(self.conn):
            self.conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            self.conn.executemany(
                "INSERT INTO chunks(doc_id, ordinal, page, label, text) VALUES (?, ?, ?, ?, ?)",
                [(doc_id, i, c.page, chunk_label(c), c.text) for i, c in enumerate(chunks) if c.text.strip()])
            self.conn.execute(
                "UPDATE documents SET index_status = ?, index_error = ?, page_count = coalesce(?, page_count) "
                "WHERE id = ?", (status, error, page_count, doc_id))

    def close(self) -> None:
        self.sandbox.close()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "category"
