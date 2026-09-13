"""
IronCore Tool: Web Search
=========================
Search the web using multiple provider backends.
Supports: Tavily, SearXNG, DuckDuckGo (fallback).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

import httpx

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_TAVILY_API_URL = "https://api.tavily.com/search"
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"


async def _tavily_search(query: str, max_results: int, api_key: str) -> List[Dict[str, Any]]:
    """Use Tavily API for high-quality search results."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _TAVILY_API_URL,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": True,
                "search_depth": "advanced",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    results = []
    if data.get("answer"):
        results.append({"title": "AI Answer", "url": "", "content": data["answer"]})
    for item in data.get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        })
    return results


async def _searxng_search(query: str, max_results: int, base_url: str) -> List[Dict[str, Any]]:
    """Use a self-hosted SearXNG instance."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{base_url}/search",
            params={"q": query, "format": "json", "pageno": 1},
        )
        resp.raise_for_status()
        data = resp.json()
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in data.get("results", [])[:max_results]
    ]


async def _duckduckgo_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Fallback: lightweight DuckDuckGo instant-answer API."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
        )
        resp.raise_for_status()
        data = resp.json()
    results = []
    if data.get("Abstract"):
        results.append({
            "title": data.get("Heading", "Result"),
            "url": data.get("AbstractURL", ""),
            "content": data["Abstract"],
        })
    for topic in data.get("RelatedTopics", [])[:max_results]:
        if isinstance(topic, dict) and "Text" in topic:
            results.append({
                "title": topic.get("Text", "")[:80],
                "url": topic.get("FirstURL", ""),
                "content": topic.get("Text", ""),
            })
    return results[:max_results]


@skill(
    name="web_search",
    version="1.0.0",
    description="Search the web for real-time information. Returns titles, URLs, and snippets.",
    long_description=(
        "Multi-provider web search tool. Tries Tavily (if API key set), "
        "then SearXNG (if self-hosted URL set), then DuckDuckGo as fallback."
    ),
    author="brain",
    tags=["web", "search", "information"],
    risk_level=RiskLevel.MEDIUM,
    requires_network=True,
    estimated_latency_ms=2000.0,
    cost_tier="cheap",
    parameters=[
        SkillParameterSchema(name="query", type="string", description="Search query", required=True),
        SkillParameterSchema(name="max_results", type="int", description="Maximum number of results (1-20)", required=False, default=5),
    ],
)
async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return structured results."""
    max_results = max(1, min(20, max_results))

    tavily_key = os.environ.get("TAVILY_API_KEY")
    searxng_url = os.environ.get("SEARXNG_URL")

    results: List[Dict[str, Any]] = []
    provider = "none"

    if tavily_key:
        try:
            results = await _tavily_search(query, max_results, tavily_key)
            provider = "tavily"
        except Exception as exc:
            logger.warning("[web_search] Tavily failed: %s", exc)

    if not results and searxng_url:
        try:
            results = await _searxng_search(query, max_results, searxng_url)
            provider = "searxng"
        except Exception as exc:
            logger.warning("[web_search] SearXNG failed: %s", exc)

    if not results:
        try:
            results = await _duckduckgo_search(query, max_results)
            provider = "duckduckgo"
        except Exception as exc:
            logger.warning("[web_search] DuckDuckGo failed: %s", exc)
            return json.dumps({"error": f"All search providers failed. Last: {exc}", "results": []})

    output = {"provider": provider, "query": query, "results": results}
    return json.dumps(output, ensure_ascii=False)
