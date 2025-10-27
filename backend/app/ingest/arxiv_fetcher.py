from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from typing import Iterable, List, Optional

import feedparser
import httpx
from sqlmodel import select

from ..db import session_context
from ..models import Paper
from .rss_sources import ARXIV_FEEDS
from ..config import get_settings
from .rss_fetcher import _parse_feed_with_fallback as _parse_feed_with_fallback_shared


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


def _parse_feed_with_fallback(url: str):
    try:
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        # Reuse the shared, previously working parser from rss_fetcher
        return _parse_feed_with_fallback_shared(url)
    except Exception as e:
        print(f"fetch error for {url}: {e}")
        try:
            # last-resort: let feedparser fetch directly
            return feedparser.parse(url)
        except Exception:
            return feedparser.parse(b"")


def _fetch_arxiv_api_by_category(category: str):
    """Fetch via arXiv API (Atom) for cases where RSS returns zero entries."""
    api_url = (
        f"https://export.arxiv.org/api/query?search_query=cat:{category}"
        "&sortBy=submittedDate&sortOrder=descending&max_results=100"
    )
    try:
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
        with httpx.Client(headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True, trust_env=True) as client:
            r = client.get(api_url)
            r.raise_for_status()
            return feedparser.parse(r.text)
    except Exception as e:
        print(f"arxiv api error for {category}: {e}", flush=True)
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


def fetch_arxiv(max_age_days: Optional[int] = None, sources: Optional[Iterable[str]] = None) -> List[Paper]:
    settings = get_settings()
    sources = list(sources or ARXIV_FEEDS)
    new_or_updated: List[Paper] = []
    max_age_days = max_age_days if max_age_days is not None else settings.max_age_days_default
    cutoff = datetime.utcnow() - timedelta(days=max_age_days) if max_age_days and max_age_days > 0 else None

    with session_context() as session:
        for feed_url in sources:
            parsed = _parse_feed_with_fallback(feed_url)
            for entry in parsed.entries:
                title = getattr(entry, "title", None) or ""
                url = getattr(entry, "link", None) or ""
                if not url:
                    continue
                description = getattr(entry, "summary", None)
                published_at = _entry_datetime(entry)

                if cutoff and (not published_at or published_at < cutoff):
                    continue

                content_hash = _compute_hash(title, url, description)

                existing = session.exec(select(Paper).where(Paper.url == url)).first()
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

                paper = Paper(
                    title=title,
                    url=url,
                    source=parsed.feed.get("title", "arXiv"),
                    published_at=published_at,
                    description=description,
                    content_hash=content_hash,
                )
                session.add(paper)
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    continue
                session.refresh(paper)
                new_or_updated.append(paper)

    return new_or_updated


def fetch_arxiv_stream(max_age_days: Optional[int] = None, sources: Optional[Iterable[str]] = None):
    """Generator variant: yields (event, payload) as items are upserted.

    Events:
      ("feed", url)
      ("upsert", title)
      ("error", message)
    """
    settings = get_settings()
    sources = list(sources or ARXIV_FEEDS)
    max_age_days = max_age_days if max_age_days is not None else settings.max_age_days_default
    cutoff = datetime.utcnow() - timedelta(days=max_age_days) if max_age_days and max_age_days > 0 else None

    with session_context() as session:
        for feed_url in sources:
            try:
                yield ("feed", feed_url)
                parsed = _parse_feed_with_fallback_shared(feed_url)
                try:
                    entries_len = len(getattr(parsed, "entries", []) or [])
                    print(f"entries {entries_len}", flush=True)
                    yield ("info", f"entries {entries_len}")
                except Exception:
                    pass
                if not getattr(parsed, "entries", None):
                    # Try arXiv API fallback by category inferred from URL
                    try:
                        # crude extraction: find segment after '/rss/'
                        if "/rss/" in feed_url:
                            category = feed_url.split("/rss/")[-1].strip("/") or "cs.AI"
                        else:
                            category = "cs.AI"
                        api_parsed = _fetch_arxiv_api_by_category(category)
                        api_len = len(getattr(api_parsed, "entries", []) or [])
                        print(f"api entries {api_len} for {category}", flush=True)
                        yield ("info", f"api entries {api_len}")
                        if api_len:
                            parsed = api_parsed
                    except Exception as e:
                        print(f"api fallback error: {e}", flush=True)
                        yield ("error", f"api fallback error: {e}")
                for entry in parsed.entries:
                    title = getattr(entry, "title", None) or ""
                    url = getattr(entry, "link", None) or ""
                    if not url:
                        continue
                    description = getattr(entry, "summary", None)
                    published_at = _entry_datetime(entry)
                    if cutoff and (not published_at or published_at < cutoff):
                        continue
                    content_hash = _compute_hash(title, url, description)
                    existing = session.exec(select(Paper).where(Paper.url == url)).first()
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
                            yield ("upsert", title)
                        continue
                    paper = Paper(
                        title=title,
                        url=url,
                        source=parsed.feed.get("title", "arXiv"),
                        published_at=published_at,
                        description=description,
                        content_hash=content_hash,
                    )
                    session.add(paper)
                    try:
                        session.commit()
                        session.refresh(paper)
                        yield ("upsert", title)
                    except Exception as e:
                        session.rollback()
                        yield ("error", str(e))
            except Exception as e:
                yield ("error", f"{feed_url}: {e}")


