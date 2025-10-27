from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import select

from ..db import get_session
from ..models import Article
from ..schemas import ArticleOut
from ..config import get_settings
from ..ingest.rss_fetcher import fetch_rss_sources
from ..ingest.hn_fetcher import fetch_hn
from fastapi import BackgroundTasks
from ..scheduler import _summarize_pending, summarize_stream, summarize_stream_async


router = APIRouter()


@router.get("/articles", response_model=List[ArticleOut])
def list_articles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    domain: Optional[str] = Query(None, description="按URL域名模糊过滤，如 arxiv.org"),
    session=Depends(get_session),
):
    stmt = select(Article).order_by(Article.published_at.desc())
    if source:
        stmt = stmt.where(Article.source == source)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Article.title.ilike(like))
    if domain:
        like_d = f"%{domain}%"
        stmt = stmt.where(Article.url.ilike(like_d))
    stmt = stmt.limit(limit).offset(offset)
    items = session.exec(stmt).all()
    return items


@router.get("/articles/sources", response_model=List[str])
def list_sources(session=Depends(get_session)):
    rows = session.exec(select(Article.source).distinct().order_by(Article.source)).all()
    sources = [r[0] if isinstance(r, (tuple, list)) else r for r in rows]
    return sources


@router.post("/refresh")
def manual_refresh(
    x_admin_token: Optional[str] = Header(None),
    max_age_days: Optional[int] = Query(None, ge=0, le=90),
    include_hn: bool = Query(False),
    hn_min_points: Optional[int] = Query(None, ge=0),
    hn_terms: Optional[str] = Query(None, description="逗号分隔关键词，留空用默认"),
):
    settings = get_settings()
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    changed = fetch_rss_sources(max_age_days=max_age_days)
    hn_changed = []
    if include_hn and settings.hn_enable:
        terms = [s.strip() for s in (hn_terms or "").split(",") if s.strip()] or None
        hn_changed = fetch_hn(query_terms=terms, max_age_days=max_age_days, min_points=hn_min_points)
    n = _summarize_pending()
    return {"updated": len(changed) + len(hn_changed), "rss_updated": len(changed), "hn_updated": len(hn_changed), "summarized": n}


@router.get("/refresh/stream")
def manual_refresh_stream(
    token: Optional[str] = Query(None),
    max_age_days: Optional[int] = Query(None, ge=0, le=90),
    include_hn: bool = Query(False),
    hn_min_points: Optional[int] = Query(None, ge=0),
    hn_terms: Optional[str] = Query(None, description="逗号分隔关键词，留空用默认"),
    summarize_limit: int = Query(30, ge=1, le=500),
    summarize_concurrency: int = Query(1, ge=1, le=20),
):
    settings = get_settings()
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    def gen():
        yield "data: starting refresh\n\n"
        try:
            yield "data: fetching rss...\n\n"
            changed = fetch_rss_sources(max_age_days=max_age_days)
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
        # Use sync summarizer to avoid event-loop blocking interactions
        for _id, title in summarize_stream(limit=summarize_limit, concurrency=summarize_concurrency):
            i += 1
            yield f"data: summarized #{i}: {title[:80]}\n\n"
        yield f"data: summarized total {i}\n\n"
        yield "data: done\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


