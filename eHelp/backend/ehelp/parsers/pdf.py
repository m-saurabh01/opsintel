import os
import shutil
import subprocess
from collections.abc import Iterator

from ehelp.parsers.base import Chunk, ParseError, ParseResult, bounded_groups

MIN_PAGE_TEXT_CHARS = 10
OCR_DPI = 200
OCR_TIMEOUT_S = 30


def find_tesseract(configured: str = "") -> str | None:
    candidate = configured or "tesseract"
    return shutil.which(candidate) or (candidate if os.path.isfile(candidate) else None)


class PdfParser:
    """PyMuPDF text extraction: chunks never span pages; section titles come from the PDF outline."""

    name = "pdf"
    version = "2"
    isolated = True

    def __init__(self, max_chars: int = 8000, ocr_enabled: bool = False, tesseract_path: str = ""):
        self.max_chars = max_chars
        self.ocr_enabled = ocr_enabled
        self.tesseract_path = tesseract_path
        self.tesseract = find_tesseract(tesseract_path) if ocr_enabled else None

    @property
    def signature(self) -> str:
        import pymupdf

        return f"{self.name}:{self.version}:{self.max_chars}:ocr-{self.ocr_enabled}:{self.tesseract_path}:" \
               f"pymupdf-{pymupdf.VersionBind}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"max_chars": self.max_chars, "ocr_enabled": self.ocr_enabled,
                           "tesseract_path": self.tesseract_path}

    def _ocr_page(self, page, page_no: int) -> str:
        if self.tesseract is None:
            raise ParseError("Tesseract was not found; set TESSERACT_PATH or add it to PATH")
        image = page.get_pixmap(dpi=OCR_DPI, alpha=False).tobytes("png")
        try:
            process = subprocess.run(
                [self.tesseract, "stdin", "stdout", "-l", "eng", "--psm", "6"],
                input=image, capture_output=True, timeout=OCR_TIMEOUT_S, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ParseError(f"Tesseract timed out on PDF page {page_no}") from exc
        except OSError as exc:
            raise ParseError(f"could not run Tesseract: {exc}") from exc
        if process.returncode:
            detail = process.stderr.decode(errors="replace").strip()[:250]
            raise ParseError(f"Tesseract failed on PDF page {page_no}: {detail or process.returncode}")
        return process.stdout.decode("utf-8", errors="replace").strip()

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
            ocr_pages: list[int] = []
            ocr_errors: list[str] = []
            ordinal = 0
            for index, page in enumerate(doc):
                page_no = index + 1
                text = page.get_text("text", sort=True)
                if len(text.strip()) < MIN_PAGE_TEXT_CHARS:
                    if page.get_images(full=False):
                        scanned.append(page_no)
                        if self.ocr_enabled:
                            try:
                                text = self._ocr_page(page, page_no)
                                if text:
                                    ocr_pages.append(page_no)
                            except ParseError as exc:
                                ocr_errors.append(str(exc))
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
                if not self.ocr_enabled:
                    result.warnings.append(f"{len(scanned)} page(s) look scanned without a text layer (OCR not "
                                           f"enabled): {pages}")
                elif ocr_pages:
                    ocr_list = ", ".join(map(str, ocr_pages[:20])) + ("…" if len(ocr_pages) > 20 else "")
                    result.warnings.append(f"OCR extracted text from {len(ocr_pages)} scanned page(s): {ocr_list}")
                if ocr_errors:
                    result.warnings.extend(ocr_errors[:3])
                if ordinal == 0:
                    reason = "scanned PDF without a text layer; OCR is not enabled" if not self.ocr_enabled \
                        else (ocr_errors[0] if ocr_errors else "Tesseract produced no text from scanned pages")
                    raise ParseError(reason)

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
