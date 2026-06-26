#!/usr/bin/env python3
# [Flow: Step 1 (engine 생성) -> Step 2 (SessionLocal 팩토리) -> Step 3 (get_db 의존성)]
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    """FastAPI 의존성: 요청당 세션 생성 후 정리."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
