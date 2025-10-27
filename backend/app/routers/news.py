from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import select

from ..db import get_session
from ..models import News
from ..schemas import NewsOut
from ..config import get_settings
from ..ingest.news_fetcher import fetch_news
from ..ingest.hn_fetcher import fetch_hn
from ..scheduler import summarize_news_stream


router = APIRouter()


@router.get("/news", response_model=List[NewsOut])
def list_news(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    only_summarized: bool = Query(False, description="仅返回已有摘要的条目"),
    session=Depends(get_session),
):
    stmt = select(News).order_by(News.published_at.desc())
    if source:
        stmt = stmt.where(News.source == source)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(News.title.ilike(like))
    if domain:
        like_d = f"%{domain}%"
        stmt = stmt.where(News.url.ilike(like_d))
    if only_summarized:
        stmt = stmt.where(News.summary != None)  # noqa: E711
    stmt = stmt.limit(limit).offset(offset)
    items = session.exec(stmt).all()
    return items


@router.get("/news/sources", response_model=List[str])
def list_sources(session=Depends(get_session)):
    rows = session.exec(select(News.source).distinct().order_by(News.source)).all()
    sources = [r[0] if isinstance(r, (tuple, list)) else r for r in rows]
    return sources


@router.get("/news/refresh/stream")
def refresh_news_stream(
    token: Optional[str] = Query(None),
    max_age_days: Optional[int] = Query(None, ge=0, le=90),
    include_hn: bool = Query(True),
    hn_min_points: Optional[int] = Query(None, ge=0),
    hn_terms: Optional[str] = Query(None),
    summarize_limit: int = Query(30, ge=1, le=500),
    summarize_concurrency: int = Query(1, ge=1, le=20),
):
    settings = get_settings()
    if settings.admin_token and token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    def gen():
        yield "data: starting refresh\n\n"
        try:
            yield "data: fetching rss...\n\n"
            changed = fetch_news(max_age_days=max_age_days)
            yield f"data: fetched {len(changed)} items\n\n"
        except Exception as e:
            yield f"data: fetch error: {e}\n\n"
        if include_hn and settings.hn_enable:
            try:
                yield "data: fetching hn...\n\n"
                terms = [s.strip() for s in (hn_terms or "").split(",") if s.strip()] or None
                hn_changed = fetch_hn(query_terms=terms, max_age_days=max_age_days, min_points=hn_min_points)
                yield f"data: fetched hn {len(hn_changed)} items\n\n"
            except Exception as e:
                yield f"data: hn fetch error: {e}\n\n"
        yield "data: summarizing...\n\n"
        i = 0
        for _id, title in summarize_news_stream(limit=summarize_limit, concurrency=summarize_concurrency):
            i += 1
            yield f"data: summarized #{i}: {title[:80]}\n\n"
        yield f"data: summarized total {i}\n\n"
        yield "data: done\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


