ARXIV_FEEDS = [
    # Prefer arxiv.org RSS (some networks block export.*)
    "https://arxiv.org/rss/cs.AI",
]

NEWS_FEEDS = [
    "https://bair.berkeley.edu/blog/feed.xml",
    "https://feeds.feedburner.com/nvidiablog",
    "https://www.microsoft.com/en-us/research/feed/",
    "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",
    "https://research.facebook.com/feed/",
    "https://openai.com/news/rss.xml",
    "https://deepmind.google/blog/feed/basic/",
    "https://news.mit.edu/rss/topic/artificial-intelligence2",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "https://www.wired.com/feed/tag/ai/latest/rss",
    "https://raw.githubusercontent.com/Olshansk/rss-feeds/refs/heads/main/feeds/feed_ollama.xml",
    "https://raw.githubusercontent.com/Olshansk/rss-feeds/refs/heads/main/feeds/feed_anthropic.xml",
]

# Back-compat
DEFAULT_RSS_SOURCES = ARXIV_FEEDS + NEWS_FEEDS
