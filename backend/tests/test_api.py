from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pymupdf

from app.db.database import Base, get_db
from app.main import app
from app.core.config import get_settings
from app.models.indexed_document import IndexedDocument
from app.schemas.interview import Evaluation, QuestionSet
from app.services.llm import OllamaService
from app.services.llm import LLMUnavailableError
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
            "app.services.interview_workflows.generate_pdf_report",
            lambda report: (_ for _ in ()).throw(RuntimeError("renderer failure")),
        )
        response = client.get(f"/api/interviews/{session_id}/export?format=pdf")
        assert response.status_code == 500
        assert response.json()["detail"] == "Could not generate the PDF report; retry or export JSON."


def test_generate_next_question_and_delete_routes(monkeypatch):
    reset_database()
    monkeypatch.setattr(OllamaService, "generate", fake_generate)
    monkeypatch.setattr(
        LocalKnowledgeBase,
        "retrieve",
        lambda self, query, workspace_id="local", limit=4: [],
    )

    generated = client.post("/api/interviews/generate", json={
        "workspace_id": "route-workspace",
        "interview_type": "python",
        "count": 2,
    })
    assert generated.status_code == 200
    assert generated.json() == {
        "questions": [
            {"text": "Explain Python lists.", "topic": "Python"},
            {"text": "What is a dictionary?", "topic": "Python"},
        ],
        "source_snippets": [],
    }

    started = client.post("/api/interviews/start", json={
        "workspace_id": "route-workspace",
        "interview_type": "python",
        "count": 2,
    })
    session_id = started.json()["session_id"]
    next_item = client.post(f"/api/interviews/{session_id}/next-question")
    assert next_item.status_code == 200
    assert next_item.json() == {"question": "Explain Python lists.", "question_number": 1}

    deleted = client.delete(f"/api/interviews/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    missing = client.get(f"/api/interviews/{session_id}/report")
    assert missing.status_code == 404


def test_resume_upload_and_rag_search_routes(monkeypatch):
    reset_database()
    monkeypatch.setattr(
        "app.services.document_processing.extract_text",
        lambda filename, content: "Built Python applications.",
    )
    uploaded = client.post(
        "/api/resume/upload",
        files={"file": ("resume.pdf", b"fixture", "application/pdf")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["filename"] == "resume.pdf"
    assert uploaded.json()["text"] == "Built Python applications."
    assert uploaded.json()["analysis"]["skills"] == ["python"]

    monkeypatch.setattr(
        LocalKnowledgeBase,
        "retrieve",
        lambda self, query, workspace_id="local", limit=4: [f"{workspace_id}: {query}"],
    )
    searched = client.post("/api/rag/search", json={
        "workspace_id": "search-workspace",
        "text": "Python evidence",
    })
    assert searched.status_code == 200
    assert searched.json() == {"sources": ["search-workspace: Python evidence"]}


def test_api_openapi_contracts_remain_available():
    paths = client.get("/openapi.json").json()["paths"]
    expected_methods = {
        "/api/health": {"get"},
        "/api/llm/status": {"get"},
        "/api/resume/upload": {"post"},
        "/api/resume/analyze": {"post"},
        "/api/job/analyze": {"post"},
        "/api/rag/index": {"post"},
        "/api/rag/search": {"post"},
        "/api/interviews/generate": {"post"},
        "/api/interviews/start": {"post"},
        "/api/interviews/{session_id}/answer": {"post"},
        "/api/interviews/{session_id}/next-question": {"post"},
        "/api/interviews/{session_id}/finish": {"post"},
        "/api/interviews/history": {"get"},
        "/api/interviews/{session_id}/report": {"get"},
        "/api/interviews/{session_id}/export": {"get"},
        "/api/interviews/{session_id}": {"delete"},
        "/api/dashboard/stats": {"get"},
    }

    for path, methods in expected_methods.items():
        assert methods <= set(paths[path])

    assert "multipart/form-data" in paths["/api/resume/upload"]["post"]["requestBody"]["content"]
    assert "application/json" in paths["/api/job/analyze"]["post"]["requestBody"]["content"]
    assert "application/json" in paths["/api/interviews/start"]["post"]["requestBody"]["content"]
    assert any(
        parameter["name"] == "format"
        for parameter in paths["/api/interviews/{session_id}/export"]["get"]["parameters"]
    )


def test_job_analysis_route_returns_existing_analysis_contract():
    response = client.post("/api/job/analyze", json={
        "description": "We develop Python and React applications.",
        "resume_text": "Built Python services.",
    })

    assert response.status_code == 200
    result = response.json()
    assert set(result) == {
        "required_skills",
        "preferred_skills",
        "responsibilities",
        "experience_requirements",
        "matched_skills",
        "missing_skills",
        "match_score",
        "score_label",
        "evidence",
    }
    assert result["matched_skills"] == ["python"]
    assert result["missing_skills"] == ["react"]
    assert result["match_score"] == 50


def test_malformed_requests_missing_rag_documents_and_unavailable_ollama(monkeypatch):
    reset_database()
    invalid_resume = client.post("/api/resume/analyze", json={"text": "  "})
    invalid_interview = client.post("/api/interviews/start", json={"count": 0})
    assert invalid_resume.status_code == 422
    assert invalid_interview.status_code == 422

    monkeypatch.setattr(LocalKnowledgeBase, "retrieve", lambda *args, **kwargs: [])
    missing_documents = client.post("/api/rag/search", json={
        "workspace_id": "empty-workspace",
        "text": "Search an empty workspace.",
    })
    assert missing_documents.status_code == 200
    assert missing_documents.json() == {"sources": []}

    monkeypatch.setattr(get_settings(), "mock_llm", False)
    monkeypatch.setattr(
        OllamaService,
        "generate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            LLMUnavailableError("Cannot connect to Ollama. Start Ollama and retry.")
        ),
    )
    unavailable = client.post("/api/interviews/start", json={
        "interview_type": "python",
        "count": 1,
    })
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "detail": "Cannot connect to Ollama. Start Ollama and retry."
    }
