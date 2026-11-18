import io
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

from ehelp.parsers.base import Chunk, ParseError, ParseResult

HEADING_PREFIX = "heading "
LIBREOFFICE_CANDIDATES = [
    "soffice", "libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def _one_line(text: str) -> str:
    return " ".join(text.split())


class DocxParser:
    """Word (.docx): headings form the section path; paragraphs and table rows keep their document order.

    Each rendered line is one paragraph or one table row, so a match maps back to a paragraph/table position.
    Page numbers are not reported: Word pagination depends on the viewer.
    """

    name = "docx"
    version = "1"
    isolated = True

    def __init__(self, max_chars: int = 8000, chunk_items: int = 40):
        self.max_chars = max_chars
        self.chunk_items = chunk_items

    @property
    def signature(self) -> str:
        return f"{self.name}:{self.version}:{self.max_chars}:{self.chunk_items}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"max_chars": self.max_chars, "chunk_items": self.chunk_items}

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ParseError(f"cannot open Word document: {exc}") from exc

        headings: list[str] = []
        buf: list[str] = []
        buf_meta: dict = {}
        ordinal = 0
        paragraph_no = 0
        table_no = 0

        def flush():
            nonlocal ordinal, buf, buf_meta
            if buf:
                chunk = Chunk(ordinal=ordinal, text="\n".join(buf), coord_kind="section",
                              section_path=" > ".join(headings) or None, extra=buf_meta)
                ordinal += 1
                buf, buf_meta = [], {}
                return chunk
            return None

        def add(line: str, kind: str, position: int, table: int | None = None):
            nonlocal buf_meta
            out = None
            size = sum(len(b) + 1 for b in buf)
            if buf and (len(buf) >= self.chunk_items or size + len(line) > self.max_chars
                        or kind != buf_meta.get("kind") or table != buf_meta.get("table")):
                out = flush()
            if not buf:
                buf_meta = {"kind": kind, "items": []}
                if table is not None:
                    buf_meta["table"] = table
            buf.append(line[: self.max_chars])
            buf_meta["items"].append(position)  # paragraph number, or row number within the table
            return out

        for element in document.element.body.iterchildren():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "p":
                paragraph = Paragraph(element, document)
                text = _one_line(paragraph.text)
                paragraph_no += 1
                if not text:
                    continue
                style = (paragraph.style.name if paragraph.style is not None else "") or ""
                level = self._heading_level(style)
                if level is not None:
                    if (c := flush()) is not None:
                        yield c
                    del headings[max(level - 1, 0):]
                    headings.append(text)
                if (c := add(text, "paragraph", paragraph_no)) is not None:
                    yield c
            elif tag == "tbl":
                table_no += 1
                table = Table(element, document)
                for row_no, row in enumerate(table.rows, start=1):
                    cells: list[str] = []
                    for cell in row.cells:
                        value = _one_line(cell.text)
                        if not cells or cells[-1] != value:  # merged cells repeat their text
                            cells.append(value)
                    if any(cells):
                        line = " | ".join(cells)
                        if (c := add(line, "table", row_no, table_no)) is not None:
                            yield c
        if (c := flush()) is not None:
            yield c

    @staticmethod
    def _heading_level(style: str) -> int | None:
        s = style.lower()
        if s == "title":
            return 1
        if s.startswith(HEADING_PREFIX):
            digits = s[len(HEADING_PREFIX):].strip()
            if digits.isdigit():
                return int(digits)
        return None


def find_libreoffice(configured: str = "") -> str | None:
    for candidate in [configured, *LIBREOFFICE_CANDIDATES]:
        if not candidate:
            continue
        path = shutil.which(candidate) or (candidate if os.path.isfile(candidate) else None)
        if path:
            return path
    return None


class LegacyDocParser:
    """Word 97-2003 (.doc): converted to .docx with headless LibreOffice, then parsed as .docx."""

    name = "doc"
    version = "1"
    isolated = True

    def __init__(self, soffice: str, timeout_s: int = 120, max_chars: int = 8000):
        self.soffice = soffice
        self.timeout_s = timeout_s
        self.docx = DocxParser(max_chars=max_chars)

    @property
    def signature(self) -> str:
        return f"{self.name}:{self.version}:{self.docx.signature}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"soffice": self.soffice, "timeout_s": self.timeout_s, "max_chars": self.docx.max_chars}

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        with tempfile.TemporaryDirectory(prefix="ehelp-doc-") as tmp:
            src = Path(tmp) / "input.doc"
            src.write_bytes(data)
            profile = Path(tmp, "profile").as_uri()  # private profile: parallel conversions must not share a lock
            cmd = [self.soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                   "--convert-to", "docx", "--outdir", tmp, str(src)]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=self.timeout_s, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ParseError(f"LibreOffice conversion timed out after {self.timeout_s}s") from exc
            out = Path(tmp) / "input.docx"
            if proc.returncode != 0 or not out.is_file():
                raise ParseError(f"LibreOffice could not convert .doc: {proc.stderr.decode(errors='replace')[:300]}")
            result.warnings.append("converted from .doc with LibreOffice")
            yield from self.docx.parse(out.read_bytes(), result)
