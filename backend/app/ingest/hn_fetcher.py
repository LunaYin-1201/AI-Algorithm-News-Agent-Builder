from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from typing import Iterable, List, Optional, Set

import httpx
from sqlmodel import select

from ..db import session_context
from ..models import News
from ..config import get_settings
from ..classify.keywords import is_ai_related_keywords
from ..classify.llm import is_ai_related_llm_sync


def _compute_hash(title: str, url: str, description: Optional[str]) -> str:
    text = "||".join([title or "", url or "", (description or "")[:1000]])
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _to_dt(created_at: Optional[str], created_at_i: Optional[int]) -> Optional[datetime]:
    if created_at_i is not None:
        try:
            return datetime.utcfromtimestamp(int(created_at_i))
        except Exception:
            pass
    if created_at:
        try:
            # Example: 2024-10-24T06:21:35.000Z
            s = created_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo:
                return dt.astimezone(tz=None).replace(tzinfo=None)
            return dt
        except Exception:
            return None
    return None


DEFAULT_TERMS: List[str] = [
    "AI",
    "LLM",
    "machine learning",
    "deep learning",
    "NLP",
    "OpenAI",
    "人工智能",
    "大模型",
]


def fetch_hn(
    query_terms: Optional[Iterable[str]] = None,
    max_age_days: Optional[int] = None,
    min_points: Optional[int] = None,
) -> List[News]:
    """Fetch Hacker News stories via Algolia API and upsert into DB.

    Returns list of new/updated Article rows in this run.
    """
    settings = get_settings()
    terms = list(query_terms or (settings.hn_query_terms.split(",") if getattr(settings, "hn_query_terms", None) else DEFAULT_TERMS))
    terms = [t.strip() for t in terms if t and t.strip()]
    if not terms:
        terms = DEFAULT_TERMS

    max_age_days = max_age_days if max_age_days is not None else settings.max_age_days_default
    cutoff = datetime.utcnow() - timedelta(days=max_age_days) if max_age_days and max_age_days > 0 else None
    min_points = min_points if min_points is not None else getattr(settings, "hn_min_points", 10)

    new_or_updated: List[News] = []
    seen_urls: Set[str] = set()

    def add_story(session, title: str, url: Optional[str], created_at: Optional[datetime]):
        nonlocal new_or_updated
        if not url:
            return
        if url in seen_urls:
            return
        seen_urls.add(url)
        existing = session.exec(select(News).where(News.url == url)).first()
        content_hash = _compute_hash(title, url, None)
        if existing:
            changed = False
            if (created_at and existing.published_at is None) or (
                created_at and existing.published_at and existing.published_at != created_at
            ):
                existing.published_at = created_at
                changed = True
            if content_hash and content_hash != (existing.content_hash or ""):
                existing.content_hash = content_hash
                changed = True
            if changed:
                existing.updated_at = datetime.utcnow()
                session.add(existing)
                session.commit()
                session.refresh(existing)
                new_or_updated.append(existing)
            return

        article = News(
            title=title or "",
            url=url,
            source="Hacker News",
            published_at=created_at,
            description=None,
            content_hash=content_hash,
        )
        session.add(article)
        try:
            session.commit()
        except Exception:
            session.rollback()
            return
        session.refresh(article)
        new_or_updated.append(article)

    with session_context() as session:
        with httpx.Client(timeout=10.0, headers={"User-Agent": "ai-news-agent/1.0"}) as client:
            for term in terms:
                try:
                    # Use search_by_date to get latest items; restrict to stories
                    params = {
                        "query": term,
                        "tags": "story",
                        "hitsPerPage": 50,
                        "page": 0,
                    }
                    r = client.get("https://hn.algolia.com/api/v1/search_by_date", params=params)
                    r.raise_for_status()
                    data = r.json()
                    for hit in data.get("hits", []):
                        title = hit.get("title") or hit.get("story_title") or ""
                        url = hit.get("url") or hit.get("story_url")
                        # Fallback to HN item link if no external URL (e.g., Ask HN)
                        if not url and hit.get("objectID"):
                            url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                        created_at = _to_dt(hit.get("created_at"), hit.get("created_at_i"))
                        if cutoff and (not created_at or created_at < cutoff):
                            continue
                        points = hit.get("points")
                        if isinstance(points, int) and points < int(min_points):
                            continue
                        # Unified relevance filtering (same as rss_fetcher)
                        if settings.enable_llm_filter:
                            keyword_hit = is_ai_related_keywords(title, None)
                            llm_hit = is_ai_related_llm_sync(title, None) if not keyword_hit else True
                            relevant = bool(keyword_hit or (True if llm_hit is None else llm_hit))
                            print(f"[ingest.filter] kw={keyword_hit} llm={llm_hit} relevant={relevant} title={title[:80]}")
                            if not relevant:
                                continue
                        add_story(session, title, url, created_at)
                except Exception as e:
                    print(f"[ingest.hn] fetch error for term '{term}': {e}")

            # Also fetch front page (hot)
            try:
                params = {
                    "tags": "front_page",
                    "hitsPerPage": 50,
                    "page": 0,
                }
                r = client.get("https://hn.algolia.com/api/v1/search", params=params)
                r.raise_for_status()
                data = r.json()
                for hit in data.get("hits", []):
                    title = hit.get("title") or hit.get("story_title") or ""
                    url = hit.get("url") or hit.get("story_url")
                    if not url and hit.get("objectID"):
                        url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                    created_at = _to_dt(hit.get("created_at"), hit.get("created_at_i"))
                    if cutoff and (not created_at or created_at < cutoff):
                        continue
                    points = hit.get("points")
                    if isinstance(points, int) and points < int(min_points):
                        continue
                    if settings.enable_llm_filter:
                        keyword_hit = is_ai_related_keywords(title, None)
                        llm_hit = is_ai_related_llm_sync(title, None) if not keyword_hit else True
                        relevant = bool(keyword_hit or (True if llm_hit is None else llm_hit))
                        print(f"[ingest.filter] kw={keyword_hit} llm={llm_hit} relevant={relevant} title={title[:80]}")
                        if not relevant:
                            continue
                    add_story(session, title, url, created_at)
            except Exception as e:
                print(f"[ingest.hn] fetch error for front_page: {e}")

    return new_or_updated


