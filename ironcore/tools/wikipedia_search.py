"""
IronCore Tool: wikipedia_search
================================
Search and extract content from Wikipedia using the free MediaWiki API.
No API key required. Inspired by LangChain's WikipediaQueryRun tool.
"""

from __future__ import annotations

import logging

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)


@skill(
    name="wikipedia_search",
    version="1.0.0",
    description="Search Wikipedia and extract article summaries or full sections. Free, no API key.",
    author="brain",
    tags=["wikipedia", "knowledge", "search", "encyclopedia", "free"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="query",
            type="string",
            description="Search topic or article title (e.g. 'Python programming language', 'Eiffel Tower')",
            required=True,
        ),
        SkillParameterSchema(
            name="sentences",
            type="int",
            description="Number of summary sentences to return (1-10). Use 0 to get the full intro section.",
            required=False,
            default=5,
        ),
        SkillParameterSchema(
            name="lang",
            type="string",
            description="Wikipedia language code (e.g. 'en', 'vi', 'ja', 'fr', 'de', 'zh')",
            required=False,
            default="en",
        ),
    ],
)
async def wikipedia_search(
    query: str,
    sentences: int = 5,
    lang: str = "en",
) -> dict:
    """Search Wikipedia using the MediaWiki REST API."""
    import httpx

    lang = lang.strip().lower() or "en"
    sentences = max(0, min(10, int(sentences)))

    # Step 1: Search for matching article title
    search_url = f"https://{lang}.wikipedia.org/w/api.php"
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": 3,
        "format": "json",
        "utf8": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": "IronCore-Agent/1.0"}) as client:
            search_resp = await client.get(search_url, params=search_params)
            search_resp.raise_for_status()
            search_data = search_resp.json()
    except Exception as exc:
        logger.warning("wikipedia_search query failed: %s", exc)
        return {"error": str(exc)}

    results = search_data.get("query", {}).get("search", [])
    if not results:
        return {"error": f"No Wikipedia articles found for '{query}'"}

    # Use the top result's page title
    top_title = results[0]["title"]

    # Step 2: Fetch the article extract
    extract_params = {
        "action": "query",
        "prop": "extracts|info",
        "titles": top_title,
        "exintro": True,        # Only intro section
        "explaintext": True,    # Plain text (no HTML)
        "inprop": "url",
        "format": "json",
        "utf8": 1,
    }
    if sentences > 0:
        extract_params["exsentences"] = sentences

    try:
        async with httpx.AsyncClient(timeout=12.0, headers={"User-Agent": "IronCore-Agent/1.0"}) as client:
            extract_resp = await client.get(search_url, params=extract_params)
            extract_resp.raise_for_status()
            extract_data = extract_resp.json()
    except Exception as exc:
        return {"error": f"Failed to fetch article content: {exc}"}

    pages = extract_data.get("query", {}).get("pages", {})
    if not pages:
        return {"error": "No article content found"}

    page = next(iter(pages.values()))
    if "missing" in page:
        return {"error": f"Wikipedia article '{top_title}' does not exist"}

    article_url = page.get("fullurl", f"https://{lang}.wikipedia.org/wiki/{top_title.replace(' ', '_')}")
    extract_text = page.get("extract", "").strip()

    # Also list the other search results as suggestions
    suggestions = [r["title"] for r in results[1:3]]

    return {
        "title": top_title,
        "summary": extract_text,
        "url": article_url,
        "language": lang,
        "other_matches": suggestions,
    }
