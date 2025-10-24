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
.card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 10px; }
.title { font-weight: 600; font-size: 16px; margin-bottom: 6px; }
.date { color: #6b7280; font-size: 12px; margin-bottom: 8px; }
.summary { font-size: 14px; color: #111827; white-space: pre-wrap; word-break: break-word; line-height: 1.5; }
</style>
""",
    unsafe_allow_html=True,
)

def load_articles(base_url: str, q: str, limit: int, offset: int = 0):
    try:
        r = requests.get(
            f"{base_url}/api/articles", params={"limit": limit, "offset": offset, "q": q or ""}, timeout=30
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"加载失败: {e}")
        return []


def render_articles(ph, data):
    cards = []
    for a in data:
        title = html.escape(a.get('title','') or "")
        url = a.get('url','') or ""
        date = html.escape(a.get('published_at','') or "")
        summary = html.escape(a.get('summary') or "")
        cards.append(
            f"<div class='card'><div class='title'><a href='{url}' target='_blank'>{title}</a></div>"
            f"<div class='date'>{date}</div><div class='summary'>{summary}</div></div>"
        )
    ph.markdown("".join(cards), unsafe_allow_html=True)

list_ph = st.empty()

top = st.container()
with top:
    col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
    with col1:
        q = st.text_input("搜索标题", "")
    with col2:
        limit = st.number_input("条数", min_value=1, max_value=200, value=50, step=1)
    with col3:
        max_age_days = st.number_input("最大天数", min_value=0, max_value=90, value=7, step=1)
    with col4:
        base_url = st.text_input("API Base URL", DEFAULT_BASE)
    with col5:
        admin_token = st.text_input("Admin Token", DEFAULT_TOKEN, type="password")
    st.caption("点击“立即抓取”后，下方会实时显示进度，列表将按摘要进度即时更新。")

with st.container():
    if st.button("立即抓取"):
            try:
                # 使用 SSE 流式进度
                with st.spinner("抓取与摘要进行中..."):
                    with requests.get(
                        f"{base_url}/api/refresh/stream",
                        params={"token": admin_token, "max_age_days": int(max_age_days)},
                        stream=True,
                        timeout=300,
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
                                    new_data = load_articles(base_url, q, int(limit))
                                    render_articles(list_ph, new_data)
                        st.success("完成")
                        st.rerun()
            except Exception as e:
                st.error(f"请求错误: {e}")

data = load_articles(base_url, q, int(limit), 0)
render_articles(list_ph, data)

# 简单“加载更多”
more_col = st.container()
if st.button("加载更多"):
    current = len(data)
    more = load_articles(base_url, q, int(limit), current)
    data = data + more
    render_articles(list_ph, data)


