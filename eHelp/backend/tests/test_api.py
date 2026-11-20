import json

from tests.conftest import ADMIN, USER, make_docx, make_pdf


def test_identity_from_gateway_headers(client):
    assert client.get("/api/me").json()["is_admin"] is False
    assert client.get("/api/me", headers=USER).json() == {
        "user_id": "100200", "name": "Plain User", "groups": ["user"], "is_admin": False}
    me = client.get("/api/me", headers=ADMIN).json()
    assert me["is_admin"] is True and me["user_id"] == "503672" and me["name"] == "Test Admin"


def test_admin_endpoints_require_admin_group(client):
    files = {"file": ("a.txt", b"hello")}
    assert client.post("/api/admin/documents", files=files).status_code == 403
    assert client.post("/api/admin/documents", files=files, headers=USER).status_code == 403
    assert client.post("/api/admin/documents", files=files, headers=ADMIN).status_code == 201


def test_upload_search_and_pages(client, upload):
    cats = {c["slug"]: c["id"] for c in client.get("/api/categories").json()}
    pdf = upload("hydraulic.pdf", make_pdf("intro page", "The hydraulic system inspection is required"),
                 category_id=cats["engineering"], tags="A320, Hydraulic")
    assert pdf.status_code == 201
    body = pdf.json()
    assert body["page_count"] == 2 and body["index_status"] == "indexed" and body["tags"] == ["A320", "Hydraulic"]
    upload("notes.docx", make_docx("Landing gear repair notes"), category_id=cats["repairs"])

    res = client.get("/api/search", params={"q": "hydraulic inspection"}).json()
    assert res["total"] == 1
    item = res["items"][0]
    assert item["document"]["id"] == body["id"] and item["snippets"][0]["page"] == 2
    assert "\x02" in item["snippets"][0]["text"]

    assert client.get("/api/search", params={"q": "gear", "category": "engineering"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "gear", "category": "repairs"}).json()["total"] == 1
    assert client.get("/api/search", params={"q": "inspection is required", "mode": "exact"}).json()["total"] == 1
    assert client.get("/api/search", params={"q": "required inspection", "mode": "exact"}).json()["total"] == 0


def test_listing_sort_filter_and_counts(client, upload):
    cats = {c["slug"]: c["id"] for c in client.get("/api/categories").json()}
    upload("b.txt", b"beta", title="Beta", category_id=cats["aviation"])
    upload("a.txt", b"alpha", title="Alpha", category_id=cats["aviation"])
    upload("c.txt", b"gamma", title="Gamma", category_id=cats["repairs"])
    data = client.get("/api/documents", params={"category": "aviation", "sort": "title"}).json()
    assert [d["title"] for d in data["items"]] == ["Alpha", "Beta"] and data["total"] == 2
    assert client.get("/api/documents", params={"category": "aviation", "q": "gamma"}).json()["total"] == 0
    assert client.get("/api/documents", params={"q": "gamma"}).json()["total"] == 1
    assert client.get("/api/documents", params={"modified_days": 1}).json()["total"] == 3
    counts = {c["slug"]: c["count"] for c in client.get("/api/categories").json()}
    assert counts["aviation"] == 2 and counts["repairs"] == 1


def test_related_manual_and_automatic(client, upload):
    cat = client.get("/api/categories").json()[0]["id"]
    a = upload("a.txt", b"x", title="A320 Structural Repair Manual", category_id=cat, tags="A320").json()["id"]
    b = upload("b.txt", b"x", title="A320 Repair Schemes", category_id=cat, tags="A320").json()["id"]
    c = upload("c.txt", b"x", title="Cafeteria menu", category_id=cat).json()["id"]
    auto = client.get(f"/api/documents/{a}/related").json()
    assert auto["manual"] is False and auto["items"][0]["id"] == b
    put = client.put(f"/api/admin/documents/{a}", headers=ADMIN, json={"related_ids": [c, a, 999]})
    assert put.status_code == 200
    manual = client.get(f"/api/documents/{a}/related").json()
    assert manual["manual"] is True and [d["id"] for d in manual["items"]] == [c]
    rel = client.get(f"/api/admin/documents/{a}/relations", headers=ADMIN).json()
    assert rel == {"related_ids": [c]}


