from __future__ import annotations

from typing import Optional

import httpx

from ..config import get_settings

PROMPT_TEMPLATE = (
    "你是资深科技编辑。请判断以下内容是否与AI算法/模型/研究密切相关。\n"
    "给出严格的 yes 或 no。\n\n"
    "标题: {title}\n"
    "摘要: {description}\n"
)


async def _call_chat(prompt: str, timeout: float = 12.0) -> Optional[str]:
    settings = get_settings()

    # Ollama-only endpoint
    base_url = settings.ollama_base_url
    api_key = None

    # Choose model: explicit setting > infer from base URL
    model_name = settings.llm_model or "qwen2.5:7b"

    headers = {"Content-Type": "application/json"}

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "只回答 yes 或 no"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4,
    }

    url = f"{base_url}/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .lower()
            )
            return text
        except Exception:
            return None


def is_ai_related_llm_sync(title: str, description: Optional[str]) -> Optional[bool]:
    """Sync wrapper for DeepSeek relevance classification.
    Returns True/False if LLM responded; None if unavailable or errored.
    """
    import anyio

    prompt = PROMPT_TEMPLATE.format(title=title, description=description or "")

    async def _inner() -> Optional[bool]:
        text = await _call_chat(prompt)
        if text is None:
            print(f"[classify.llm] none title={title[:80]}")
            return None
        result = text.startswith("y")
        print(f"[classify.llm] text={text!r} result={result} title={title[:80]}")
        return result

    try:
        return anyio.run(_inner)
    except Exception:
        return None


