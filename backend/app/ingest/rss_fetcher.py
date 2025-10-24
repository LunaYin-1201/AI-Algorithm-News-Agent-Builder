from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from typing import Iterable, List, Optional

import feedparser
import httpx
from sqlmodel import select

from ..db import session_context
from ..models import Article
from .rss_sources import DEFAULT_RSS_SOURCES
from ..config import get_settings
from ..classify.keywords import is_ai_related_keywords
from ..classify.llm import is_ai_related_llm_sync


def _to_datetime(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        # feedparser returns time.struct_time in published_parsed
        if isinstance(dt, str):
            # Best-effort parse
            return datetime.fromisoformat(dt)
        # else assume struct_time
        return datetime(*dt[:6])
    except Exception:
        return None


def _compute_hash(title: str, url: str, description: Optional[str]) -> str:
    text = "||".join([title or "", url or "", (description or "")[:1000]])
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15"


def _parse_feed_with_fallback(url: str):
    """Fetch feed content with a browser-like User-Agent and parse.
    Falls back to http for arXiv if https yields empty entries.
    """
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=10.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
            if getattr(parsed, "bozo", 0):
                # Log parse issues to aid debugging
                print(f"feedparser bozo for {url}: {getattr(parsed, 'bozo_exception', '')}")
            if not parsed.entries and url.startswith("https://") and "export.arxiv.org" in url:
                http_url = "http://" + url[8:]
                r2 = client.get(http_url)
                r2.raise_for_status()
                parsed2 = feedparser.parse(r2.content)
                if getattr(parsed2, "bozo", 0):
                    print(f"feedparser bozo (fallback) for {http_url}: {getattr(parsed2, 'bozo_exception', '')}")
                if parsed2.entries:
                    return parsed2
            return parsed
    except Exception as e:
        print(f"fetch error for {url}: {e}")
        return feedparser.parse(b"")


def _entry_datetime(entry) -> Optional[datetime]:
    """Best-effort datetime extraction.
    Order: *_parsed struct_time → RFC822 strings → ISO8601 strings.
    Returns naive UTC datetime if tz-aware.
    """
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


def fetch_rss_sources(sources: Optional[Iterable[str]] = None, max_age_days: Optional[int] = None) -> List[Article]:
    """Fetch RSS feeds and upsert into DB. Returns new/updated Articles in this run."""
    sources = list(sources or DEFAULT_RSS_SOURCES)
    new_or_updated: List[Article] = []
    settings = get_settings()
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

                # Skip too-old items (treat missing date as too old when cutoff set)
                if cutoff and (not published_at or published_at < cutoff):
                    continue

                # Relevance filtering (keywords quick check + optional LLM verification)
                settings = get_settings()
                if settings.enable_llm_filter:
                    keyword_hit = is_ai_related_keywords(title, description)
                    llm_hit = is_ai_related_llm_sync(title, description) if not keyword_hit else True
                    # Fail-open: if LLM unavailable (None), allow
                    relevant = bool(keyword_hit or (True if llm_hit is None else llm_hit))
                    print(f"[ingest.filter] kw={keyword_hit} llm={llm_hit} relevant={relevant} title={title[:80]}")
                    if not relevant:
                        continue

                content_hash = _compute_hash(title, url, description)

                existing = session.exec(select(Article).where(Article.url == url)).first()
                if existing:
                    # Update minimal fields if changed
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

                    
                article = Article(
                    title=title,
                    url=url,
                    source=parsed.feed.get("title", "rss"),
                    published_at=published_at,
                    description=description,
                    content_hash=content_hash,
                )
                session.add(article)
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    continue
                session.refresh(article)
                new_or_updated.append(article)

    return new_or_updated


