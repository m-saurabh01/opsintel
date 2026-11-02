from collections.abc import Iterator

from opsintel.parsers.base import Chunk, ParseError, ParseResult, bounded_groups

MIN_PAGE_TEXT_CHARS = 10


class PdfParser:
    """PyMuPDF text extraction: chunks never span pages; section titles come from the PDF outline."""

    name = "pdf"
    version = "1"
    isolated = True

    def __init__(self, max_chars: int = 8000):
        self.max_chars = max_chars

    @property
    def signature(self) -> str:
        import pymupdf

        return f"{self.name}:{self.version}:{self.max_chars}:pymupdf-{pymupdf.VersionBind}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"max_chars": self.max_chars}

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        import pymupdf

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise ParseError(f"cannot open PDF: {exc}") from exc
        with doc:
            if doc.needs_pass:
                raise ParseError("encrypted PDF (password required)")
            if doc.page_count == 0:
                raise ParseError("PDF has no pages")
            sections = self._page_sections(doc)
            scanned: list[int] = []
            ordinal = 0
            for index, page in enumerate(doc):
                page_no = index + 1
                text = page.get_text("text", sort=True)
                if len(text.strip()) < MIN_PAGE_TEXT_CHARS:
                    if page.get_images(full=False):
                        scanned.append(page_no)
                    if not text.strip():
                        continue
                lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
                while lines and not lines[-1]:
                    lines.pop()
                for s, e in bounded_groups(lines, len(lines) or 1, self.max_chars):
                    body = "\n".join(lines[s:e]).strip()
                    if body:
                        yield Chunk(ordinal=ordinal, text=body, coord_kind="page", page=page_no,
                                    section_path=sections.get(page_no), extra={"page_count": doc.page_count})
                        ordinal += 1
            result.line_count = None
            if scanned:
                pages = ", ".join(map(str, scanned[:20])) + ("…" if len(scanned) > 20 else "")
                result.warnings.append(f"{len(scanned)} page(s) look scanned without a text layer (OCR not "
                                       f"enabled): {pages}")
                if ordinal == 0:
                    raise ParseError("scanned PDF without a text layer; OCR is not enabled")

    @staticmethod
    def _page_sections(doc) -> dict[int, str]:
        toc = doc.get_toc(simple=True)
        if not toc:
            return {}
        by_page: dict[int, str] = {}
        stack: list[str] = []
        entries = sorted(((max(1, p), lvl, title.strip()) for lvl, title, p in toc), key=lambda e: e[0])
        idx = 0
        for page_no in range(1, doc.page_count + 1):
            while idx < len(entries) and entries[idx][0] <= page_no:
                _, lvl, title = entries[idx]
                del stack[lvl - 1:]
                stack.append(title)
                idx += 1
            if stack:
                by_page[page_no] = " > ".join(stack)
        return by_page
