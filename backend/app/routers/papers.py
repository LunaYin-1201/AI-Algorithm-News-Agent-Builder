from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import select

from ..db import get_session
from ..models import Paper
from ..schemas import PaperOut
from ..config import get_settings
from ..ingest.arxiv_fetcher import fetch_arxiv, fetch_arxiv_stream
from ..scheduler import summarize_papers_stream


router = APIRouter()


@router.get("/papers", response_model=List[PaperOut])
def list_papers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None),
    session=Depends(get_session),
):
    stmt = select(Paper).order_by(Paper.published_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Paper.title.ilike(like))
    stmt = stmt.limit(limit).offset(offset)
    items = session.exec(stmt).all()
    return items


@router.get("/papers/refresh/stream")
def refresh_papers_stream(
    token: Optional[str] = Query(None),
    max_age_days: Optional[int] = Query(None, ge=0, le=90),
    summarize_limit: int = Query(30, ge=1, le=500),
    summarize_concurrency: int = Query(1, ge=1, le=20),
):
    settings = get_settings()
    # If admin_token is set, enforce it; otherwise allow
    if settings.admin_token and token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    def gen():
        yield "data: starting refresh\n\n"
        yield "data: fetching arxiv...\n\n"
        upserts = 0
        collected: list[tuple[str, str, str]] = []  # (kind, title, url)
        for ev, payload in fetch_arxiv_stream(max_age_days=max_age_days):
            if ev == "feed":
                yield f"data: feed {payload}\n\n"
            elif ev == "info":
                yield f"data: feed {payload}\n\n"
            elif ev == "upsert":
                upserts += 1
                yield f"data: fetched #{upserts}: {payload[:80]}\n\n"
                # Note: fetch_arxiv_stream currently yields only title; URL is not returned.
                # We keep title-only push for now to avoid extra lookups.
                collected.append(("Paper", payload, ""))
            elif ev == "error":
                yield f"data: fetch error: {payload}\n\n"
        yield f"data: fetched total {upserts}\n\n"
        yield "data: summarizing...\n\n"
        i = 0
        for _id, title in summarize_papers_stream(limit=summarize_limit, concurrency=summarize_concurrency):
            i += 1
            yield f"data: summarized #{i}: {title[:80]}\n\n"
        yield f"data: summarized total {i}\n\n"
        yield "data: done\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


