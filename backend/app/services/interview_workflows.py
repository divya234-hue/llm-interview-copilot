import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.indexed_document import IndexedDocument
from app.models.interview import InterviewSession
from app.schemas.interview import (
    AnswerRequest,
    Evaluation,
    InterviewGenerateRequest,
    InterviewStartRequest,
    QuestionSet,
)
from app.services.document_processing import retrieve_documents
from app.services.errors import ServiceError
from app.services.llm import LLMUnavailableError, OllamaService
from app.services.reports import generate_pdf_report

logger = logging.getLogger(__name__)


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


def _generate_questions(
    request: InterviewGenerateRequest,
    db: Session,
) -> tuple[list[dict], list[str]]:
    evidence: list[str] = []
    has_documents = db.query(IndexedDocument.id).filter_by(
        workspace_id=request.workspace_id
    ).first() is not None
    if has_documents:
        try:
            evidence = retrieve_documents(
                request.resume_text or request.job_description or request.interview_type,
                workspace_id=request.workspace_id,
                limit=4,
            )
        except ServiceError as exc:
            raise ServiceError(
                503,
                f"Could not retrieve your indexed documents: {exc.detail}",
            ) from exc
    try:
        response = OllamaService().generate(
            _question_prompt(request, evidence),
            QuestionSet,
            allow_raw_response_logging=not any(
                (request.resume_text, request.job_description, evidence)
            ),
        )
    except LLMUnavailableError as exc:
        raise ServiceError(503, str(exc)) from exc
    return [question.model_dump() for question in response.questions], evidence


def generate_interview(request: InterviewGenerateRequest, db: Session) -> dict:
    questions, evidence = _generate_questions(request, db)
    return {
        "questions": [
            {"text": question["text"], "topic": question["topic"]}
            for question in questions
        ],
        "source_snippets": evidence,
    }


def start_interview(request: InterviewStartRequest, db: Session) -> dict:
    questions, evidence = _generate_questions(request, db)
    if not questions:
        raise ServiceError(503, "The model did not generate any questions.")
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
        raise ServiceError(404, "Interview session not found.")
    return session


def submit_answer(session_id: str, request: AnswerRequest, db: Session) -> dict:
    session = _find_session(db, session_id)
    if session.status != "in_progress":
        raise ServiceError(409, "This interview is no longer in progress.")
    questions = json.loads(session.questions_json)
    if session.current_index >= len(questions):
        raise ServiceError(409, "There are no unanswered questions.")
    question = questions[session.current_index]
    has_documents = db.query(IndexedDocument.id).filter_by(
        workspace_id=session.workspace_id
    ).first() is not None
    try:
        sources = retrieve_documents(
            question["text"],
            workspace_id=session.workspace_id,
            limit=3,
        ) if has_documents else []
    except ServiceError as exc:
        raise ServiceError(
            503,
            f"Could not retrieve your indexed documents: {exc.detail}",
        ) from exc
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
        raise ServiceError(503, str(exc)) from exc
    if sources:
        evaluation.source_snippets = sources
    answers = json.loads(session.answers_json)
    answers.append({
        "question": question["text"],
        "answer": request.answer,
        "evaluation": evaluation.model_dump(),
    })
    session.answers_json = json.dumps(answers)
    session.current_index += 1
    db.commit()
    return {
        "evaluation": evaluation.model_dump(),
        "next_question": questions[session.current_index]["text"]
        if session.current_index < len(questions)
        else None,
        "question_number": session.current_index + 1,
        "total_questions": len(questions),
    }


def next_question(session_id: str, db: Session) -> dict:
    session = _find_session(db, session_id)
    questions = json.loads(session.questions_json)
    if session.current_index >= len(questions):
        return {"question": None, "complete": True}
    return {
        "question": questions[session.current_index]["text"],
        "question_number": session.current_index + 1,
    }


def _session_report(session: InterviewSession) -> dict:
    questions = json.loads(session.questions_json)
    return {
        "id": session.id,
        "title": session.title,
        "mode": session.mode,
        "difficulty": session.difficulty,
        "status": session.status,
        "average_score": session.average_score,
        "questions": [
            {"text": item["text"], "topic": item.get("topic", "General")}
            for item in questions
        ],
        "answers": json.loads(session.answers_json),
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "score_notice": "Practice feedback only; not an authoritative measure of interview performance.",
    }


def finish_interview(session_id: str, db: Session) -> dict:
    session = _find_session(db, session_id)
    answers = json.loads(session.answers_json)
    if session.status == "in_progress":
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        scores = [item["evaluation"]["overall_score"] for item in answers]
        session.average_score = round(sum(scores) / len(scores), 2) if scores else 0
        db.commit()
    return _session_report(session)


def interview_history(db: Session, workspace_id: str = "local") -> list[dict]:
    sessions = db.query(InterviewSession).filter_by(
        workspace_id=workspace_id
    ).order_by(desc(InterviewSession.created_at)).limit(100).all()
    return [
        {
            "id": item.id,
            "title": item.title,
            "mode": item.mode,
            "status": item.status,
            "average_score": item.average_score,
            "created_at": item.created_at.isoformat(),
        }
        for item in sessions
    ]


def interview_report(session_id: str, db: Session) -> dict:
    return _session_report(_find_session(db, session_id))


def export_interview(
    session_id: str,
    db: Session,
    export_format: str = "json",
) -> tuple[str | bytes, str, str]:
    report = interview_report(session_id, db)
    if export_format == "json":
        return (
            json.dumps(report, indent=2),
            "application/json",
            f'interview-{session_id}.json',
        )
    if export_format == "pdf":
        if report["status"] != "completed":
            raise ServiceError(409, "PDF reports are available after completing the interview.")
        try:
            content = generate_pdf_report(report)
        except Exception as exc:
            logger.exception("Could not generate PDF report for session %s", session_id)
            raise ServiceError(
                500,
                "Could not generate the PDF report; retry or export JSON.",
            ) from exc
        return content, "application/pdf", f'interview-{session_id}.pdf'
    raise ServiceError(400, "Export format must be 'json' or 'pdf'.")


def delete_interview(session_id: str, db: Session) -> dict:
    session = _find_session(db, session_id)
    db.delete(session)
    db.commit()
    return {"deleted": True}


def dashboard_stats(db: Session, workspace_id: str = "local") -> dict:
    sessions = db.query(InterviewSession).filter_by(
        workspace_id=workspace_id,
        status="completed",
    ).all()
    averages = [item.average_score for item in sessions if item.average_score is not None]
    scores_by_topic: dict[str, list[float]] = {}
    for session in sessions:
        questions = json.loads(session.questions_json)
        for answer in json.loads(session.answers_json):
            matching_question = next(
                (item for item in questions if item["text"] == answer["question"]),
                {},
            )
            topic = matching_question.get("topic", session.mode)
            scores_by_topic.setdefault(topic, []).append(
                answer["evaluation"]["overall_score"]
            )
    topic_scores = [
        {"topic": key, "score": round(sum(values) / len(values), 1)}
        for key, values in scores_by_topic.items()
    ]
    topic_scores.sort(key=lambda item: item["score"])
    return {
        "completed_interviews": len(sessions),
        "average_score": round(sum(averages) / len(averages), 1) if averages else 0,
        "strongest_topics": topic_scores[-3:][::-1],
        "improve_topics": topic_scores[:3],
        "progress": topic_scores,
        "recommended_next": f"Practice {topic_scores[0]['topic']}"
        if topic_scores
        else "Start your first practice interview",
        "recent": interview_history(db, workspace_id)[:5],
    }
