import io

import fitz
import pytest
from docx import Document
from fastapi.testclient import TestClient

from ehelp.app import create_app
from ehelp.config import Config

ADMIN = {"iv-user": "503672", "iv-groups": "user,admin,localadmin", "iv-name": "Test Admin"}
USER = {"iv-user": "100200", "iv-groups": "user", "iv-name": "Plain User"}


def make_pdf(*pages: str) -> bytes:
    doc = fitz.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def make_docx(text: str) -> bytes:
    buf = io.BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(buf)
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path):
    config = Config(data_dir=tmp_path, dev_admin=False, max_upload_bytes=5 * 1024 * 1024, libreoffice_path="")
    with TestClient(create_app(config)) as c:
        yield c


@pytest.fixture()
def upload(client):
    def _upload(name, data, **fields):
        return client.post("/api/admin/documents", headers=ADMIN, files={"file": (name, data)}, data=fields)
    return _upload
