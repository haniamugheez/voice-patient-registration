"""SQLAlchemy engine / session setup.

The rest of the application never talks to the database driver directly — it
goes through the session dependency below, which keeps the data layer swappable
(SQLite locally, Postgres in production) without touching business logic.
"""

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

db_url = settings.DATABASE_URL

# Render/Heroku hand out `postgres://` URLs; SQLAlchemy 2.x wants `postgresql://`
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

connect_args: dict = {}
if db_url.startswith("sqlite"):
    # FastAPI serves requests from a threadpool; SQLite needs this to be shared.
    connect_args = {"check_same_thread": False}
    # Make sure the folder that holds the .db file exists.
    if ":///" in db_url:
        path = db_url.split(":///", 1)[1]
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist yet."""
    from app import models  # noqa: F401  (import registers the models)

    Base.metadata.create_all(bind=engine)
