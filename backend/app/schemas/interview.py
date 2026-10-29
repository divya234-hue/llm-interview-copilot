from typing import Literal

from pydantic import BaseModel, Field, field_validator


class JobAnalysisRequest(BaseModel):
    description: str = Field(min_length=30, max_length=30000)
    resume_text: str = Field(default="", max_length=30000)


class InterviewGenerateRequest(BaseModel):
    workspace_id: str = Field(default="local", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    resume_text: str = Field(default="", max_length=30000)
    job_description: str = Field(default="", max_length=30000)
    experience_level: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    interview_type: Literal["technical", "hr", "python", "programming", "dsa", "ml", "nlp_llm_rag", "projects", "behavioral", "system_design", "mixed"] = "mixed"
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    count: int = Field(default=5, ge=1, le=10)


class InterviewStartRequest(InterviewGenerateRequest):
    title: str = Field(default="Practice interview", max_length=200)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=10000)


class Question(BaseModel):
    text: str
    topic: str = "General"
    criteria: list[str] = Field(default_factory=list)
    expected_concepts: list[str] = Field(default_factory=list)


class Evaluation(BaseModel):
    overall_score: float = Field(ge=0, le=10)
    category_scores: dict[str, float]
    strengths: list[str]
    missing_concepts: list[str]
    unsupported_statements: list[str]
    improved_answer: str
    follow_up_question: str
    source_snippets: list[str] = Field(default_factory=list)

    @field_validator("category_scores")
    @classmethod
    def validate_category_scores(cls, scores: dict[str, float]) -> dict[str, float]:
        required = {"technical_correctness", "relevance", "depth", "clarity", "examples"}
        if not required.issubset(scores):
            raise ValueError("All five evaluation categories are required.")
        if any(score < 0 or score > 10 for score in scores.values()):
            raise ValueError("Category scores must be between 0 and 10.")
        return scores
