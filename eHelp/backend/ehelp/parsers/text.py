from collections.abc import Iterator

from charset_normalizer import from_bytes

from ehelp.parsers.base import Chunk, ParseError, ParseResult

BINARY_SNIFF_BYTES = 8192


def looks_binary(data: bytes) -> bool:
    head = data[:BINARY_SNIFF_BYTES]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False  # UTF-16 with BOM contains NULs but is text
    return b"\x00" in head


def decode_text(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    best = from_bytes(data[: 1024 * 1024]).best()
    if best is not None and best.encoding:
        return data.decode(best.encoding, errors="replace"), best.encoding
    return data.decode("latin-1"), "latin-1"


def split_lines(text: str) -> list[str]:
    # Only CRLF, LF and lone CR count as line breaks, matching editors and git.
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


class TextParser:
    """Line-oriented parser for source code, plain text, logs and config files."""

    name = "text"
    version = "1"
    isolated = False

    def __init__(self, chunk_lines: int = 50, max_chars: int = 8000):
        if chunk_lines < 1 or max_chars < 1:
            raise ValueError("chunk_lines and max_chars must be positive")
        self.chunk_lines = chunk_lines
        self.max_chars = max_chars

    @property
    def signature(self) -> str:
        return f"{self.name}:{self.version}:{self.chunk_lines}:{self.max_chars}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"chunk_lines": self.chunk_lines, "max_chars": self.max_chars}

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        if looks_binary(data):
            raise ParseError("binary content")
        text, encoding = decode_text(data)
        result.encoding = encoding
        lines = split_lines(text)
        if lines and lines[-1] == "":
            lines.pop()  # trailing newline does not start a new line
        result.line_count = len(lines)

        ordinal = 0
        for start in range(0, len(lines), self.chunk_lines):
            end = min(start + self.chunk_lines, len(lines))
            for chunk_start, chunk_end, body in self._bounded(lines, start, end):
                if body.strip():
                    yield Chunk(
                        ordinal=ordinal, text=body, coord_kind="line",
                        start_line=chunk_start + 1, end_line=chunk_end,
                    )
                    ordinal += 1

    def _bounded(self, lines: list[str], start: int, end: int) -> Iterator[tuple[int, int, str]]:
        """Split a line window further when it exceeds max_chars (e.g. minified files)."""
        buf: list[str] = []
        buf_start = start
        size = 0
        for i in range(start, end):
            line = lines[i]
            if len(line) > self.max_chars:
                if buf:
                    yield buf_start, i, "\n".join(buf)
                    buf, size = [], 0
                for off in range(0, len(line), self.max_chars):
                    yield i, i + 1, line[off: off + self.max_chars]
                buf_start = i + 1
                continue
            if size + len(line) + 1 > self.max_chars and buf:
                yield buf_start, i, "\n".join(buf)
                buf, size, buf_start = [], 0, i
            buf.append(line)
            size += len(line) + 1
        if buf:
            yield buf_start, end, "\n".join(buf)
