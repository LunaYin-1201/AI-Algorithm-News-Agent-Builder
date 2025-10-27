from __future__ import annotations

from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import select

from .db import session_context
from .ingest.rss_fetcher import fetch_rss_sources
from .ingest.hn_fetcher import fetch_hn
from .models import Article, Paper, News
import asyncio
from .summarize.llm import summarize_with_llm_sync, summarize_with_llm_async
from .summarize.extractive import summarize_extractive
from .config import get_settings


def _summarize_pending(limit: int = 30) -> int:
    """Summarize articles without summary. Returns number processed."""
    count = 0
    with session_context() as session:
        articles = session.exec(
            select(Article)
            .where(Article.summary == None)  # noqa: E711
            .order_by(Article.published_at.is_(None))  # NULLs last
            .order_by(Article.published_at.desc())
            .order_by(Article.created_at.desc())
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

    if settings.hn_enable:
        # fetch HN every 30 minutes
        scheduler.add_job(lambda: fetch_hn(max_age_days=settings.max_age_days_default, min_points=settings.hn_min_points), "interval", minutes=30, id="fetch_hn")

    # summarize every 10 minutes
    scheduler.add_job(lambda: _summarize_pending(), "interval", minutes=10, id="summarize")

    return scheduler


def summarize_stream(limit: int = 30, concurrency: int = 1):
    """Generator that summarizes pending articles and yields (id, title).

    If concurrency > 1, model calls are executed concurrently (I/O-bound),
    and DB commits happen sequentially in the current thread.
    """
    with session_context() as session:
        articles = session.exec(
            select(Article)
            .where(Article.summary == None)  # noqa: E711
            .order_by(Article.published_at.is_(None))
            .order_by(Article.published_at.desc())
            .order_by(Article.created_at.desc())
        ).all()
        to_process = articles[:limit]
        processed = 0

        if concurrency <= 1:
            for art in to_process:
                try:
                    text = summarize_with_llm_sync(art.title, art.description)
                    if not text:
                        text = summarize_extractive(art.title, art.description)
                    if text:
                        art.summary = text
                        session.add(art)
                        session.commit()
                        processed += 1
                        yield art.id, art.title or ""
                except Exception as e:
                    session.rollback()
                    yield art.id, f"error: {str(e)[:60]}"
            return

        async def _run_batch():
            sem = asyncio.Semaphore(max(1, int(concurrency)))

            async def _job(art: Article):
                async with sem:
                    try:
                        text = await summarize_with_llm_async(art.title, art.description)
                        return art, text, None
                    except Exception as exc:
                        return art, None, exc

            tasks = [_job(art) for art in to_process]
            return await asyncio.gather(*tasks, return_exceptions=False)

        try:
            results = asyncio.run(_run_batch())
        except Exception as e:
            # Fallback to sequential if event loop issues
            results = []
            for art in to_process:
                results.append((art, None, e))

        for art, text, err in results:
            try:
                if err is not None:
                    text = None
                if not text:
                    text = summarize_extractive(art.title, art.description)
                if text:
                    art.summary = text
                    session.add(art)
                    session.commit()
                    processed += 1
                    yield art.id, art.title or ""
            except Exception as e:
                session.rollback()
                yield art.id, f"error: {str(e)[:60]}"


async def summarize_stream_async(limit: int = 30, concurrency: int = 1):
    """Async generator variant: yields as soon as each summary finishes.

    LLM calls run concurrently (I/O-bound) with a semaphore. DB commits happen
    sequentially when each task completes, to avoid DB session concurrency issues.
    """
    # Collect target articles first in a sync context
    with session_context() as session:
        articles = session.exec(
            select(Article).where(Article.summary == None).order_by(Article.published_at.desc())  # noqa: E711
        ).all()

    to_process = articles[:limit]
    if not to_process:
        return

    if concurrency <= 1:
        # Sequential async path
        for art in to_process:
            text = None
            try:
                text = await summarize_with_llm_async(art.title, art.description)
            except Exception:
                text = None
            if not text:
                text = summarize_extractive(art.title, art.description)
            if text:
                try:
                    with session_context() as session:
                        # Re-fetch to ensure current row
                        row = session.get(Article, art.id)
                        if row is None:
                            continue
                        row.summary = text
                        session.add(row)
                        session.commit()
                    yield art.id, art.title or ""
                except Exception as e:
                    yield art.id, f"error: {str(e)[:60]}"
        return

    # Concurrent LLM calls; DB commits on completion
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _job(art: Article):
        async with sem:
            try:
                text = await summarize_with_llm_async(art.title, art.description)
                return art, text, None
            except Exception as exc:
                return art, None, exc

    tasks = [asyncio.create_task(_job(art)) for art in to_process]
    for coro in asyncio.as_completed(tasks):
        art, text, err = await coro
        if err is not None:
            text = None
        if not text:
            text = summarize_extractive(art.title, art.description)
        if text:
            try:
                with session_context() as session:
                    row = session.get(Article, art.id)
                    if row is None:
                        continue
                    row.summary = text
                    session.add(row)
                    session.commit()
                yield art.id, art.title or ""
            except Exception as e:
                yield art.id, f"error: {str(e)[:60]}"


def summarize_papers_stream(limit: int = 30, concurrency: int = 1):
    with session_context() as session:
        rows = session.exec(
            select(Paper)
            .where(Paper.summary == None)  # noqa: E711
            .order_by(Paper.published_at.is_(None))
            .order_by(Paper.published_at.desc())
            .order_by(Paper.created_at.desc())
        ).all()
    # Reuse logic by mapping to Article-like objects
    # We will process sequentially to keep patch minimal
    processed = 0
    for row in rows:
        if processed >= limit:
            break
        try:
            text = summarize_with_llm_sync(row.title, row.description)
            if not text:
                text = summarize_extractive(row.title, row.description)
            if text:
                with session_context() as session:
                    p = session.get(Paper, row.id)
                    if not p:
                        continue
                    p.summary = text
                    session.add(p)
                    session.commit()
                processed += 1
                yield row.id, row.title or ""
        except Exception as e:
            yield row.id, f"error: {str(e)[:60]}"


def summarize_news_stream(limit: int = 30, concurrency: int = 1):
    with session_context() as session:
        rows = session.exec(
            select(News)
            .where(News.summary == None)  # noqa: E711
            .order_by(News.published_at.is_(None))
            .order_by(News.published_at.desc())
            .order_by(News.created_at.desc())
        ).all()
    processed = 0
    for row in rows:
        if processed >= limit:
            break
        try:
            text = summarize_with_llm_sync(row.title, row.description)
            if not text:
                text = summarize_extractive(row.title, row.description)
            if text:
                with session_context() as session:
                    n = session.get(News, row.id)
                    if not n:
                        continue
                    n.summary = text
                    session.add(n)
                    session.commit()
                processed += 1
                yield row.id, row.title or ""
        except Exception as e:
            yield row.id, f"error: {str(e)[:60]}"


