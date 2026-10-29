from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    columns = {column["name"] for column in inspect(engine).get_columns("interview_sessions")}
    if "workspace_id" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE interview_sessions ADD COLUMN workspace_id VARCHAR(64) NOT NULL DEFAULT 'local'")
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_interview_sessions_workspace_id ON interview_sessions (workspace_id)")
            )
