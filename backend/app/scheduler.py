from __future__ import annotations

from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import select

from .db import session_context
from .ingest.rss_fetcher import fetch_rss_sources
from .models import Article
from .summarize.llm import summarize_with_llm_sync
from .summarize.extractive import summarize_extractive
from .config import get_settings


def _summarize_pending(limit: int = 30) -> int:
    """Summarize articles without summary. Returns number processed."""
    count = 0
    with session_context() as session:
        articles = session.exec(
            select(Article).where(Article.summary == None).order_by(Article.published_at.desc())  # noqa: E711
        ).all()
        for art in articles[:limit]:
            text = summarize_with_llm_sync(art.title, art.description)
            if not text:
                text = summarize_extractive(art.title, art.description)
            if text:
                art.summary = text
                session.add(art)
                session.commit()
                count += 1
    return count


def create_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler()

    # fetch every 30 minutes
    scheduler.add_job(lambda: fetch_rss_sources(), "interval", minutes=30, id="fetch_rss")

    # summarize every 10 minutes
    scheduler.add_job(lambda: _summarize_pending(), "interval", minutes=10, id="summarize")

    return scheduler


def summarize_stream(limit: int = 30):
    """Generator that summarizes pending articles one by one and yields (id, title)."""
    with session_context() as session:
        articles = session.exec(
            select(Article).where(Article.summary == None).order_by(Article.published_at.desc())  # noqa: E711
        ).all()
        processed = 0
        for art in articles:
            if processed >= limit:
                break
            text = summarize_with_llm_sync(art.title, art.description)
            if not text:
                text = summarize_extractive(art.title, art.description)
            if text:
                art.summary = text
                session.add(art)
                session.commit()
                processed += 1
                yield art.id, art.title or ""


