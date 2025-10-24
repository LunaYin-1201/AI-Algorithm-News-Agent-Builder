# AI Algorithm News Agent (Backend)

## Setup

1. Python 3.11+
2. Create virtualenv and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Create `.env` (see below) and run:

```bash
uvicorn app.main:app --reload
```

The frontend is served from `backend/frontend/index.html` at `/`.

## .env example

```env
DATABASE_URL=sqlite:///./news.db

# Admin token for POST /api/refresh
ADMIN_TOKEN=changeme

# LLM configuration (OpenAI-compatible)
# For DeepSeek:
# LITELLM_BASE_URL=https://api.deepseek.com/v1
# LITELLM_API_KEY=sk-...

# Or OpenAI:
# OPENAI_API_KEY=sk-...

# Choose model (optional). Defaults: deepseek-chat if base URL contains deepseek; else gpt-4o-mini
# LLM_MODEL=deepseek-chat

# Enable LLM relevance filter for RSS entries
ENABLE_LLM_FILTER=false
```

## API

- GET `/api/health`
- GET `/api/articles?limit=50&source=&q=`
- POST `/api/refresh` with header `X-Admin-Token: <ADMIN_TOKEN>`

## Notes

- RSS relevance filter: keyword prefilter + optional DeepSeek/OpenAI yes/no check when `ENABLE_LLM_FILTER=true`.
- Summaries: LLM preferred (if keys provided), fallback to simple extractive.
