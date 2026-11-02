import uuid

from sqlalchemy.orm import Session

from app.models.indexed_document import IndexedDocument
from app.services.analysis import analyze_resume
from app.services.documents import extract_text
from app.services.errors import ServiceError
from app.services.rag import LocalKnowledgeBase


MAX_ANALYSIS_TEXT_LENGTH = 30000


def process_resume_upload(
    filename: str,
    content: bytes,
    max_upload_size_mb: int,
) -> dict:
    if filename.lower().rsplit(".", 1)[-1] not in {"pdf", "docx"}:
        raise ServiceError(415, "Upload a PDF or DOCX resume.")
    max_upload_size_bytes = max_upload_size_mb * 1024 * 1024
    if len(content) > max_upload_size_bytes:
        raise ServiceError(413, f"File exceeds {max_upload_size_mb} MB.")
    try:
        text = extract_text(filename, content)
    except ValueError as exc:
        raise ServiceError(422, str(exc)) from exc
    if len(text) > MAX_ANALYSIS_TEXT_LENGTH:
        raise ServiceError(
            413,
            "Extracted resume text exceeds the 30,000-character analysis limit.",
        )
    return {"filename": filename, "text": text, "analysis": analyze_resume(text)}


def index_document(
    workspace_id: str,
    source: str,
    text: str,
    db: Session,
) -> dict:
    knowledge = LocalKnowledgeBase()
    content_hash = knowledge.content_hash(text)
    document = db.query(IndexedDocument).filter_by(
        workspace_id=workspace_id,
        source=source,
    ).one_or_none()
    if document and document.content_hash == content_hash:
        return {
            "indexed_chunks": document.chunk_count,
            "unchanged": True,
            "source": document.source,
            "document_id": document.id,
        }

    previous_id = document.id if document else None
    document_id = uuid.uuid4().hex
    try:
        count = knowledge.add_document(workspace_id, document_id, text, source)
    except RuntimeError as exc:
        raise ServiceError(503, str(exc)) from exc
    if document is None:
        document = IndexedDocument(
            id=document_id,
            workspace_id=workspace_id,
            source=source,
            content_hash=content_hash,
            chunk_count=count,
        )
        db.add(document)
    else:
        document.id = document_id
        document.content_hash = content_hash
        document.chunk_count = count
    try:
        db.commit()
    except Exception:
        db.rollback()
        knowledge.delete_document(document_id)
        raise
    if previous_id:
        knowledge.delete_document(previous_id)
    return {
        "indexed_chunks": count,
        "unchanged": False,
        "source": source,
        "document_id": document_id,
    }


def retrieve_documents(query: str, workspace_id: str, limit: int = 4) -> list[str]:
    try:
        return LocalKnowledgeBase().retrieve(query, workspace_id=workspace_id, limit=limit)
    except RuntimeError as exc:
        raise ServiceError(503, str(exc)) from exc
