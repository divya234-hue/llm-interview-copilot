import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db
from app.models.indexed_document import IndexedDocument
from app.models.interview import InterviewSession
from app.schemas.interview import (
    AnswerRequest,
    Evaluation,
    InterviewGenerateRequest,
    InterviewStartRequest,
    JobAnalysisRequest,
    Question,
)
from app.services.analysis import analyze_job, analyze_resume
from app.services.documents import extract_text
from app.services.llm import LLMUnavailableError, OllamaService
from app.services.rag import LocalKnowledgeBase
from app.services.reports import generate_pdf_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]


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


class QuestionSet(BaseModel):
    questions: list[Question]


def _llm_error(exc: LLMUnavailableError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _question_prompt(request: InterviewGenerateRequest, evidence: list[str]) -> str:
    return f"""Create {request.count} personalized interview questions as JSON matching
{{"questions":[{{"text":"...","topic":"...","criteria":["..."],"expected_concepts":["..."]}}]}}.
Interview type: {request.interview_type}. Difficulty: {request.difficulty}.
Experience level: {request.experience_level}.
Resume (use only evidence present; never invent experience): {request.resume_text or "Not provided"}
Job description: {request.job_description or "Not provided"}
Retrieved source snippets: {json.dumps(evidence)}
Keep the answer key in expected_concepts; the UI must not reveal it before submission.
Return a single valid JSON object only. No markdown, no prose, no code fences, no trailing commas."""


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
    if filename.lower().rsplit(".", 1)[-1] not in {"pdf", "docx"}:
        raise HTTPException(status_code=415, detail="Upload a PDF or DOCX resume.")
    content = await file.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_size_mb} MB.")
    try:
        text = extract_text(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if len(text) > 30000:
        raise HTTPException(status_code=413, detail="Extracted resume text exceeds the 30,000-character analysis limit.")
    return {"filename": filename, "text": text, "analysis": analyze_resume(text)}


@router.post("/resume/analyze")
def resume_analyze(request: TextRequest):
    return analyze_resume(request.text)


@router.post("/job/analyze")
def job_analyze(request: JobAnalysisRequest):
    return analyze_job(request.description, request.resume_text)


@router.post("/rag/index")
def index_document(request: RagIndexRequest, db: DbSession):
    knowledge = LocalKnowledgeBase()
    content_hash = knowledge.content_hash(request.text)
    document = db.query(IndexedDocument).filter_by(
        workspace_id=request.workspace_id,
        source=request.source,
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
        count = knowledge.add_document(request.workspace_id, document_id, request.text, request.source)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if document is None:
        document = IndexedDocument(
            id=document_id,
            workspace_id=request.workspace_id,
            source=request.source,
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
    return {"indexed_chunks": count, "unchanged": False, "source": request.source, "document_id": document_id}


@router.post("/rag/search")
def search_documents(request: RagSearchRequest):
    try:
        return {"sources": LocalKnowledgeBase().retrieve(request.text, workspace_id=request.workspace_id)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _generate_questions(request: InterviewGenerateRequest, db: Session) -> tuple[list[dict], list[str]]:
    evidence: list[str] = []
    has_documents = db.query(IndexedDocument.id).filter_by(workspace_id=request.workspace_id).first() is not None
    if has_documents:
        try:
            evidence = LocalKnowledgeBase().retrieve(
                request.resume_text or request.job_description or request.interview_type,
                workspace_id=request.workspace_id,
                limit=4,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=f"Could not retrieve your indexed documents: {exc}") from exc
    try:
        response = OllamaService().generate(
            _question_prompt(request, evidence),
            QuestionSet,
            allow_raw_response_logging=not any(
                (request.resume_text, request.job_description, evidence)
            ),
        )
    except LLMUnavailableError as exc:
        raise _llm_error(exc) from exc
    return [question.model_dump() for question in response.questions], evidence


@router.post("/interviews/generate")
def generate_interview(request: InterviewGenerateRequest, db: DbSession):
    questions, evidence = _generate_questions(request, db)
    return {
        "questions": [
            {"text": question["text"], "topic": question["topic"]}
            for question in questions
        ],
        "source_snippets": evidence,
    }


@router.post("/interviews/start")
def start_interview(request: InterviewStartRequest, db: DbSession):
    questions, evidence = _generate_questions(request, db)
    if not questions:
        raise HTTPException(status_code=503, detail="The model did not generate any questions.")
    session = InterviewSession(
        id=str(uuid.uuid4()),
        title=request.title,
        workspace_id=request.workspace_id,
        mode=request.interview_type,
        difficulty=request.difficulty,
        questions_json=json.dumps(questions),
    )
    db.add(session)
    db.commit()
    return {
        "session_id": session.id,
        "question": questions[0]["text"],
        "question_number": 1,
        "total_questions": len(questions),
        "source_snippets": evidence,
    }


def _find_session(db: Session, session_id: str) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Interview session not found.")
    return session


@router.post("/interviews/{session_id}/answer")
def submit_answer(session_id: str, request: AnswerRequest, db: DbSession):
    session = _find_session(db, session_id)
    if session.status != "in_progress":
        raise HTTPException(status_code=409, detail="This interview is no longer in progress.")
    questions = json.loads(session.questions_json)
    if session.current_index >= len(questions):
        raise HTTPException(status_code=409, detail="There are no unanswered questions.")
    question = questions[session.current_index]
    try:
        has_documents = db.query(IndexedDocument.id).filter_by(workspace_id=session.workspace_id).first() is not None
        sources = LocalKnowledgeBase().retrieve(
            question["text"], workspace_id=session.workspace_id, limit=3
        ) if has_documents else []
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Could not retrieve your indexed documents: {exc}") from exc
    prompt = f"""Evaluate this interview answer as practice feedback, not an authoritative hiring measure.
Question: {question["text"]}
Evaluation criteria: {json.dumps(question.get("criteria", []))}
Expected concepts: {json.dumps(question.get("expected_concepts", []))}
Candidate answer: {request.answer}
Retrieved source snippets (if any): {json.dumps(sources)}
Do not treat absent information as fact. Return JSON matching:
{{"overall_score":0,"category_scores":{{"technical_correctness":0,"relevance":0,"depth":0,"clarity":0,"examples":0}},"strengths":[],"missing_concepts":[],"unsupported_statements":[],"improved_answer":"","follow_up_question":"","source_snippets":[]}}
Scores must be from 0 to 10.
Return a single valid JSON object only. No markdown, no prose, no code fences, no trailing commas."""
    try:
        evaluation = OllamaService().generate(prompt, Evaluation)
    except LLMUnavailableError as exc:
        raise _llm_error(exc) from exc
    if sources:
        evaluation.source_snippets = sources
    answers = json.loads(session.answers_json)
    answers.append({"question": question["text"], "answer": request.answer, "evaluation": evaluation.model_dump()})
    session.answers_json = json.dumps(answers)
    session.current_index += 1
    db.commit()
    return {
        "evaluation": evaluation.model_dump(),
        "next_question": questions[session.current_index]["text"] if session.current_index < len(questions) else None,
        "question_number": session.current_index + 1,
        "total_questions": len(questions),
    }


@router.post("/interviews/{session_id}/next-question")
def next_question(session_id: str, db: DbSession):
    session = _find_session(db, session_id)
    questions = json.loads(session.questions_json)
    if session.current_index >= len(questions):
        return {"question": None, "complete": True}
    return {"question": questions[session.current_index]["text"], "question_number": session.current_index + 1}


@router.post("/interviews/{session_id}/finish")
def finish_interview(session_id: str, db: DbSession):
    session = _find_session(db, session_id)
    answers = json.loads(session.answers_json)
    if session.status == "in_progress":
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        scores = [item["evaluation"]["overall_score"] for item in answers]
        session.average_score = round(sum(scores) / len(scores), 2) if scores else 0
        db.commit()
    return _session_report(session)


def _session_report(session: InterviewSession) -> dict:
    questions = json.loads(session.questions_json)
    return {
        "id": session.id,
        "title": session.title,
        "mode": session.mode,
        "difficulty": session.difficulty,
        "status": session.status,
        "average_score": session.average_score,
        "questions": [{"text": item["text"], "topic": item.get("topic", "General")} for item in questions],
        "answers": json.loads(session.answers_json),
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "score_notice": "Practice feedback only; not an authoritative measure of interview performance.",
    }


@router.get("/interviews/history")
def interview_history(db: DbSession, workspace_id: str = "local"):
    sessions = db.query(InterviewSession).filter_by(workspace_id=workspace_id).order_by(desc(InterviewSession.created_at)).limit(100).all()
    return [{"id": item.id, "title": item.title, "mode": item.mode, "status": item.status, "average_score": item.average_score, "created_at": item.created_at.isoformat()} for item in sessions]


@router.get("/interviews/{session_id}/report")
def interview_report(session_id: str, db: DbSession):
    return _session_report(_find_session(db, session_id))


@router.get("/interviews/{session_id}/export")
def export_interview(session_id: str, db: DbSession, format: str = "json"):
    report = _session_report(_find_session(db, session_id))
    if format == "json":
        return Response(
            content=json.dumps(report, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="interview-{session_id}.json"'},
        )
    if format == "pdf":
        if report["status"] != "completed":
            raise HTTPException(status_code=409, detail="PDF reports are available after completing the interview.")
        try:
            content = generate_pdf_report(report)
        except Exception as exc:
            logger.exception("Could not generate PDF report for session %s", session_id)
            raise HTTPException(status_code=500, detail="Could not generate the PDF report; retry or export JSON.") from exc
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="interview-{session_id}.pdf"'},
        )
    raise HTTPException(status_code=400, detail="Export format must be 'json' or 'pdf'.")


@router.delete("/interviews/{session_id}")
def delete_interview(session_id: str, db: DbSession):
    session = _find_session(db, session_id)
    db.delete(session)
    db.commit()
    return {"deleted": True}


@router.get("/dashboard/stats")
def dashboard_stats(db: DbSession, workspace_id: str = "local"):
    sessions = db.query(InterviewSession).filter_by(workspace_id=workspace_id, status="completed").all()
    averages = [item.average_score for item in sessions if item.average_score is not None]
    scores_by_topic: dict[str, list[float]] = {}
    for session in sessions:
        questions = json.loads(session.questions_json)
        for answer in json.loads(session.answers_json):
            matching_question = next((item for item in questions if item["text"] == answer["question"]), {})
            topic = matching_question.get("topic", session.mode)
            scores_by_topic.setdefault(topic, []).append(answer["evaluation"]["overall_score"])
    topic_scores = [{"topic": key, "score": round(sum(values) / len(values), 1)} for key, values in scores_by_topic.items()]
    topic_scores.sort(key=lambda item: item["score"])
    return {
        "completed_interviews": len(sessions),
        "average_score": round(sum(averages) / len(averages), 1) if averages else 0,
        "strongest_topics": topic_scores[-3:][::-1],
        "improve_topics": topic_scores[:3],
        "progress": topic_scores,
        "recommended_next": f"Practice {topic_scores[0]['topic']}" if topic_scores else "Start your first practice interview",
        "recent": interview_history(db, workspace_id)[:5],
    }
