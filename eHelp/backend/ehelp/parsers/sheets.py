import datetime as dt
import io
import itertools
from collections.abc import Iterable, Iterator

from ehelp.parsers.base import Chunk, ParseError, ParseResult, bounded_groups

MAX_COLUMNS = 300
MAX_VALUE_CHARS = 500
MAX_REPEATED_ROWS = 1000


def column_letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def display(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ") if value.time() != dt.time(0) else value.date().isoformat()
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    text = " ".join(str(value).split())
    return text[:MAX_VALUE_CHARS] if text else None


Cell = tuple[int, str]  # (1-based column, rendered "value" or "value [=formula]")


def _looks_numeric(text: str) -> bool:
    try:
        float(text.split(" [", 1)[0])
        return True
    except ValueError:
        return False


class _SheetRenderer:
    """Renders rows as `A5: value | C5: value [=SUM(..)]` so every match carries its own cell reference."""

    def __init__(self, chunk_rows: int, max_chars: int):
        self.chunk_rows = chunk_rows
        self.max_chars = max_chars

    def chunks(self, sheet: str, rows: Iterable[tuple[int, list[Cell]]], start_ordinal: int,
               extra: dict) -> Iterator[Chunk]:
        rendered: list[tuple[int, str]] = []
        headers: dict[str, str] | None = None
        for row_num, cells in rows:
            cells = [c for c in cells if c[1]][:MAX_COLUMNS]
            if not cells:
                continue
            if headers is None:
                # First non-empty row is treated as the header row only if none of its values are numbers.
                headers = {} if any(_looks_numeric(t) for _, t in cells) else {
                    column_letter(col): text for col, text in cells}
            rendered.append((row_num, " | ".join(f"{column_letter(col)}{row_num}: {text}" for col, text in cells)))
        meta = {**extra, "headers": headers or {}}
        ordinal = start_ordinal
        for s, e in bounded_groups([r[1] for r in rendered], self.chunk_rows, self.max_chars):
            group = rendered[s:e]
            yield Chunk(ordinal=ordinal, text="\n".join(r[1] for r in group), coord_kind="cell", sheet=sheet,
                        start_line=group[0][0], end_line=group[-1][0], extra=meta)
            ordinal += 1


class _SpreadsheetParser:
    name = "sheet"
    version = "1"
    isolated = True

    def __init__(self, chunk_rows: int = 50, max_chars: int = 8000):
        self.chunk_rows = chunk_rows
        self.max_chars = max_chars
        self.renderer = _SheetRenderer(chunk_rows, max_chars)

    @property
    def signature(self) -> str:
        return f"{self.name}:{self.version}:{self.chunk_rows}:{self.max_chars}"

    def spec(self) -> tuple[str, dict]:
        return self.name, {"chunk_rows": self.chunk_rows, "max_chars": self.max_chars}


class XlsxParser(_SpreadsheetParser):
    """Excel 2007+ (.xlsx/.xlsm): cached values plus formulas; streamed in read-only mode."""

    name = "xlsx"

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        import openpyxl

        try:
            values_wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            formula_wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False)
        except Exception as exc:
            raise ParseError(f"cannot open Excel workbook: {exc}") from exc
        missing_cache = 0
        ordinal = 0
        try:
            for ws_v in values_wb.worksheets:
                ws_f = formula_wb[ws_v.title]

                def rows(ws_v=ws_v, ws_f=ws_f):
                    nonlocal missing_cache
                    pairs = itertools.zip_longest(ws_v.iter_rows(min_row=1, min_col=1, values_only=True),
                                                  ws_f.iter_rows(min_row=1, min_col=1, values_only=True),
                                                  fillvalue=())
                    for row_num, (vals, forms) in enumerate(pairs, start=1):
                        cells: list[Cell] = []
                        for col, (v, f) in enumerate(itertools.zip_longest(vals, forms), start=1):
                            formula = f if isinstance(f, str) and f.startswith("=") else None
                            shown = display(v)
                            if formula:
                                if shown is None:
                                    missing_cache += 1
                                    cells.append((col, f"[{formula[:MAX_VALUE_CHARS]}] (no cached value)"))
                                else:
                                    cells.append((col, f"{shown} [{formula[:MAX_VALUE_CHARS]}]"))
                            elif shown is not None:
                                cells.append((col, shown))
                        yield row_num, cells

                extra = {"hidden": ws_v.sheet_state != "visible"} if ws_v.sheet_state != "visible" else {}
                for chunk in self.renderer.chunks(ws_v.title, rows(), ordinal, extra):
                    ordinal = chunk.ordinal + 1
                    yield chunk
        finally:
            values_wb.close()
            formula_wb.close()
        if missing_cache:
            result.warnings.append(f"{missing_cache} formula cell(s) have no cached value; the file was saved "
                                   "without recalculation, so only the formula is indexed")


