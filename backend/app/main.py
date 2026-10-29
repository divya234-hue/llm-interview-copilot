import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db.database import initialize_database
from app.models import IndexedDocument, InterviewSession  # noqa: F401

logging.basicConfig(level=logging.INFO)
settings = get_settings()
initialize_database()
app = FastAPI(title=settings.app_name, version="1.0.0", description="Local-first AI interview practice API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root():
    return {"message": "LLM Interview Copilot API", "docs": "/docs"}
