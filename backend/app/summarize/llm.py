from __future__ import annotations

from typing import Optional

import httpx

from ..config import get_settings

SUMMARY_PROMPT = (
    "你是新闻编辑，请用中文生成 2-3 句要点式摘要，聚焦新模型/方法/数据/指标，"
    "不超过 120 字。\n\n"
    "标题: {title}\n"
    "描述: {description}\n"
)


async def _chat(prompt: str, timeout: float = 15.0) -> Optional[str]:
    settings = get_settings()
    base_url = settings.ollama_base_url
    api_key = None

    # Choose model (support Ollama by defaulting to llama3.1:8b on local URLs)
    model_name = settings.llm_model or "llama3.1:8b"

    headers = {"Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "用简洁中文输出，不要前缀词。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 200,
    }
    url = f"{base_url}/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            print(f"[summarize.llm] text={text!r}")
            return text or None
        except Exception:
            return None


def summarize_with_llm_sync(title: str, description: Optional[str]) -> Optional[str]:
    import anyio

    prompt = SUMMARY_PROMPT.format(title=title, description=description or "")

    async def _inner() -> Optional[str]:
        return await _chat(prompt)

    try:
        res = anyio.run(_inner)
        return res if res else None
    except Exception:
        return None


