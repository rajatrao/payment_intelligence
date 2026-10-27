"""Text extraction for uploaded evidence.

OCR is deliberately not used. PDFs contribute their text layer; JPEGs contribute no text and are instead
embedded directly as images by EmbeddingGemma 2 (see matching.py).
"""

import io
import logging
import re

from pypdf import PdfReader

log = logging.getLogger("extraction")

PDF_TYPES = {"application/pdf"}
IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/pjpeg"}


def detect_kind(filename: str, content_type: str | None, data: bytes) -> str:
    if data[:5] == b"%PDF-" or (content_type or "") in PDF_TYPES or filename.lower().endswith(".pdf"):
        return "pdf"
    if data[:3] == b"\xff\xd8\xff" or (content_type or "") in IMAGE_TYPES or filename.lower().endswith((".jpg", ".jpeg")):
        return "jpeg"
    raise ValueError("Only PDF or JPEG evidence files are supported.")


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_text(kind: str, data: bytes) -> tuple[str, str]:
    """Return (text, method). Never raises on unreadable content; returns empty text instead."""
    if kind == "pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            return _clean("\n".join(page.extract_text() or "" for page in reader.pages)), "pypdf"
        except Exception as exc:  # noqa: BLE001
            log.warning("PDF text extraction failed: %s", exc)
            return "", "pypdf (failed)"

    return "", "image (embedded directly, no OCR)"


def chunk_text(text: str, target_chars: int = 320) -> list[str]:
    """Split into paragraph-ish chunks so each can be scored against transaction facets."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    chunks: list[str] = []
    buf = ""
    for line in lines:
        if buf and len(buf) + len(line) > target_chars:
            chunks.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        chunks.append(buf)
    return chunks[:40]
