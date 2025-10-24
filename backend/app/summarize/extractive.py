from __future__ import annotations

import re
from typing import Optional


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"https?://\S+", "", text)
    return text.strip()


def summarize_extractive(title: str, description: Optional[str]) -> Optional[str]:
    if not title and not description:
        return None
    # simple heuristic: take first 1-2 sentences of cleaned description, else title
    desc = _clean(description or "")
    if not desc:
        return title[:120]
    sentences = re.split(r"(?<=[。！？.!?])\s+", desc)
    out = " ".join(sentences[:2]).strip()
    result = out[:180] if out else (title[:120] if title else None)
    print(f"[summ.extract] title={title[:80]} len={len(result or '')}")
    return result


