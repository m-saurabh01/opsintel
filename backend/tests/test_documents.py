import pytest

from opsintel.indexing import FileWriter, LocalIndexer, register_local_repo
from opsintel.parsers.base import ParseError, ParseResult
from opsintel.parsers.delimited import DelimitedParser
from opsintel.parsers.pdf import PdfParser
from opsintel.parsers.sandbox import ParserSandbox, ParseTimeout
from opsintel.parsers.sheets import OdsParser, XlsParser, XlsxParser, column_letter
from opsintel.parsers.word import DocxParser
from opsintel.search import SearchRequest, search
from tests import doc_fixtures as fx
from tests.conftest import write


def parse(parser, data):
    result = ParseResult()
    return list(parser.parse(data, result)), result


def one(conn, q, **kw):
    [r] = search(conn, SearchRequest(q=q, **kw))["results"]
    return r


@pytest.fixture
def indexed(conn, settings, repo_dir, monkeypatch):
    monkeypatch.setattr("opsintel.parsers.registry.find_libreoffice", lambda *_: None)
    write(repo_dir / "docs" / "deploy.pdf", fx.make_pdf())
    write(repo_dir / "docs" / "guide.docx", fx.make_docx())
    write(repo_dir / "data" / "fleet.xlsx", fx.make_xlsx())
    write(repo_dir / "data" / "legacy.xls", fx.make_xls())
    write(repo_dir / "data" / "ops.ods", fx.make_ods())
    write(repo_dir / "data" / "notes.csv", fx.CSV_TEXT.encode("latin-1"))
    write(repo_dir / "data" / "plain.tsv", "host\tport\nalpha_host\t8080\n")
    write(repo_dir / "docs" / "old.doc", b"\xd0\xcf\x11\xe0legacy")
    stats = LocalIndexer(conn, settings).index_repo(register_local_repo(conn, "docs", repo_dir))
    return stats


def test_all_formats_indexed(conn, indexed):
    status = {r["path"]: (r["status"], r["status_reason"]) for r in conn.execute("SELECT * FROM files")}
    assert {p: s for p, (s, _) in status.items()} == {
        "docs/deploy.pdf": "indexed", "docs/guide.docx": "indexed", "data/fleet.xlsx": "indexed",
        "data/legacy.xls": "indexed", "data/ops.ods": "indexed", "data/notes.csv": "indexed",
        "data/plain.tsv": "indexed", "docs/old.doc": "unsupported",
    }
    assert "scanned" in status["docs/deploy.pdf"][1]
    assert "no cached value" in status["data/fleet.xlsx"][1]


def test_pdf_page_and_section(conn, indexed):
    r = one(conn, "restore_previous_war")
    assert r["location"] == {"kind": "page", "page": 2, "section": "Deployment > Rollback"}
    assert r["preview"][0]["label"] == "p.2"


def test_pdf_scanned_only_and_encrypted():
    with pytest.raises(ParseError, match="encrypted"):
        parse(PdfParser(), fx.make_pdf(password="s3cret"))
    chunks, result = parse(PdfParser(), fx.make_pdf())
    assert [c.page for c in chunks] == [1, 2]
    assert "3" in result.warnings[0]


def test_docx_sections_paragraphs_tables(conn, indexed):
    r = one(conn, "db2_pool_size")
    assert r["location"]["section"] == "Configuration > Database"
    assert r["location"]["paragraph"] == 6  # empty paragraph still counts in document order
    t = one(conn, "timeout_key")
    assert (t["location"]["table"], t["location"]["table_row"]) == (1, 2)
    assert any(p["text"] == "timeout_key | 45" and p["label"] == "T1.r2" for p in t["preview"])


def test_xlsx_cells_headers_formulas_hidden_sheets(conn, indexed):
    r = one(conn, "VT-XYZ", mode="exact")
    assert r["location"] == {"kind": "cell", "sheet": "Fleet", "cell": "A3", "row": 3, "column": "A",
                             "header": "tail_number"}
    model = one(conn, "ATR 72-600", mode="phrase")
    assert model["location"]["cell"] == "B3" and model["location"]["header"] == "model"
    formula = one(conn, "SUM(C2:C3)", mode="exact")
    assert formula["location"]["cell"] == "C5"
    assert one(conn, "2026-10-01", mode="exact")["location"]["cell"] == "A6"
    assert one(conn, "hidden_sheet_value")["location"]["sheet"] == "Secrets"


def test_xls_and_ods(conn, indexed):
    r = one(conn, "legacy_xls_marker")
    assert (r["location"]["sheet"], r["location"]["cell"], r["location"]["header"]) == ("Legacy", "B2", "description")
    assert any("C2: 2019-04-12" in p["text"] for p in r["preview"])
    o = one(conn, "ods_station_marker")
    assert (o["location"]["sheet"], o["location"]["cell"]) == ("Ops", "A5")  # 3 repeated blank rows skipped


