"""
IronCore Tool: news_fetch
==========================
Fetch latest news from multiple free sources:
 - HackerNews (Algolia API) — tech news, no key needed
 - NewsData.io — broad news, free tier (NEWSDATA_API_KEY env var)
Falls back to HackerNews when no API key is configured.
"""

from __future__ import annotations

import logging
import os

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)


@skill(
    name="news_fetch",
    version="1.0.0",
    description="Fetch latest news headlines. Uses HackerNews (free) or NewsData.io (free tier with API key).",
    author="brain",
    tags=["news", "headlines", "api", "realtime", "hackernews"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="query",
            type="string",
            description="Topic or keyword to search for (e.g. 'AI', 'Python', 'startup')",
            required=False,
            default="",
        ),
        SkillParameterSchema(
            name="source",
            type="string",
            description="News source: 'hackernews' (free) or 'newsdata' (requires NEWSDATA_API_KEY)",
            required=False,
            default="hackernews",
        ),
        SkillParameterSchema(
            name="max_results",
            type="int",
            description="Number of articles to return (1-20)",
            required=False,
            default=10,
        ),
        SkillParameterSchema(
            name="category",
            type="string",
            description="For HackerNews: 'top', 'new', 'best', 'show', 'ask'. For NewsData: 'technology', 'business', etc.",
            required=False,
            default="top",
        ),
    ],
)
async def news_fetch(
    query: str = "",
    source: str = "hackernews",
    max_results: int = 10,
    category: str = "top",
) -> dict:
    """Fetch news from HackerNews or NewsData.io."""
    import httpx

    max_results = max(1, min(20, int(max_results)))

    if source == "newsdata" and os.environ.get("NEWSDATA_API_KEY"):
        return await _fetch_newsdata(query, max_results, category)
    return await _fetch_hackernews(query, max_results, category)


async def _fetch_hackernews(query: str, max_results: int, category: str) -> dict:
    """Fetch from HackerNews Algolia API."""
    import httpx

    # Category → HN endpoint tag
    hn_tags = {"top": "front_page", "new": "story", "best": "story", "show": "show_hn", "ask": "ask_hn"}
    tag = hn_tags.get(category, "front_page")

    if query:
        url = "https://hn.algolia.com/api/v1/search"
        params: dict = {"query": query, "tags": tag, "hitsPerPage": max_results}
    else:
        # Top stories
        url = "https://hn.algolia.com/api/v1/search"
        params = {"tags": tag, "hitsPerPage": max_results}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("hackernews fetch failed: %s", exc)
        return {"error": str(exc), "source": "hackernews"}

    articles = []
    for hit in data.get("hits", []):
        title = hit.get("title") or hit.get("story_title", "")
        story_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
        articles.append({
            "title": title,
            "url": story_url,
            "hn_url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
            "score": hit.get("points", 0),
            "comments": hit.get("num_comments", 0),
            "author": hit.get("author", ""),
            "time": hit.get("created_at", ""),
        })

    return {
        "source": "hackernews",
        "query": query or f"[{category} stories]",
        "total": data.get("nbHits", len(articles)),
        "articles": articles,
    }


async def _fetch_newsdata(query: str, max_results: int, category: str) -> dict:
    """Fetch from NewsData.io free tier."""
    import httpx

    api_key = os.environ.get("NEWSDATA_API_KEY", "")
    params: dict = {
        "apikey": api_key,
        "language": "en",
        "size": min(max_results, 10),  # free tier max 10
    }
    if query:
        params["q"] = query
    if category and category not in ("top", "new", "best"):
        params["category"] = category

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://newsdata.io/api/1/news", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("newsdata fetch failed: %s", exc)
        return {"error": str(exc), "source": "newsdata"}

    if data.get("status") != "success":
        return {"error": data.get("message", "NewsData API error"), "source": "newsdata"}

    articles = []
    for item in data.get("results", []):
        articles.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": (item.get("description") or "")[:200],
            "source": item.get("source_id", ""),
            "published": item.get("pubDate", ""),
            "categories": item.get("category", []),
        })

    return {
        "source": "newsdata.io",
        "query": query,
        "total": data.get("totalResults", len(articles)),
        "articles": articles,
    }
