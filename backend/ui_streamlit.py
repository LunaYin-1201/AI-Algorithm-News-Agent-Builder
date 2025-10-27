import os
import html
import requests
import streamlit as st


st.set_page_config(page_title="AI Algorithm News", layout="wide")
st.title("AI Algorithm News Agent")

DEFAULT_BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Styles for nicer summary rendering
st.markdown(
    """
<style>
.card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 10px; background: #ffffff; }
.title { font-weight: 600; font-size: 16px; margin-bottom: 6px; }
.date { color: #6b7280; font-size: 12px; margin-bottom: 8px; }
.summary { font-size: 14px; color: #111827; white-space: pre-wrap; word-break: break-word; line-height: 1.5; }

@media (prefers-color-scheme: dark) {
  .card { border-color: #1f2937; background: #121934; }
  .title { color: #e5e7eb; }
  .date { color: #9ca3af; }
  .summary { color: #e5e7eb; }
}
</style>
""",
    unsafe_allow_html=True,
)

def load_news(base_url: str, q: str, limit: int, offset: int = 0, source: str | None = None, domain: str | None = None, only_summarized: bool = False):
    try:
        params = {"limit": limit, "offset": offset, "q": q or ""}
        if source:
            params["source"] = source
        if domain:
            params["domain"] = domain
        if only_summarized:
            params["only_summarized"] = True
        r = requests.get(f"{base_url}/api/news", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"加载失败: {e}")
        return []


def load_papers(base_url: str, q: str, limit: int, offset: int = 0):
    try:
        params = {"limit": limit, "offset": offset, "q": q or ""}
        r = requests.get(f"{base_url}/api/papers", params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"加载失败: {e}")
        return []


def render_cards(ph, data):
    cards = []
    for a in data:
        title = html.escape(a.get('title','') or "")
        url = a.get('url','') or ""
        date = html.escape(str(a.get('published_at','') or ""))
        # fallback: summary -> description
        text = (a.get('summary') or a.get('description') or "").strip()
        summary = html.escape(text)
        source = html.escape(a.get('source','') or "")
        cards.append(
            f"<div class='card'><div class='title'><a href='{url}' target='_blank'>{title}</a></div>"
            f"<div class='date'>{date}{(' · ' + source) if source else ''}</div>"
            f"<div class='summary'>{summary}</div></div>"
        )
    ph.markdown("".join(cards), unsafe_allow_html=True)

@st.cache_data(ttl=300)
def load_news_sources(base_url: str):
    try:
        r = requests.get(f"{base_url}/api/news/sources", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


top = st.container()
with top:
    with st.sidebar:
        st.subheader("设置")
        base_url = st.text_input("API Base URL", DEFAULT_BASE)
        admin_token = st.text_input("Admin Token", DEFAULT_TOKEN, type="password")
        st.divider()
        st.subheader("分页")
        limit = st.slider("每页条数", min_value=10, max_value=200, value=50, step=10)
        max_age_days = st.slider("最大天数(刷新时)", min_value=0, max_value=90, value=7, step=1)
        st.subheader("Hacker News")
        include_hn = st.checkbox("包含 HN", value=True)
        hn_min_points = st.slider("HN 最少分数", min_value=0, max_value=500, value=10, step=5)
        hn_terms = st.text_input("HN 关键词(逗号分隔)", value="")
        st.subheader("摘要设置")
        summarize_concurrency = st.slider("LLM 并行数", min_value=1, max_value=20, value=1, step=1, help="并发请求到 LLM 的数量")
        summarize_limit = st.slider("本轮摘要条数", min_value=10, max_value=500, value=50, step=10, help="本次刷新最多处理的文章数量")
        st.caption("侧边栏：全局设置与刷新参数。")

if "offset_papers" not in st.session_state:
    st.session_state["offset_papers"] = 0

tab_papers, tab_news = st.tabs(["论文 (arXiv)", "资讯 (HN/Blogs)"])

with tab_papers:
    st.subheader("论文列表")
    q_p = st.text_input("搜索论文标题", "", key="q_papers")
    # 将抓取按钮上移至列表上方，移除“加载更多论文”
    trigger_refresh_papers = st.button("抓取论文并摘要")
    ph_papers = st.empty()
    data_papers = load_papers(base_url, q_p, int(limit), 0)
    render_cards(ph_papers, data_papers)

with tab_news:
    st.subheader("资讯列表")
    q_n = st.text_input("搜索资讯标题", "", key="q_news")
    sources = [""] + load_news_sources(base_url)
    source = st.selectbox("来源", options=sources, index=0, format_func=lambda x: "全部" if x == "" else x, key="source_news")
    only_sum = st.checkbox("仅显示已摘要", value=True, key="only_sum_news")
    # 抓取按钮上移至列表上方
    trigger_refresh_news = st.button("抓取资讯并摘要")
    ph_news = st.empty()
    data_news = load_news(base_url, q_n, int(limit), 0, source or None, None, only_sum)
    render_cards(ph_news, data_news)
    # 按需刷新资讯（不提供"加载更多资讯"按钮）

with st.container():
    if 'trigger_refresh_papers' in locals() and trigger_refresh_papers:
            try:
                # 使用 SSE 流式进度
                with st.spinner("抓取与摘要进行中..."):
                    with requests.get(
                        f"{base_url}/api/papers/refresh/stream",
                        params={
                            "token": admin_token,
                            "max_age_days": int(max_age_days),
                            "summarize_limit": int(summarize_limit),
                            "summarize_concurrency": int(summarize_concurrency),
                        },
                        headers={"Accept": "text/event-stream"},
                        stream=True,
                        timeout=(10, None),
                    ) as resp:
                        if resp.status_code != 200:
                            st.error(f"刷新失败: {resp.status_code}")
                        partial = []
                        for line in resp.iter_lines(decode_unicode=True):
                            if not line:
                                continue
                            if line.startswith("data: "):
                                msg = line[6:]
                                st.write(msg)
                                # 增量刷新：每次完成一条摘要时，重新加载并渲染列表
                                if msg.startswith("summarized #") or msg.startswith("summarized total") or msg == "done":
                                    data_papers = load_papers(base_url, q_p, int(limit), 0)
                                    render_cards(ph_papers, data_papers)
                st.success("完成")
                st.rerun()
            except Exception as e:
                st.error(f"请求错误: {e}")

with st.container():
    if 'trigger_refresh_news' in locals() and trigger_refresh_news:
            try:
                with st.spinner("抓取与摘要进行中..."):
                    with requests.get(
                        f"{base_url}/api/news/refresh/stream",
                        params={
                            "token": admin_token,
                            "max_age_days": int(max_age_days),
                            "include_hn": include_hn,
                            "hn_min_points": int(hn_min_points),
                            "hn_terms": hn_terms,
                            "summarize_limit": int(summarize_limit),
                            "summarize_concurrency": int(summarize_concurrency),
                        },
                        headers={"Accept": "text/event-stream"},
                        stream=True,
                        timeout=(10, None),
                    ) as resp:
                        if resp.status_code != 200:
                            st.error(f"刷新失败: {resp.status_code}")
                        for line in resp.iter_lines(decode_unicode=True):
                            if not line:
                                continue
                            if line.startswith("data: "):
                                msg = line[6:]
                                st.write(msg)
                                if msg.startswith("summarized #") or msg.startswith("summarized total") or msg == "done":
                                    data_news = load_news(base_url, q_n, int(limit), 0, source or None, None, only_sum)
                                    render_cards(ph_news, data_news)
                st.success("完成")
                st.rerun()
            except Exception as e:
                st.error(f"请求错误: {e}")