def test_files_views_text_and_delete(client, upload):
    doc = upload("guide.pdf", make_pdf("page one"), title="Guide").json()
    pdf = client.get(f"/api/documents/{doc['id']}/file")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert "inline" in pdf.headers["content-disposition"]
    word = upload("w.docx", make_docx("some words")).json()
    assert "attachment" in client.get(f"/api/documents/{word['id']}/download").headers["content-disposition"]
    assert "attachment" in client.get(f"/api/documents/{word['id']}/file").headers["content-disposition"]
    assert client.get(f"/api/documents/{word['id']}/text").json()["items"][0]["text"] == "some words"

    client.post(f"/api/documents/{doc['id']}/view")
    client.post(f"/api/documents/{doc['id']}/view")
    home = client.get("/api/home").json()
    assert home["popular"][0]["id"] == doc["id"] and home["popular"][0]["views"] == 2
    assert home["total"] == 2

    assert client.delete(f"/api/admin/documents/{doc['id']}", headers=ADMIN).status_code == 204
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    assert client.get("/api/search", params={"q": "page one"}).json()["total"] == 0


def test_replace_file_and_failed_parse(client, upload):
    doc = upload("a.txt", b"first version", title="Doc").json()
    new = client.post(f"/api/admin/documents/{doc['id']}/file", headers=ADMIN,
                      files={"file": ("a.pdf", make_pdf("second version"))}).json()
    assert new["ext"] == "pdf" and new["page_count"] == 1
    assert client.get("/api/search", params={"q": "first"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "second"}).json()["total"] == 1
    bad = upload("broken.pdf", b"not a pdf").json()
    assert bad["index_status"] == "failed"
    assert client.get(f"/api/documents/{bad['id']}/download").content == b"not a pdf"


def test_settings_and_categories_admin(client):
    assert client.get("/api/settings").json()["app_name"] == "eHelp"
    assert client.put("/api/admin/settings", json={"app_name": "X"}).status_code == 403
    out = client.put("/api/admin/settings", headers=ADMIN, json={"app_name": "X", "show_popular": "0"}).json()
    assert out["app_name"] == "X" and out["show_popular"] == "0"
    assert client.put("/api/admin/settings", headers=ADMIN, json={"nope": "1"}).status_code == 422
    cat = client.post("/api/admin/categories", headers=ADMIN, json={"name": "Radar Systems"}).json()
    assert cat["slug"] == "radar-systems"
    assert client.post("/api/admin/categories", headers=ADMIN, json={"name": "Radar Systems"}).status_code == 409
    up = client.put(f"/api/admin/categories/{cat['id']}", headers=ADMIN, json={"description": "d"}).json()
    assert up["description"] == "d"
    assert client.delete(f"/api/admin/categories/{cat['id']}", headers=ADMIN).status_code == 204


def test_upload_limits_and_bad_input(client, upload):
    assert upload("big.txt", b"x" * (6 * 1024 * 1024)).status_code == 413
    assert upload("noext", b"x").status_code == 422
    assert upload("a.txt", b"x", category_id=9999).status_code == 422
    assert upload("a.txt", b"x", related_ids="oops").status_code == 422
    assert client.get("/api/search", params={"q": "!!!"}).json()["total"] == 0
    assert json.loads(json.dumps(client.get("/api/home").json()))["total"] == 0


def test_cbt_video_upload_and_range(client, upload):
    data = bytes(range(256)) * 40
    doc = upload("Cockpit Drill.mp4", data, title="Cockpit Drill CBT").json()
    assert doc["ext"] == "mp4" and doc["index_status"] == "indexed"
    full = client.get(f"/api/documents/{doc['id']}/file")
    assert full.headers["content-type"] == "video/mp4"
    part = client.get(f"/api/documents/{doc['id']}/file", headers={"range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == data[:100]
    assert client.get("/api/search", params={"q": "cockpit"}).json()["total"] == 1


def test_ai_mode_toggle_and_daily_limit(client, upload, monkeypatch):
    from ehelp import ai

    upload("fuel.txt", b"The fuel pump pressure limit is 45 psi during taxi.")
    body = {"question": "What is the fuel pump pressure limit?"}
    assert client.post("/api/ai/ask", json=body).status_code == 403
    client.put("/api/admin/settings", headers=ADMIN, json={"ai_enabled": "1", "ai_daily_limit": "1"})

    async def fake_status(*_a, **_k):
        return {"reachable": True, "model_present": True}

    async def fake_generate(*_a, **_k):
        yield "It is 45 psi [E1].", None
        yield "", "stop"

    monkeypatch.setattr(ai, "status", fake_status)
    monkeypatch.setattr(ai, "generate", fake_generate)
    out = client.post("/api/ai/ask", json=body)
    assert out.status_code == 200 and "event: done" in out.text and '"title": "fuel"' in out.text
    assert client.post("/api/ai/ask", json=body).status_code == 429
    assert client.get("/api/ai/status").json()["remaining"] == 0
    client.put("/api/admin/settings", headers=ADMIN, json={"ai_daily_limit": "0"})
    assert client.post("/api/ai/ask", json=body).status_code == 200
