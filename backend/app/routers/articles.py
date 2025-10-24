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
from fastapi import BackgroundTasks
from ..scheduler import _summarize_pending, summarize_stream


router = APIRouter()


@router.get("/articles", response_model=List[ArticleOut])
def list_articles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    session=Depends(get_session),
):
    stmt = select(Article).order_by(Article.published_at.desc())
    if source:
        stmt = stmt.where(Article.source == source)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Article.title.ilike(like))
    stmt = stmt.limit(limit).offset(offset)
    items = session.exec(stmt).all()
    return items


@router.post("/refresh")
def manual_refresh(
    x_admin_token: Optional[str] = Header(None),
    max_age_days: Optional[int] = Query(None, ge=0, le=90),
):
    settings = get_settings()
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    changed = fetch_rss_sources(max_age_days=max_age_days)
    n = _summarize_pending()
    return {"updated": len(changed), "summarized": n}


@router.get("/refresh/stream")
def manual_refresh_stream(token: Optional[str] = Query(None), max_age_days: Optional[int] = Query(None, ge=0, le=90)):
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
        yield "data: summarizing...\n\n"
        i = 0
        for _id, title in summarize_stream():
            i += 1
            yield f"data: summarized #{i}: {title[:80]}\n\n"
        yield f"data: summarized total {i}\n\n"
        yield "data: done\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