def test_csv_rows_columns_and_encoding(conn, indexed):
    r = one(conn, "csv_marker")
    assert r["location"] == {"kind": "row", "row": 4, "column_index": 3, "column": "notes"}
    assert any(p["text"] == "row 4: 3 | gamma | csv_marker café" for p in r["preview"])
    multi = one(conn, "multi line", mode="phrase")
    assert multi["location"]["row"] == 3
    tsv = one(conn, "alpha_host")
    assert tsv["location"]["column"] == "host"


def test_delimited_parser_physical_lines():
    chunks, result = parse(DelimitedParser(), fx.CSV_TEXT.encode())
    assert result.line_count == 5
    [c] = chunks
    assert (c.row_num, c.start_line, c.end_line) == (1, 1, 5)
    assert c.extra["headers"] == ["id", "name", "notes"] and c.extra["delimiter"] == ";"


def test_legacy_doc_without_libreoffice_is_reported(conn, indexed):
    reason = conn.execute("SELECT status_reason FROM files WHERE path = 'docs/old.doc'").fetchone()[0]
    assert "LibreOffice" in reason


def test_parse_cache_reuses_identical_documents(conn, settings, repo_dir):
    data = fx.make_xlsx()
    write(repo_dir / "a" / "copy1.xlsx", data)
    write(repo_dir / "b" / "copy2.xlsx", data)
    indexer = LocalIndexer(conn, settings)
    indexer.index_repo(register_local_repo(conn, "dup", repo_dir))
    assert (indexer.writer.cache.misses, indexer.writer.cache.hits) == (1, 1)
    assert len(search(conn, SearchRequest(q="VT-ABC", mode="exact"))["results"]) == 2


def test_sandbox_timeout_and_recovery():
    sandbox = ParserSandbox(timeout_s=0.001)
    try:
        with pytest.raises(ParseTimeout):
            sandbox.run(XlsxParser(), fx.make_xlsx())
        sandbox.timeout_s = 60
        chunks, _ = sandbox.run(DocxParser(), fx.make_docx())  # a fresh process is started after the kill
        assert chunks
    finally:
        sandbox.close()


def test_malformed_documents_are_reported_not_raised():
    for parser in (PdfParser(), DocxParser(), XlsxParser(), XlsParser(), OdsParser()):
        with pytest.raises(ParseError):
            parse(parser, b"this is not a real document")


def test_chunk_viewer_api(client, settings, conn, repo_dir, indexed):
    r = one(conn, "VT-XYZ", mode="exact")
    body = client.get(f"/api/files/{r['file_id']}/chunks/{r['chunk_id']}").json()
    target = next(c for c in body["chunks"] if c["is_target"])
    assert target["heading"] == "Fleet · rows 1–6"
    assert target["extra"]["headers"]["A"] == "tail_number"
    assert [ln["label"] for ln in target["lines"]][:3] == ["row 1", "row 2", "row 3"]
    assert client.get(f"/api/files/{r['file_id']}/chunks/999999").status_code == 404
    target_cell = client.get(f"/api/files/{r['file_id']}/chunks/{r['chunk_id']}", params={"cell": "A3"}).json()
    assert target_cell["target_cell"] == "A3"
    assert target_cell["chunks"][0]["location"]["cell"] == "A3"
    assert target_cell["chunks"][0]["lines"][2]["cells"][0]["value"] == "VT-XYZ"
    csv_result = one(conn, "csv_marker")
    csv_view = client.get(f"/api/files/{csv_result['file_id']}/chunks/{csv_result['chunk_id']}").json()
    assert csv_view["chunks"][0]["lines"][0]["label"] == "row 1"


def test_file_metadata_does_not_expose_repository_location(client, indexed, conn):
    file_id = conn.execute("SELECT id FROM files WHERE path = 'docs/deploy.pdf'").fetchone()[0]
    response = client.get(f"/api/files/{file_id}")
    assert response.status_code == 200
    assert "repo_location" not in response.json() and "repo_kind" not in response.json()


def test_raw_pdf_endpoint_serves_the_indexed_revision(client, conn, repo_dir, indexed):
    file_id = conn.execute("SELECT id FROM files WHERE path = 'docs/deploy.pdf'").fetchone()[0]
    response = client.get(f"/api/files/{file_id}/raw.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")

    text_id = conn.execute("SELECT id FROM files WHERE path = 'data/notes.csv'").fetchone()[0]
    assert client.get(f"/api/files/{text_id}/raw.pdf").status_code == 415


def test_raw_pdf_endpoint_rejects_stale_local_source(client, conn, repo_dir, indexed):
    file_id = conn.execute("SELECT id FROM files WHERE path = 'docs/deploy.pdf'").fetchone()[0]
    (repo_dir / "docs" / "deploy.pdf").write_bytes(b"%PDF-changed-after-index")
    assert client.get(f"/api/files/{file_id}/raw.pdf").status_code == 409


def test_writer_signature_changes_trigger_reparse(settings, conn):
    from opsintel.discovery import FileKind

    w = FileWriter(conn, settings)
    assert w.parser_signature(FileKind("spreadsheet", "csv")).startswith("delimited:")
    assert w.parser_signature(FileKind("binary", None)) is None
    assert column_letter(1) == "A" and column_letter(28) == "AB"
