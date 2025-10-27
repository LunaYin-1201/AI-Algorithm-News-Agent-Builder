from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from typing import Iterable, List, Optional

import feedparser
import httpx
from sqlmodel import select

from ..db import session_context
from ..models import News
from .rss_sources import NEWS_FEEDS
from ..config import get_settings
from ..classify.keywords import is_ai_related_keywords
from ..classify.llm import is_ai_related_llm_sync


def _to_datetime(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        if isinstance(dt, str):
            return datetime.fromisoformat(dt)
        return datetime(*dt[:6])
    except Exception:
        return None


def _compute_hash(title: str, url: str, description: Optional[str]) -> str:
    text = "||".join([title or "", url or "", (description or "")[:1000]])
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15"
)


def _parse_feed(url: str):
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=10.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
            return parsed
    except Exception as e:
        print(f"news fetch error for {url}: {e}")
        return feedparser.parse(b"")


def _entry_datetime(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed", "created_parsed", "issued_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6])
            except Exception:
                pass
    for attr in ("published", "updated", "created", "issued"):
        s = getattr(entry, attr, None)
        if not s:
            continue
        try:
            dt = parsedate_to_datetime(s)
            if dt is not None:
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            pass
    return None


def fetch_news(sources: Optional[Iterable[str]] = None, max_age_days: Optional[int] = None) -> List[News]:
    settings = get_settings()
    sources = list(sources or NEWS_FEEDS)
    new_or_updated: List[News] = []
    max_age_days = max_age_days if max_age_days is not None else settings.max_age_days_default
    cutoff = datetime.utcnow() - timedelta(days=max_age_days) if max_age_days and max_age_days > 0 else None

    with session_context() as session:
        for feed_url in sources:
            parsed = _parse_feed(feed_url)
            for entry in parsed.entries:
                title = getattr(entry, "title", None) or ""
                url = getattr(entry, "link", None) or ""
                if not url:
                    continue
                description = getattr(entry, "summary", None)
                published_at = _entry_datetime(entry)

                if cutoff and (not published_at or published_at < cutoff):
                    continue

                # Relevance filtering (same as before)
                if settings.enable_llm_filter:
                    keyword_hit = is_ai_related_keywords(title, description)
                    llm_hit = is_ai_related_llm_sync(title, description) if not keyword_hit else True
                    relevant = bool(keyword_hit or (True if llm_hit is None else llm_hit))
                    if not relevant:
                        continue

                content_hash = _compute_hash(title, url, description)
                existing = session.exec(select(News).where(News.url == url)).first()
                if existing:
                    changed = False
                    if description and description != existing.description:
                        existing.description = description
                        changed = True
                    if (published_at and existing.published_at is None) or (
                        published_at and existing.published_at and published_at != existing.published_at
                    ):
                        existing.published_at = published_at
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
                    continue

                news = News(
                    title=title,
                    url=url,
                    source=parsed.feed.get("title", "rss"),
                    published_at=published_at,
                    description=description,
                    content_hash=content_hash,
                )
                session.add(news)
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    continue
                session.refresh(news)
                new_or_updated.append(news)

    return new_or_updated


