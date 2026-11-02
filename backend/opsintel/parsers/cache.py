import json
import sqlite3
import time
import zlib
from dataclasses import asdict

from opsintel.db import transaction
from opsintel.parsers.base import Chunk, ParseResult


class ParseCache:
    """Persistent, size-bounded cache of parser output keyed by content hash and parser signature."""

    def __init__(self, conn: sqlite3.Connection, max_bytes: int):
        self.conn = conn
        self.max_bytes = max_bytes
        self.hits = 0
        self.misses = 0

    def get(self, content_hash: str, signature: str) -> tuple[list[Chunk], ParseResult] | None:
        row = self.conn.execute("SELECT payload FROM parse_cache WHERE content_hash = ? AND parser_sig = ?",
                                (content_hash, signature)).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.conn.execute("UPDATE parse_cache SET last_used_at = ? WHERE content_hash = ? AND parser_sig = ?",
                          (time.time(), content_hash, signature))
        self.hits += 1
        body = json.loads(zlib.decompress(row[0]))
        return [Chunk(**c) for c in body["chunks"]], ParseResult(**body["result"])

    def put(self, content_hash: str, signature: str, chunks: list[Chunk], result: ParseResult) -> None:
        if self.max_bytes <= 0:
            return
        payload = zlib.compress(json.dumps({"chunks": [asdict(c) for c in chunks], "result": asdict(result)},
                                           separators=(",", ":")).encode(), 6)
        if len(payload) > self.max_bytes // 4:
            return  # one huge document must not evict the whole cache
        now = time.time()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR REPLACE INTO parse_cache(content_hash, parser_sig, payload, size, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (content_hash, signature, payload, len(payload), now, now))
            self._evict()

    def _evict(self) -> None:
        total = self.conn.execute("SELECT coalesce(sum(size), 0) FROM parse_cache").fetchone()[0]
        if total <= self.max_bytes:
            return
        for row in self.conn.execute("SELECT content_hash, parser_sig, size FROM parse_cache "
                                     "ORDER BY last_used_at").fetchall():
            self.conn.execute("DELETE FROM parse_cache WHERE content_hash = ? AND parser_sig = ?", (row[0], row[1]))
            total -= row[2]
            if total <= self.max_bytes:
                return

    def stats(self) -> dict:
        n, size = self.conn.execute("SELECT count(*), coalesce(sum(size), 0) FROM parse_cache").fetchone()
        return {"entries": n, "bytes": size, "max_bytes": self.max_bytes, "hits": self.hits, "misses": self.misses}
