"""Builds document fixtures in code so tests need no binary files in the repository."""

import datetime as dt
import io


def make_pdf(scanned_page: bool = True, password: str | None = None) -> bytes:
    import pymupdf as fitz

    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Deployment Procedure")
    p1.insert_text((72, 100), "Step 1: copy fleet-portal.war to /opt/tomcat/webapps")
    p2 = doc.new_page()
    p2.insert_text((72, 72), "Rollback")
    p2.insert_text((72, 100), "Run restore_previous_war from /opt/releases")
    if scanned_page:
        p3 = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64), False)
        pix.clear_with(180)
        p3.insert_image(fitz.Rect(72, 72, 300, 300), pixmap=pix)
    doc.set_toc([[1, "Deployment", 1], [2, "Rollback", 2]])
    out = io.BytesIO()
    if password:
        doc.save(out, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password)
    else:
        doc.save(out)
    return out.getvalue()


def make_docx() -> bytes:
    import docx

    d = docx.Document()
    d.add_heading("Installation", level=1)
    d.add_paragraph("Install the monitoring agent on every node.")
    d.add_paragraph("")
    d.add_heading("Configuration", level=1)
    d.add_heading("Database", level=2)
    d.add_paragraph("Set db2_pool_size to 20 for production.")
    table = d.add_table(rows=3, cols=2)
    for r, (k, v) in enumerate([("Key", "Value"), ("timeout_key", "45"), ("retry_key", "3")]):
        table.cell(r, 0).text, table.cell(r, 1).text = k, v
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def make_xlsx() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fleet"
    ws.append(["tail_number", "model", "flights"])
    ws.append(["VT-ABC", "A320neo", 120])
    ws.append(["VT-XYZ", "ATR 72-600", 80])
    ws.append([None, None, None])
    ws["C5"] = "=SUM(C2:C3)"  # openpyxl does not calculate, so there is no cached value
    ws["A6"] = dt.date(2026, 10, 1)
    hidden = wb.create_sheet("Secrets")
    hidden["B2"] = "hidden_sheet_value"
    hidden.sheet_state = "hidden"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def make_xls() -> bytes:
    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Legacy")
    for c, h in enumerate(["part_no", "description", "installed"]):
        ws.write(0, c, h)
    ws.write(1, 0, "PN-7781")
    ws.write(1, 1, "hydraulic pump legacy_xls_marker")
    ws.write(1, 2, dt.datetime(2019, 4, 12), xlwt.easyxf(num_format_str="YYYY-MM-DD"))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def make_ods() -> bytes:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    doc = OpenDocumentSpreadsheet()
    table = Table(name="Ops")

    def row(*values):
        tr = TableRow()
        for v in values:
            if isinstance(v, int | float):
                tc = TableCell(valuetype="float", value=v)
                tc.addElement(P(text=str(v)))
            else:
                tc = TableCell(valuetype="string")
                tc.addElement(P(text=v))
            tr.addElement(tc)
        return tr

    table.addElement(row("station", "count"))
    blank = TableRow(numberrowsrepeated=3)
    blank.addElement(TableCell())
    table.addElement(blank)
    table.addElement(row("ods_station_marker", 42))
    doc.spreadsheet.addElement(table)
    out = io.BytesIO()
    doc.write(out)
    return out.getvalue()


CSV_TEXT = (
    'id;name;notes\n'
    '1;alpha;"plain"\n'
    '2;beta;"multi\nline note"\n'
    '3;gamma;"csv_marker caf\u00e9"\n'
)
