from opsintel.config import Settings
from opsintel.discovery import FileKind
from opsintel.parsers.base import Parser
from opsintel.parsers.delimited import DelimitedParser
from opsintel.parsers.pdf import PdfParser
from opsintel.parsers.sheets import OdsParser, XlsParser, XlsxParser
from opsintel.parsers.text import TextParser
from opsintel.parsers.word import DocxParser, LegacyDocParser, find_libreoffice

TEXT_KINDS = {"code", "text", "structured", "unknown"}

PARSER_CLASSES: dict[str, type] = {
    cls.name: cls
    for cls in (TextParser, DelimitedParser, PdfParser, DocxParser, LegacyDocParser, XlsxParser, XlsParser, OdsParser)
}


def build(name: str, kwargs: dict) -> Parser:
    """Recreate a parser from its spec (used inside the sandbox process)."""
    return PARSER_CLASSES[name](**kwargs)


class ParserRegistry:
    def __init__(self, settings: Settings):
        lines, chars = settings.chunk_lines, settings.chunk_max_chars
        self.text = TextParser(lines, chars)
        soffice = find_libreoffice(settings.libreoffice_path)
        doc = LegacyDocParser(soffice, settings.parse_timeout_s, chars) if soffice else None
        xlsx = XlsxParser(lines, chars)
        self._by_language: dict[str, Parser | None] = {
            "csv": DelimitedParser(",", lines, chars),
            "tsv": DelimitedParser("\t", lines, chars),
            "pdf": PdfParser(chars),
            "docx": DocxParser(chars),
            "doc": doc,
            "xlsx": xlsx,
            "xlsm": xlsx,
            "xls": XlsParser(lines, chars),
            "ods": OdsParser(lines, chars),
        }

    def for_kind(self, kind: FileKind) -> Parser | None:
        if kind.file_type in TEXT_KINDS:
            return self.text
        if kind.file_type in ("document", "spreadsheet"):
            return self._by_language.get(kind.language or "")
        return None

    @staticmethod
    def unsupported_reason(kind: FileKind) -> str:
        if kind.language == "doc":
            return "legacy .doc requires LibreOffice (install it or set LIBREOFFICE_PATH)"
        return f"no parser for .{kind.language}"
