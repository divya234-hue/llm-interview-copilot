import io
import re
import zipfile

import pymupdf
from docx import Document
from docx.opc.exceptions import PackageNotFoundError


def extract_text(filename: str, content: bytes) -> str:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf":
        try:
            with pymupdf.open(stream=content, filetype="pdf") as document:
                text = "\n".join(page.get_text() for page in document)
        except pymupdf.FileDataError as exc:
            raise ValueError("The uploaded PDF is invalid or unreadable.") from exc
    elif suffix == "docx":
        try:
            document = Document(io.BytesIO(content))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        except (PackageNotFoundError, zipfile.BadZipFile, KeyError) as exc:
            raise ValueError("The uploaded DOCX is invalid or unreadable.") from exc
    else:
        raise ValueError("Only PDF and DOCX resumes are supported.")
    cleaned = re.sub(r"[ \t]+", " ", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if not cleaned:
        raise ValueError("No readable text was found in the uploaded document.")
    return cleaned


def split_chunks(text: str, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Chunk size must be positive and overlap must be smaller than chunk size.")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks
