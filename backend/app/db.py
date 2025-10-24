from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        _engine = create_engine(settings.database_url, connect_args=connect_args)
    return _engine


def create_db_and_tables() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session


@contextmanager
def session_context() -> Iterator[Session]:
    engine = get_engine()
    with Session(engine) as session:
        yield session


