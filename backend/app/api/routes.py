import logging
from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db
from app.schemas.interview import (
    AnswerRequest,
    InterviewGenerateRequest,
    InterviewStartRequest,
    JobAnalysisRequest,
)
from app.services.analysis import analyze_job, analyze_resume
from app.services.document_processing import index_document as index_document_service
from app.services.document_processing import process_resume_upload
from app.services.document_processing import retrieve_documents
from app.services.errors import ServiceError
from app.services.interview_workflows import (
    dashboard_stats as dashboard_stats_service,
    delete_interview as delete_interview_service,
    export_interview as export_interview_service,
    finish_interview as finish_interview_service,
    generate_interview as generate_interview_service,
    interview_history as interview_history_service,
    interview_report as interview_report_service,
    next_question as next_question_service,
    start_interview as start_interview_service,
    submit_answer as submit_answer_service,
)
from app.services.llm import OllamaService

router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
logger = logging.getLogger(__name__)
Result = TypeVar("Result")


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30000)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must contain non-whitespace characters.")
        return value


class RagIndexRequest(TextRequest):
    workspace_id: str = Field(default="local", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    source: str = Field(pattern=r"^(resume|job_description)$")


class RagSearchRequest(TextRequest):
    workspace_id: str = Field(default="local", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


def _service_result(operation: Callable[..., Result], *args, **kwargs) -> Result:
    try:
        return operation(*args, **kwargs)
    except ServiceError as exc:
        logger.warning(
            "Backend service operation %s failed with HTTP %s.",
            operation.__name__,
            exc.status_code,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/health")
def health():
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "llm_model": settings.ollama_model}


@router.get("/llm/status")
def llm_status():
    return OllamaService().status()


@router.post("/resume/upload")
async def upload_resume(file: Annotated[UploadFile, File()]):
    settings = get_settings()
    filename = file.filename or ""
    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    return _service_result(
        process_resume_upload,
        filename,
        content,
        settings.max_upload_size_mb,
    )


@router.post("/resume/analyze")
def resume_analyze(request: TextRequest):
    return analyze_resume(request.text)


@router.post("/job/analyze")
def job_analyze(request: JobAnalysisRequest):
    return analyze_job(request.description, request.resume_text)


@router.post("/rag/index")
def index_document(request: RagIndexRequest, db: DbSession):
    return _service_result(
        index_document_service,
        request.workspace_id,
        request.source,
        request.text,
        db,
    )


@router.post("/rag/search")
def search_documents(request: RagSearchRequest):
    return {"sources": _service_result(retrieve_documents, request.text, request.workspace_id)}


@router.post("/interviews/generate")
def generate_interview(request: InterviewGenerateRequest, db: DbSession):
    return _service_result(generate_interview_service, request, db)


@router.post("/interviews/start")
def start_interview(request: InterviewStartRequest, db: DbSession):
    return _service_result(start_interview_service, request, db)


@router.post("/interviews/{session_id}/answer")
def submit_answer(session_id: str, request: AnswerRequest, db: DbSession):
    return _service_result(submit_answer_service, session_id, request, db)


@router.post("/interviews/{session_id}/next-question")
def next_question(session_id: str, db: DbSession):
    return _service_result(next_question_service, session_id, db)


@router.post("/interviews/{session_id}/finish")
def finish_interview(session_id: str, db: DbSession):
    return _service_result(finish_interview_service, session_id, db)


@router.get("/interviews/history")
def interview_history(db: DbSession, workspace_id: str = "local"):
    return interview_history_service(db, workspace_id)


@router.get("/interviews/{session_id}/report")
def interview_report(session_id: str, db: DbSession):
    return _service_result(interview_report_service, session_id, db)


@router.get("/interviews/{session_id}/export")
def export_interview(session_id: str, db: DbSession, format: str = "json"):
    content, media_type, filename = _service_result(
        export_interview_service,
        session_id,
        db,
        format,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/interviews/{session_id}")
def delete_interview(session_id: str, db: DbSession):
    return _service_result(delete_interview_service, session_id, db)


@router.get("/dashboard/stats")
def dashboard_stats(db: DbSession, workspace_id: str = "local"):
    return dashboard_stats_service(db, workspace_id)
