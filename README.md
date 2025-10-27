# AI Algorithm News Agent

## Setup

1) Python 3.12+
2) Create virtualenv and install deps
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3) Create `.env` (see below) and run backend
```bash
uvicorn backend.app.main:app --reload
```

4) (Optional) Run Streamlit UI
```bash
streamlit run backend/ui_streamlit.py
```

- The web frontend is served from the project `frontend/` directory at `/` by FastAPI.

## .env example

```env
# Database
DATABASE_URL=sqlite:///./news.db

# Admin token for privileged refresh endpoints (optional). If empty, refresh is open.
ADMIN_TOKEN=

# LLM configuration (Ollama-compatible, default)
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=llama3.1:8b

# Relevance filter for ingest (keywords + optional LLM yes/no)
ENABLE_LLM_FILTER=false

# Hacker News fetch defaults
HN_ENABLE=true
HN_MIN_POINTS=10
# HN_QUERY_TERMS can be comma-separated (optional)
```

## API (current)

- Health
  - GET `/api/health`

- Papers (arXiv → `Paper` table)
  - GET `/api/papers?limit=50&offset=0&q=`
  - GET `/api/papers/refresh/stream?token=&max_age_days=7&summarize_limit=30&summarize_concurrency=1`

- News (HN/Blogs → `News` table)
  - GET `/api/news?limit=50&offset=0&source=&q=&domain=&only_summarized=false`
  - GET `/api/news/sources`
  - GET `/api/news/refresh/stream?token=&max_age_days=7&include_hn=true&hn_min_points=10&hn_terms=&summarize_limit=30&summarize_concurrency=1`

- Backward-compat (legacy)
  - GET `/api/articles` and related endpoints still exist but may be removed later.

Notes
- Stream endpoints are Server-Sent Events (SSE). The UI consumes them for real-time progress.
- Summarization supports configurable concurrency; each completed item is committed and pushed incrementally.
- If `ADMIN_TOKEN` is set in `.env`, the refresh/stream endpoints require `token` to match; otherwise they are open.

## Streamlit UI

- Two tabs:
  - 论文 (arXiv): 搜索、列表、按钮“抓取论文并摘要”。
  - 资讯 (HN/Blogs): 搜索、来源筛选、可选“仅显示已摘要”、按钮“抓取资讯并摘要”。（无“加载更多”）
- 侧边栏可配置每页条数、最大天数、HN 参数、摘要并行数与单次条数。

## Troubleshooting

- RSS/Atom 返回空（entries 0）：
  - 本机先确认 `curl -L https://arxiv.org/rss/cs.AI` 是否返回 XML。
  - 程序已尝试 arXiv 多镜像与 API 兜底；若仍为 0，多半是网络代理/网关返回了 HTML 或拦截页。
  - 在同一终端中启动后端以继承相同代理环境；httpx 已启用 `trust_env=True` 与 `follow_redirects=True`。

- SSE 读取超时：
  - Streamlit 使用 `timeout=(10, None)` 和 `Accept: text/event-stream`，避免长任务断开。

- 端口占用：
  - `lsof -nP -iTCP:8000 | grep LISTEN` 找到进程后 `kill -TERM <PID>`。
