from ehelp.parsers.base import Parser
from ehelp.parsers.delimited import DelimitedParser
from ehelp.parsers.pdf import PdfParser
from ehelp.parsers.powerpoint import LegacyPptParser, PptxParser
from ehelp.parsers.sheets import OdsParser, XlsParser, XlsxParser
from ehelp.parsers.text import TextParser
from ehelp.parsers.word import DocxParser, LegacyDocParser, find_libreoffice

LINES, CHARS = 40, 2000

PARSER_CLASSES: dict[str, type] = {
    cls.name: cls
    for cls in (TextParser, DelimitedParser, PdfParser, DocxParser, LegacyDocParser, PptxParser, LegacyPptParser,
                XlsxParser, XlsParser, OdsParser)
}

TEXT_EXTENSIONS = {"txt", "md", "log", "json", "xml", "yaml", "yml", "ini", "cfg", "rtf", "html", "htm"}


def build(name: str, kwargs: dict) -> Parser:
    """Recreate a parser from its spec (used inside the sandbox process)."""
    return PARSER_CLASSES[name](**kwargs)


class ParserRegistry:
    def __init__(self, libreoffice_path: str = "", timeout_s: float = 120, ocr_enabled: bool = False):
        soffice = find_libreoffice(libreoffice_path)
        xlsx = XlsxParser(LINES, CHARS)
        self._by_ext: dict[str, Parser | None] = {
            "csv": DelimitedParser(",", LINES, CHARS),
            "tsv": DelimitedParser("\t", LINES, CHARS),
            "pdf": PdfParser(CHARS, ocr_enabled, ""),
            "docx": DocxParser(CHARS),
            "doc": LegacyDocParser(soffice, timeout_s, CHARS) if soffice else None,
            "ppt": LegacyPptParser(soffice, timeout_s, CHARS) if soffice else None,
            "pptx": PptxParser(CHARS),
            "xlsx": xlsx,
            "xlsm": xlsx,
            "xls": XlsParser(LINES, CHARS),
            "ods": OdsParser(LINES, CHARS),
        }
        self._text = TextParser(LINES, CHARS)

    def for_extension(self, ext: str) -> Parser | None:
        ext = ext.lower().lstrip(".")
        if ext in self._by_ext:
            return self._by_ext[ext]
        if ext in TEXT_EXTENSIONS:
            return self._text
        return None
