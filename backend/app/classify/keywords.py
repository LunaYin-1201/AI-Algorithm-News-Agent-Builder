AI_KEYWORDS = {
    "ai","ml","dl","llm","transformer","gpt","bert","diffusion","rl",
    "neural","embedding","prompt","finetune","lora","rag","agent",
    "arxiv","benchmark","dataset","pretrain","foundation model","self-supervised",
    "人工智能","机器学习","深度学习","大模型","神经网络","扩散模型","强化学习","检索增强","微调","算法","论文",
}


def is_ai_related_keywords(title: str, description: str | None) -> bool:
    text = f"{title} {description or ''}".lower()
    return any(k in text for k in AI_KEYWORDS)


