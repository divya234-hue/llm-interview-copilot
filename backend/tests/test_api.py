from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pymupdf

from app.db.database import Base, get_db
from app.main import app
from app.api.routes import QuestionSet
from app.core.config import get_settings
from app.models.indexed_document import IndexedDocument
from app.schemas.interview import Evaluation
from app.services.llm import OllamaService
from app.services.rag import LocalKnowledgeBase

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def fake_generate(self, prompt, response_model=None, **kwargs):
    if response_model is QuestionSet:
        return QuestionSet(questions=[
            {"text": "Explain Python lists.", "topic": "Python", "criteria": ["accuracy"], "expected_concepts": ["ordered"]},
            {"text": "What is a dictionary?", "topic": "Python", "criteria": ["clarity"], "expected_concepts": ["key-value"]},
        ])
    return Evaluation(
        overall_score=8,
        category_scores={"technical_correctness": 8, "relevance": 8, "depth": 7, "clarity": 8, "examples": 7},
        strengths=["Clear explanation."],
        missing_concepts=["Mention complexity."],
        unsupported_statements=[],
        improved_answer="A stronger sample answer.",
        follow_up_question="What is the lookup complexity?",
        source_snippets=[],
    )


def test_health_and_complete_mock_interview(monkeypatch):
    reset_database()
    monkeypatch.setattr(OllamaService, "generate", fake_generate)
    monkeypatch.setattr(
        LocalKnowledgeBase,
        "retrieve",
        lambda self, query, workspace_id="local", limit=4: [],
    )

    assert client.get("/api/health").status_code == 200
    start = client.post("/api/interviews/start", json={
        "title": "Python practice",
        "interview_type": "python",
        "difficulty": "beginner",
        "experience_level": "beginner",
        "count": 2,
    })
    assert start.status_code == 200
    assert "expected_concepts" not in start.text
    session_id = start.json()["session_id"]

    first = client.post(f"/api/interviews/{session_id}/answer", json={"answer": "Lists are ordered sequences."})
    assert first.status_code == 200
    assert first.json()["next_question"] == "What is a dictionary?"

    active_report = client.get(f"/api/interviews/{session_id}/report")
    assert "expected_concepts" not in active_report.text
    assert len(active_report.json()["answers"]) == 1
    active_pdf = client.get(f"/api/interviews/{session_id}/export?format=pdf")
    assert active_pdf.status_code == 409

    second = client.post(f"/api/interviews/{session_id}/answer", json={"answer": "A dictionary stores key-value pairs."})
    assert second.status_code == 200
    assert second.json()["next_question"] is None

    finished = client.post(f"/api/interviews/{session_id}/finish")
    assert finished.status_code == 200
    assert finished.json()["average_score"] == 8
    pdf_response = client.get(f"/api/interviews/{session_id}/export?format=pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"
    pdf = pymupdf.open(stream=pdf_response.content, filetype="pdf")
    pdf_text = "\n".join(page.get_text() for page in pdf)
    assert "Interview Practice Report" in pdf_text
    assert "Lists are ordered sequences." in pdf_text
    assert "Clear explanation." in pdf_text
    assert "Mention complexity." in pdf_text
    assert "A stronger sample answer." in pdf_text
    assert "Question 2" in pdf_text
    pdf.close()
    assert client.get(f"/api/interviews/{session_id}/export?format=docx").status_code == 400
    assert client.get("/api/dashboard/stats").json()["completed_interviews"] == 1
    assert len(client.get("/api/interviews/history").json()) == 1


def test_mock_llm_runs_complete_api_interview(monkeypatch):
    reset_database()
    monkeypatch.setattr(get_settings(), "mock_llm", True)

    start = client.post("/api/interviews/start", json={
        "workspace_id": "mock-workspace",
        "interview_type": "python",
        "count": 2,
    })
    assert start.status_code == 200
    assert start.json()["question"].startswith("[Mock]")
    response = client.post(
        f"/api/interviews/{start.json()['session_id']}/answer",
        json={"answer": "A concise practice answer."},
    )
    assert response.status_code == 200
    assert response.json()["evaluation"]["overall_score"] == 7
    assert response.json()["next_question"].startswith("[Mock]")
    assert client.get("/api/llm/status").json()["mode"] == "mock"


def test_rag_indexing_is_workspace_scoped_and_skips_duplicate_content(monkeypatch):
    reset_database()
    indexed = []
    deleted = []

    monkeypatch.setattr(
        LocalKnowledgeBase,
        "add_document",
        lambda self, workspace_id, document_id, text, source: (
            indexed.append((workspace_id, document_id, text, source)) or 2
        ),
    )
    monkeypatch.setattr(LocalKnowledgeBase, "delete_document", lambda self, document_id: deleted.append(document_id))

    payload = {
        "workspace_id": "student-workspace",
        "source": "resume",
        "text": "Python and machine learning project evidence.",
    }
    first = client.post("/api/rag/index", json=payload)
    unchanged = client.post("/api/rag/index", json=payload)
    changed = client.post("/api/rag/index", json={**payload, "text": "Updated Python project evidence."})
    blank = client.post("/api/rag/index", json={**payload, "text": " \n "})
    assert first.status_code == unchanged.status_code == changed.status_code == 200
    assert blank.status_code == 422
    assert first.json()["unchanged"] is False
    assert unchanged.json()["unchanged"] is True
    assert changed.json()["unchanged"] is False
    assert len(indexed) == 2
    assert deleted == [first.json()["document_id"]]

    with TestSession() as db:
        row = db.query(IndexedDocument).one()
        assert row.workspace_id == "student-workspace"
        assert row.source == "resume"
        assert row.content_hash == LocalKnowledgeBase.content_hash("Updated Python project evidence.")


def test_pdf_export_reports_generation_errors(monkeypatch):
        reset_database()
        session_id = "pdf-error-session"
        with TestSession() as db:
            from app.models.interview import InterviewSession

            db.add(InterviewSession(
                id=session_id,
                title="Completed practice",
                workspace_id="workspace",
                mode="python",
                difficulty="beginner",
                status="completed",
                questions_json="[]",
                answers_json="[]",
            ))
            db.commit()
        monkeypatch.setattr(
            "app.api.routes.generate_pdf_report",
            lambda report: (_ for _ in ()).throw(RuntimeError("renderer failure")),
        )
        response = client.get(f"/api/interviews/{session_id}/export?format=pdf")
        assert response.status_code == 500
        assert response.json()["detail"] == "Could not generate the PDF report; retry or export JSON."
