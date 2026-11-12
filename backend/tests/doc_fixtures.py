"""Builds document fixtures in code so tests need no binary files in the repository."""

import datetime as dt
import io
import xml.etree.ElementTree as ET
import zipfile


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


def make_scanned_pdf(text: str = "SCANNED OCR MARKER") -> bytes:
    import pymupdf as fitz

    source = fitz.open()
    source_page = source.new_page(width=600, height=800)
    source_page.insert_text((40, 150), text, fontsize=40)
    image = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
    scanned = fitz.open()
    page = scanned.new_page(width=600, height=800)
    page.insert_image(page.rect, stream=image)
    out = io.BytesIO()
    scanned.save(out)
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


def make_pptx() -> bytes:
    p = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    r = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    rel = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    def make_slide(title, body, table_rows=()):
        slide = ET.Element(p + "sld")
        common = ET.SubElement(slide, p + "cSld")
        tree = ET.SubElement(common, p + "spTree")
        ET.SubElement(tree, p + "nvGrpSpPr")
        ET.SubElement(tree, p + "grpSpPr")

        def add_shape(shape_id, name, text, placeholder=None):
            shape = ET.SubElement(tree, p + "sp")
            nv = ET.SubElement(shape, p + "nvSpPr")
            ET.SubElement(nv, p + "cNvPr", {"id": str(shape_id), "name": name})
            ET.SubElement(nv, p + "cNvSpPr")
            nonvisual = ET.SubElement(nv, p + "nvPr")
            if placeholder:
                ET.SubElement(nonvisual, p + "ph", {"type": placeholder})
            text_body = ET.SubElement(shape, p + "txBody")
            ET.SubElement(text_body, a + "bodyPr")
            ET.SubElement(text_body, a + "lstStyle")
            paragraph = ET.SubElement(text_body, a + "p")
            run = ET.SubElement(paragraph, a + "r")
            ET.SubElement(run, a + "t").text = text

        add_shape(2, "Title", title, "title")
        add_shape(3, "Body", body)
        if table_rows:
            frame = ET.SubElement(tree, p + "graphicFrame")
            nv = ET.SubElement(frame, p + "nvGraphicFramePr")
            ET.SubElement(nv, p + "cNvPr", {"id": "4", "name": "Table 1"})
            ET.SubElement(nv, p + "cNvGraphicFramePr")
            ET.SubElement(nv, p + "nvPr")
            transform = ET.SubElement(frame, p + "xfrm")
            ET.SubElement(transform, a + "off", {"x": "0", "y": "0"})
            ET.SubElement(transform, a + "ext", {"cx": "0", "cy": "0"})
            graphic = ET.SubElement(frame, a + "graphic")
            graphic_data = ET.SubElement(graphic, a + "graphicData", {"uri": "http://schemas.openxmlformats.org/drawingml/2006/table"})
            table = ET.SubElement(graphic_data, a + "tbl")
            ET.SubElement(table, a + "tblPr")
            grid = ET.SubElement(table, a + "tblGrid")
            ET.SubElement(grid, a + "gridCol", {"w": "1"})
            ET.SubElement(grid, a + "gridCol", {"w": "1"})
            for values in table_rows:
                row = ET.SubElement(table, a + "tr", {"h": "1"})
                for value in values:
                    cell = ET.SubElement(row, a + "tc")
                    text_body = ET.SubElement(cell, a + "txBody")
                    ET.SubElement(text_body, a + "bodyPr")
                    ET.SubElement(text_body, a + "lstStyle")
                    paragraph = ET.SubElement(text_body, a + "p")
                    run = ET.SubElement(paragraph, a + "r")
                    ET.SubElement(run, a + "t").text = value
                    ET.SubElement(cell, a + "tcPr")
        return ET.tostring(slide, encoding="utf-8", xml_declaration=True)

    presentation = ET.Element(p + "presentation")
    slide_list = ET.SubElement(presentation, p + "sldIdLst")
    ET.SubElement(slide_list, p + "sldId", {"id": "256", r + "id": "rId1"})
    ET.SubElement(slide_list, p + "sldId", {"id": "257", r + "id": "rId2"})
    relationships = ET.Element(rel + "Relationships")
    ET.SubElement(relationships, rel + "Relationship", {
        "Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
        "Target": "slides/slide1.xml",
    })
    ET.SubElement(relationships, rel + "Relationship", {
        "Id": "rId2", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
        "Target": "slides/slide2.xml",
    })
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/presentation.xml", ET.tostring(presentation, encoding="utf-8"))
        archive.writestr("ppt/_rels/presentation.xml.rels", ET.tostring(relationships, encoding="utf-8"))
        archive.writestr("ppt/slides/slide1.xml", make_slide("Fleet Status", "VT-ABC is active."))
        archive.writestr("ppt/slides/slide2.xml", make_slide(
            "Service Notes", "powerpoint_marker maintenance note.",
            [("Asset", "Status"), ("ppt_table_marker", "GROUNDED")],
        ))
    return out.getvalue()


CSV_TEXT = (
    'id;name;notes\n'
    '1;alpha;"plain"\n'
    '2;beta;"multi\nline note"\n'
    '3;gamma;"csv_marker caf\u00e9"\n'
)
