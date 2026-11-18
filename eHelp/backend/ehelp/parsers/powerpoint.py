import io
import posixpath
import subprocess
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from ehelp.parsers.base import Chunk, ParseError, ParseResult

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": A_NS, "p": P_NS}


def _one_line(text: str) -> str:
    return " ".join(text.split())


class PptxParser:
    """Extract text and table rows from OOXML PowerPoint slides with slide-aware locations."""

    name = "pptx"
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
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                slide_paths = self._slide_paths(archive)
                if not slide_paths:
                    raise ParseError("PowerPoint presentation contains no slides")
                ordinal = 0
                for slide_number, slide_path in enumerate(slide_paths, start=1):
                    try:
                        root = ET.fromstring(archive.read(slide_path))
                    except (KeyError, ET.ParseError, DefusedXmlException) as exc:
                        raise ParseError(f"cannot read PowerPoint slide {slide_number}: {exc}") from exc
                    chunks = self._parse_slide(root, slide_number, ordinal)
                    yield from chunks
                    ordinal += len(chunks)
        except (OSError, zipfile.BadZipFile) as exc:
            raise ParseError(f"cannot open PowerPoint presentation: {exc}") from exc

    @staticmethod
    def _slide_paths(archive: zipfile.ZipFile) -> list[str]:
        try:
            presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
            relationships = ET.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
        except (KeyError, ET.ParseError, DefusedXmlException) as exc:
            raise ParseError(f"invalid PowerPoint presentation structure: {exc}") from exc
        targets = {
            relation.get("Id"): relation
            for relation in relationships.findall(f"{{{REL_NS}}}Relationship")
        }
        names = set(archive.namelist())
        paths = []
        for slide_id in presentation.findall(".//p:sldId", NS):
            relation = targets.get(slide_id.get(f"{{{R_NS}}}id"))
            if relation is None or relation.get("TargetMode") == "External":
                continue
            target = relation.get("Target", "").lstrip("/")
            path = target if target.startswith("ppt/") else posixpath.normpath(posixpath.join("ppt", target))
            if path not in names:
                raise ParseError(f"PowerPoint slide is missing: {path}")
            paths.append(path)
        return paths

    def _parse_slide(self, root: Element, slide_number: int, first_ordinal: int) -> list[Chunk]:
        tree = root.find("./p:cSld/p:spTree", NS)
        if tree is None:
            return []
        shapes = {id(shape): self._paragraphs(shape) for shape in tree.findall("./p:sp", NS)}
        title = self._slide_title(tree, shapes)
        section = f"Slide {slide_number}" + (f": {title}" if title else "")
        chunks: list[Chunk] = []
        lines: list[str] = []
        positions: list[int] = []
        kind: str | None = None
        table_number: int | None = None
        shape_paragraph = 0
        table_count = 0

        def flush() -> None:
            nonlocal lines, positions, kind, table_number
            if not lines:
                return
            extra = {"kind": kind, "items": positions, "slide": slide_number}
            if table_number is not None:
                extra["table"] = table_number
            chunks.append(Chunk(ordinal=first_ordinal + len(chunks), text="\n".join(lines),
                                coord_kind="section", section_path=section, extra=extra))
            lines, positions, kind, table_number = [], [], None, None

        def add(text: str, item_kind: str, position: int, item_table: int | None = None) -> None:
            nonlocal kind, table_number
            size = sum(len(line) + 1 for line in lines)
            if lines and (kind != item_kind or table_number != item_table or len(lines) >= self.chunk_items
                          or size + len(text) > self.max_chars):
                flush()
            if not lines:
                kind, table_number = item_kind, item_table
            lines.append(text[:self.max_chars])
            positions.append(position)

        for shape in list(tree):
            if shape.tag == f"{{{P_NS}}}sp":
                for text in shapes.get(id(shape), []):
                    shape_paragraph += 1
                    add(text, "paragraph", shape_paragraph)
            elif shape.tag == f"{{{P_NS}}}graphicFrame":
                table = shape.find(".//a:tbl", NS)
                if table is None:
                    continue
                table_count += 1
                for row_number, row in enumerate(table.findall("./a:tr", NS), start=1):
                    cells = [" ".join(self._paragraphs(cell))
                             for cell in row.findall("./a:tc", NS)]
                    if any(cells):
                        add(" | ".join(cells), "table", row_number, table_count)
        flush()
        return chunks

    def _paragraphs(self, element: Element) -> list[str]:
        paragraphs = []
        for paragraph in element.findall(".//a:p", NS):
            text = _one_line("".join(node.text or "" for node in paragraph.findall(".//a:t", NS)))
            if text:
                paragraphs.append(text)
        return paragraphs

    def _slide_title(self, tree: Element, shapes: dict[int, list[str]]) -> str:
        first_text = ""
        for shape in tree.findall("./p:sp", NS):
            paragraphs = shapes.get(id(shape), [])
            if not paragraphs:
                continue
            first_text = first_text or paragraphs[0]
            placeholder = shape.find("./p:nvSpPr/p:nvPr/p:ph", NS)
            if placeholder is not None and placeholder.get("type") in {"title", "ctrTitle"}:
                return paragraphs[0]
        return first_text


class LegacyPptParser:
    """Convert legacy .ppt with LibreOffice, then parse the resulting .pptx."""

    name = "ppt"
    version = "1"
    isolated = True

    def __init__(self, soffice: str, timeout_s: int = 120, max_chars: int = 8000):
        self.soffice = soffice
        self.timeout_s = timeout_s
        self.pptx = PptxParser(max_chars=max_chars)

    @property
    def signature(self) -> str:
        return f"{self.name}:{self.version}:{self.pptx.signature}:{self.soffice}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"soffice": self.soffice, "timeout_s": self.timeout_s,
                           "max_chars": self.pptx.max_chars}

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        with tempfile.TemporaryDirectory(prefix="ehelp-ppt-") as temp_dir:
            source = Path(temp_dir) / "input.ppt"
            source.write_bytes(data)
            profile = Path(temp_dir, "profile").as_uri()
            command = [self.soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                       "--convert-to", "pptx", "--outdir", temp_dir, str(source)]
            try:
                proc = subprocess.run(command, capture_output=True, timeout=self.timeout_s, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ParseError(f"LibreOffice conversion timed out after {self.timeout_s}s") from exc
            converted = Path(temp_dir) / "input.pptx"
            if proc.returncode != 0 or not converted.is_file():
                message = proc.stderr.decode(errors="replace")[:300]
                raise ParseError(f"LibreOffice could not convert .ppt: {message}")
            result.warnings.append("converted from .ppt with LibreOffice")
            yield from self.pptx.parse(converted.read_bytes(), result)
