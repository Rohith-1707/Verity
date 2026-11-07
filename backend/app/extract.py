"""Document validation and text extraction (PDF via PyMuPDF, DOCX via python-docx, TXT)."""
import io

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 200_000


class ExtractError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in {"pdf", "docx", "txt"}:
        raise ExtractError("Only PDF, DOCX and TXT files are accepted.")
    if len(data) > MAX_BYTES:
        raise ExtractError("File is larger than 10 MB.")
    try:
        if ext == "pdf":
            if not data.startswith(b"%PDF"):
                raise ExtractError("File content is not a valid PDF.")
            import fitz
            with fitz.open(stream=data, filetype="pdf") as doc:
                text = "\n".join(page.get_text() for page in doc)
        elif ext == "docx":
            if not data.startswith(b"PK"):
                raise ExtractError("File content is not a valid DOCX.")
            import docx
            d = docx.Document(io.BytesIO(data))
            text = "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])
        else:
            text = data.decode("utf-8", errors="replace")
    except ExtractError:
        raise
    except Exception as e:
        raise ExtractError(f"Could not read the file: {e}") from e
    text = text.strip()
    if not text:
        raise ExtractError("No extractable text found (scanned files need OCR, which is not enabled).")
    if len(text) > MAX_CHARS:
        raise ExtractError("Document text exceeds 200,000 characters.")
    return text
