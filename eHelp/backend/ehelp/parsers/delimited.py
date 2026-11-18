import csv
import io
from collections.abc import Iterator

from ehelp.parsers.base import Chunk, ParseError, ParseResult, bounded_groups
from ehelp.parsers.text import decode_text, looks_binary

SNIFF_CHARS = 64 * 1024
MAX_FIELD_CHARS = 2000
csv.field_size_limit(10 * 1024 * 1024)


def render_row(row_num: int, values: list[str]) -> str:
    cells = [" ".join(v.split())[:MAX_FIELD_CHARS] for v in values]
    return f"row {row_num}: " + " | ".join(cells)


class DelimitedParser:
    """CSV/TSV: one rendered line per record, prefixed with its record number; headers kept as metadata."""

    name = "delimited"
    version = "1"
    isolated = False

    def __init__(self, default_delimiter: str = ",", chunk_rows: int = 50, max_chars: int = 8000):
        self.default_delimiter = default_delimiter
        self.chunk_rows = chunk_rows
        self.max_chars = max_chars

    @property
    def signature(self) -> str:
        return f"{self.name}:{self.version}:{self.default_delimiter!r}:{self.chunk_rows}:{self.max_chars}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"default_delimiter": self.default_delimiter, "chunk_rows": self.chunk_rows,
                           "max_chars": self.max_chars}

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        if looks_binary(data):
            raise ParseError("binary content")
        text, encoding = decode_text(data)
        result.encoding = encoding
        delimiter = self._delimiter(text[:SNIFF_CHARS])
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)

        header: list[str] | None = None
        rows: list[tuple[int, int, int, str]] = []  # (record_no, first_line, last_line, rendered)
        prev_line = 0
        try:
            for record_no, values in enumerate(reader, start=1):
                first_line, prev_line = prev_line + 1, reader.line_num
                if not any(v.strip() for v in values):
                    continue
                if header is None:
                    header = [v.strip() for v in values]
                rows.append((record_no, first_line, prev_line, render_row(record_no, values)))
        except csv.Error as exc:
            raise ParseError(f"malformed delimited file near line {reader.line_num}: {exc}") from exc
        result.line_count = prev_line

        extra = {"delimiter": delimiter, "headers": header or []}
        ordinal = 0
        for s, e in bounded_groups([r[3] for r in rows], self.chunk_rows, self.max_chars):
            group = rows[s:e]
            yield Chunk(
                ordinal=ordinal, text="\n".join(r[3] for r in group), coord_kind="row",
                row_num=group[0][0], start_line=group[0][1], end_line=group[-1][2], extra=extra,
            )
            ordinal += 1

    def _delimiter(self, sample: str) -> str:
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            return self.default_delimiter