class XlsParser(_SpreadsheetParser):
    """Excel 97-2003 (.xls) via xlrd: cell values only (xlrd does not expose formulas)."""

    name = "xls"

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        import xlrd

        try:
            book = xlrd.open_workbook(file_contents=data, on_demand=True)
        except Exception as exc:
            raise ParseError(f"cannot open .xls workbook: {exc}") from exc
        ordinal = 0
        try:
            for index in range(book.nsheets):
                sheet = book.sheet_by_index(index)

                def rows(sheet=sheet):
                    for r in range(sheet.nrows):
                        cells: list[Cell] = []
                        for c in range(min(sheet.ncols, MAX_COLUMNS)):
                            cell = sheet.cell(r, c)
                            value = cell.value
                            if cell.ctype == xlrd.XL_CELL_DATE:
                                try:
                                    value = xlrd.xldate_as_datetime(value, book.datemode)
                                except (ValueError, OverflowError):
                                    pass
                            elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                                value = bool(value)
                            elif cell.ctype == xlrd.XL_CELL_ERROR:
                                value = xlrd.error_text_from_code.get(value, "#ERR")
                            shown = display(value if value != "" else None)
                            if shown is not None:
                                cells.append((c + 1, shown))
                        yield r + 1, cells

                for chunk in self.renderer.chunks(sheet.name, rows(), ordinal, {}):
                    ordinal = chunk.ordinal + 1
                    yield chunk
                book.unload_sheet(index)
        finally:
            book.release_resources()
        result.warnings.append(".xls formulas are not available; cell values only")


class OdsParser(_SpreadsheetParser):
    """OpenDocument spreadsheets (.ods) via odfpy, honouring repeated rows/columns."""

    name = "ods"

    def parse(self, data: bytes, result: ParseResult) -> Iterator[Chunk]:
        from odf import teletype
        from odf.opendocument import load
        from odf.table import Table, TableRow

        try:
            doc = load(io.BytesIO(data))
        except Exception as exc:
            raise ParseError(f"cannot open .ods spreadsheet: {exc}") from exc
        ordinal = 0
        for table in doc.spreadsheet.getElementsByType(Table):

            def rows(table=table):
                row_num = 0
                for tr in table.getElementsByType(TableRow):
                    repeat = int(tr.getAttribute("numberrowsrepeated") or 1)
                    cells: list[Cell] = []
                    col = 0
                    for tc in tr.childNodes:
                        if tc.qname[1] not in ("table-cell", "covered-table-cell"):
                            continue
                        col_repeat = int(tc.getAttribute("numbercolumnsrepeated") or 1)
                        shown = self._cell_text(tc, teletype)
                        if shown is not None:
                            for k in range(min(col_repeat, MAX_COLUMNS)):
                                cells.append((col + k + 1, shown))
                        col += col_repeat
                        if col >= MAX_COLUMNS:
                            break
                    if cells:
                        for k in range(min(repeat, MAX_REPEATED_ROWS)):
                            yield row_num + k + 1, cells
                    row_num += repeat

            for chunk in self.renderer.chunks(table.getAttribute("name") or "Sheet", rows(), ordinal, {}):
                ordinal = chunk.ordinal + 1
                yield chunk

    @staticmethod
    def _cell_text(tc, teletype) -> str | None:
        vtype = tc.getAttribute("valuetype") if tc.qname[1] == "table-cell" else None
        if vtype in ("float", "percentage", "currency"):
            raw = tc.getAttribute("value")
            try:
                shown = display(float(raw)) if raw is not None else None
            except ValueError:
                shown = display(raw)
        elif vtype == "date":
            shown = display(tc.getAttribute("datevalue"))
        elif vtype == "boolean":
            shown = "TRUE" if (tc.getAttribute("booleanvalue") or "").lower() == "true" else "FALSE"
        else:
            shown = display(teletype.extractText(tc))
        formula = tc.getAttribute("formula") if tc.qname[1] == "table-cell" else None
        if formula:
            formula = formula.split(":", 1)[1] if formula.startswith("of:") else formula
            return f"{shown} [{formula[:MAX_VALUE_CHARS]}]" if shown is not None else f"[{formula}] (no cached value)"
        return shown
