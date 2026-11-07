import io
import pytest
from fastapi.testclient import TestClient
from app.extract import ExtractError, extract_text


def test_txt_and_validation():
    assert extract_text("a.txt", b"Hello world") == "Hello world"
    for name, data in [("a.exe", b"x"), ("a.pdf", b"not a pdf"), ("a.docx", b"nope"), ("a.txt", b"  "), ("a.txt", b"x" * (10 * 1024 * 1024 + 1))]:
        with pytest.raises(ExtractError):
            extract_text(name, data)


def test_pdf_extraction():
    import fitz
    d = fitz.open(); d.new_page().insert_text((72, 72), "Warranty is 3 years."); data = d.tobytes()
    assert "Warranty is 3 years" in extract_text("p.pdf", data)


def test_docx_extraction():
    import docx
    d = docx.Document(); d.add_paragraph("Battery lasts 12 hours."); b = io.BytesIO(); d.save(b)
    assert "12 hours" in extract_text("p.docx", b.getvalue())


def test_api_rejects_unauthenticated_and_bad_tokens(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-secret")
    from app.main import app
    c = TestClient(app)
    for path in ("/api/me", "/api/submissions", "/api/documents", "/api/audit", "/api/brand-health"):
        assert c.get(path).status_code == 401
        assert c.get(path, headers={"Authorization": "Bearer forged"}).status_code == 401
    assert c.get("/api/health").json() == {"status": "ok"}
