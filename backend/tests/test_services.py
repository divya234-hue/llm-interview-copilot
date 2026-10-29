import io

import pymupdf
import pytest
import numpy as np
from docx import Document
from pydantic import ValidationError
import httpx

from app.services.analysis import analyze_job, analyze_resume, extract_skills
from app.services.documents import extract_text, split_chunks
from app.services.llm import LLMUnavailableError, OllamaService
from app.schemas.interview import Evaluation


def test_extract_text_from_pdf_and_docx():
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Python developer and machine learning student")
    pdf_bytes = pdf.tobytes()
    pdf.close()
    assert "Python developer" in extract_text("resume.pdf", pdf_bytes)

    doc = Document()
    doc.add_paragraph("Built projects using FastAPI and SQL.")
    buffer = io.BytesIO()
    doc.save(buffer)
    assert "FastAPI" in extract_text("resume.docx", buffer.getvalue())


def test_document_parser_rejects_bad_file_and_empty_document():
    with pytest.raises(ValueError, match="invalid or unreadable"):
        extract_text("bad.pdf", b"not a pdf")
    with pytest.raises(ValueError, match="Only PDF and DOCX"):
        extract_text("resume.txt", b"content")


def test_split_chunks_respects_overlap_and_arguments():
    chunks = split_chunks("abcdefghij " * 12, chunk_size=40, overlap=8)
    assert len(chunks) > 1
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert chunks[0][-8:] in chunks[1]
    with pytest.raises(ValueError):
        split_chunks("text", chunk_size=10, overlap=10)


def test_resume_and_job_analysis_is_evidence_based():
    resume = "Education: B.Tech. Project: built a Python and FastAPI application."
    result = analyze_resume(resume)
    assert result["skills"] == ["fastapi", "python"]
    assert "education" in result["sections_found"]
    assert "experience" in result["sections_not_found"]
    match = analyze_job("We develop applications with Python and React.", resume)
    assert match["matched_skills"] == ["python"]
    assert match["missing_skills"] == ["react"]
    assert "not an objective hiring probability" in match["score_label"]
    assert "Project: built a Python" in match["evidence"]["python"]
    categorized = analyze_job("Required: Python. Preferred: React.", resume)
    assert categorized["required_skills"] == ["python"]
    assert categorized["preferred_skills"] == ["react"]
    assert categorized["experience_requirements"] == []


def test_llm_json_extractor_handles_markdown_and_rejects_plain_text():
    assert OllamaService._extract_json('```json\n{"ok": true}\n```') == '{"ok": true}'
    assert OllamaService._extract_json('Here is the result:\n{"ok": true}\nDone.') == '{"ok": true}'
    with pytest.raises(ValueError):
        OllamaService._extract_json("No JSON here")


def test_mock_llm_generates_questions_and_evaluations(monkeypatch):
    from app.api.routes import QuestionSet
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "mock_llm", True)
    service = OllamaService()
    questions = service.generate(
        "Create 2 personalized interview questions.\nInterview type: python.",
        QuestionSet,
    )
    assert len(questions.questions) == 2
    assert questions.questions[0].text.startswith("[Mock]")
    evaluation = service.generate("evaluate", Evaluation)
    assert evaluation.overall_score == 7
    assert service.status()["mode"] == "mock"


def test_ollama_reports_connect_timeout_and_missing_model(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "ollama_model", "llama3.2")
    service = OllamaService()

    def connect_error(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.services.llm.httpx.post", connect_error)
    with pytest.raises(LLMUnavailableError, match="Cannot connect to Ollama"):
        service.generate("prompt")

    request = httpx.Request("POST", "http://localhost:11434/api/generate")
    response = httpx.Response(404, json={"error": "model not found"}, request=request)
    monkeypatch.setattr("app.services.llm.httpx.post", lambda *args, **kwargs: response)
    with pytest.raises(LLMUnavailableError, match="ollama pull llama3.2"):
        service.generate("prompt")

    monkeypatch.setattr(
        "app.services.llm.httpx.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ReadTimeout("late")),
    )
    with pytest.raises(LLMUnavailableError, match="did not respond"):
        service.generate("prompt")


def test_ollama_status_reports_service_and_model_state(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "ollama_model", "llama3.2")
    request = httpx.Request("GET", "http://localhost:11434/api/tags")
    monkeypatch.setattr(
        "app.services.llm.httpx.get",
        lambda *args, **kwargs: httpx.Response(200, json={"models": [{"name": "mistral:latest"}]}, request=request),
    )
    status = OllamaService().status()
    assert status["available"] is True
    assert status["model_installed"] is False
    assert status["message"] == "Run: ollama pull llama3.2"

    monkeypatch.setattr(
        "app.services.llm.httpx.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(httpx.ConnectError("refused")),
    )
    status = OllamaService().status()
    assert status["available"] is False
    assert "Cannot reach Ollama" in status["message"]


@pytest.mark.parametrize(
    ("raw_response", "expected_text"),
    [
        (
            '{"questions":[{"text":"What is Python?","topic":"Python","criteria":["basic understanding"],"expected_concepts":["syntax"]}]}',
            "What is Python?",
        ),
        (
            'Here is the result:\n```json\n{"questions":[{"text":"What is Python?","topic":"Python","criteria":["basic understanding"],"expected_concepts":["syntax"]}]}\n```',
            "What is Python?",
        ),
    ],
)
def test_ollama_parses_valid_and_fenced_json(monkeypatch, raw_response, expected_text):
    from app.api.routes import QuestionSet
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "ollama_model", "llama3.2")

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(
            200,
            json={"response": raw_response},
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
        )

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    result = OllamaService().generate("prompt", QuestionSet)
    assert result.questions[0].text == expected_text
    assert len(calls) == 1
    assert calls[0]["format"] == QuestionSet.model_json_schema()


