import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.indexed_document import IndexedDocument
from app.models.interview import InterviewSession
from app.schemas.interview import AnswerRequest, Evaluation, InterviewStartRequest
from app.services import document_processing, interview_workflows
from app.services.errors import ServiceError


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = test_session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_process_resume_upload_extracts_and_analyzes(monkeypatch):
    monkeypatch.setattr(
        document_processing,
        "extract_text",
        lambda filename, content: "Built Python applications.",
    )
    result = document_processing.process_resume_upload("resume.pdf", b"pdf", 1024)
    assert result["filename"] == "resume.pdf"
    assert result["text"] == "Built Python applications."
    assert result["analysis"]["skills"] == ["python"]


@pytest.mark.parametrize(
    ("filename", "content", "limit", "status_code", "message"),
    [
        ("resume.txt", b"data", 1, 415, "Upload a PDF or DOCX resume."),
        ("resume.pdf", b"x" * (1024 * 1024 + 1), 1, 413, "File exceeds 1 MB."),
    ],
    ids=["unsupported-extension", "file-size-limit"],
)
def test_process_resume_upload_rejects_invalid_files(
    filename,
    content,
    limit,
    status_code,
    message,
):
    with pytest.raises(ServiceError) as error:
        document_processing.process_resume_upload(filename, content, limit)
    assert error.value.status_code == status_code
    assert error.value.detail == message


def test_index_document_reuses_unchanged_content(db_session, monkeypatch):
    indexed = []
    deleted = []
    monkeypatch.setattr(
        document_processing.LocalKnowledgeBase,
        "add_document",
        lambda self, workspace_id, document_id, text, source: indexed.append(document_id) or 3,
    )
    monkeypatch.setattr(
        document_processing.LocalKnowledgeBase,
        "delete_document",
        lambda self, document_id: deleted.append(document_id),
    )

    first = document_processing.index_document(
        "unit-workspace", "resume", "Python evidence.", db_session
    )
    repeated = document_processing.index_document(
        "unit-workspace", "resume", "Python evidence.", db_session
    )

    assert first["indexed_chunks"] == 3
    assert first["unchanged"] is False
    assert repeated == {**first, "unchanged": True}
    assert len(indexed) == 1
    assert deleted == []
    assert db_session.query(IndexedDocument).one().chunk_count == 3


def test_interview_workflows_preserve_session_transitions(db_session, monkeypatch):
    def generate(self, prompt, response_model=None, **kwargs):
        if response_model is interview_workflows.QuestionSet:
            return response_model(questions=[
                {
                    "text": "Explain Python lists.",
                    "topic": "Python",
                    "criteria": ["accuracy"],
                    "expected_concepts": ["ordered"],
                },
            ])
        return Evaluation(
            overall_score=8,
            category_scores={
                "technical_correctness": 8,
                "relevance": 8,
                "depth": 7,
                "clarity": 8,
                "examples": 7,
            },
            strengths=["Clear explanation."],
            missing_concepts=[],
            unsupported_statements=[],
            improved_answer="",
            follow_up_question="",
        )

    monkeypatch.setattr(interview_workflows.OllamaService, "generate", generate)
    request = InterviewStartRequest(
        workspace_id="unit-workspace",
        interview_type="python",
        count=1,
    )
    started = interview_workflows.start_interview(request, db_session)
    session_id = started["session_id"]

    assert started["question"] == "Explain Python lists."
    assert interview_workflows.next_question(session_id, db_session) == {
        "question": "Explain Python lists.",
        "question_number": 1,
    }
    answer = interview_workflows.submit_answer(
        session_id,
        AnswerRequest(answer="Lists preserve order."),
        db_session,
    )
    assert answer["evaluation"]["overall_score"] == 8
    assert answer["next_question"] is None

    report = interview_workflows.finish_interview(session_id, db_session)
    assert report["status"] == "completed"
    assert report["average_score"] == 8
    assert report["answers"][0]["answer"] == "Lists preserve order."
    assert interview_workflows.dashboard_stats(db_session, "unit-workspace")[
        "completed_interviews"
    ] == 1
    assert db_session.query(InterviewSession).one().status == "completed"


def test_interview_service_errors_keep_http_status_and_detail(db_session):
    with pytest.raises(ServiceError) as error:
        interview_workflows.interview_report("missing-session", db_session)
    assert error.value.status_code == 404
    assert error.value.detail == "Interview session not found."
