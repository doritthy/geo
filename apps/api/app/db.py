from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()


def _normalize_url(url: str) -> str:
    """Ensure the psycopg (v3) driver is used even if DATABASE_URL is given as
    the plain 'postgresql://' scheme (which SQLAlchemy would otherwise route
    to psycopg2, which we do not depend on)."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# psycopg (v3) driver, SQLAlchemy 2.0 style
engine = create_engine(_normalize_url(settings.DATABASE_URL), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