@pytest.mark.parametrize(
    ("raw_response", "description"),
    [
        ('{"questions":[{"text":"Question without its closing delimiters"', "malformed JSON"),
        ('{"unexpected":[]}', "missing required fields"),
        ('{"questions":[{"text":"Question","criteria":"not a list"}]}', "incorrect field type"),
    ],
)
def test_ollama_retries_and_rejects_invalid_structured_output(
    monkeypatch,
    raw_response,
    description,
):
    from app.api.routes import QuestionSet
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "ollama_model", "llama3.2")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(
            200,
            json={"response": raw_response},
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
        )

    monkeypatch.setattr("app.services.llm.httpx.post", fake_post)
    with pytest.raises(
        LLMUnavailableError,
        match=f"after 3 attempts",
    ):
        OllamaService().generate("prompt", QuestionSet)
    assert description
    assert len(calls) == 3
    assert all(call["format"] == QuestionSet.model_json_schema() for call in calls)
    assert "previous response was invalid" in calls[1]["prompt"]


def test_evaluation_ollama_schema_requires_valid_category_scores():
    schema = OllamaService._response_schema(Evaluation)
    category_scores = schema["properties"]["category_scores"]
    assert set(category_scores["required"]) == {
        "technical_correctness",
        "relevance",
        "depth",
        "clarity",
        "examples",
    }
    assert category_scores["properties"]["technical_correctness"] == {
        "type": "number",
        "minimum": 0,
        "maximum": 10,
    }


def test_invalid_raw_response_logging_is_development_only_and_explicit(monkeypatch, caplog):
    from app.api.routes import QuestionSet
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "debug", True)
    raw_response = '{"invalid":"private answer should not be logged"}'
    monkeypatch.setattr(
        "app.services.llm.httpx.post",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"response": raw_response},
            request=httpx.Request("POST", "http://localhost:11434/api/generate"),
        ),
    )

    with pytest.raises(LLMUnavailableError):
        OllamaService().generate("private resume context", QuestionSet)
    assert raw_response not in caplog.text

    caplog.clear()
    with pytest.raises(LLMUnavailableError):
        OllamaService().generate(
            "generic prompt",
            QuestionSet,
            allow_raw_response_logging=True,
        )
    assert raw_response in caplog.text


def test_evaluation_schema_rejects_out_of_range_category_scores():
    with pytest.raises(ValidationError, match="between 0 and 10"):
        Evaluation(
            overall_score=8,
            category_scores={
                "technical_correctness": 11,
                "relevance": 8,
                "depth": 7,
                "clarity": 8,
                "examples": 7,
            },
            strengths=[],
            missing_concepts=[],
            unsupported_statements=[],
            improved_answer="",
            follow_up_question="",
        )


def test_local_knowledge_base_chunks_and_retrieves_with_local_embedding(monkeypatch, tmp_path):
    from app.services import rag

    class FakeCollection:
        records = []

        def count(self):
            return len(self.records)

        def upsert(self, ids, documents, embeddings, metadatas):
            self.records.extend(zip(ids, documents, metadatas))

        def query(self, query_embeddings, n_results, where):
            documents = [
                text for _, text, metadata in self.records
                if metadata["workspace_id"] == where["workspace_id"]
            ]
            return {"documents": [documents[:n_results]]}

        def delete(self, where):
            self.records = [record for record in self.records if record[2]["document_id"] != where["document_id"]]

    class FakeEmbedder:
        def encode(self, texts):
            return np.array([[0.1, 0.2] for _ in texts])

    collection = FakeCollection()
    monkeypatch.setattr(rag, "_get_chroma_collection", lambda path: collection)
    monkeypatch.setattr(rag, "_get_embedder", lambda model_name: FakeEmbedder())
    knowledge = rag.LocalKnowledgeBase()
    knowledge.path = str(tmp_path)
    count = knowledge.add_document("workspace-1", "test-document", "Python builds reliable services.", "resume")
    assert count == 1
    assert knowledge.retrieve("What did the resume say about Python?", workspace_id="workspace-1") == ["Python builds reliable services."]
    assert knowledge.retrieve("What did the resume say about Python?", workspace_id="workspace-2") == []
