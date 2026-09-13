"""
IronCore Tool: github_search
=============================
Search GitHub repositories, issues, and code using the GitHub REST API.
Works without authentication for public content (60 requests/hour).
Pass GITHUB_TOKEN env var for 5000 requests/hour.
"""

from __future__ import annotations

import logging
import os

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)


@skill(
    name="github_search",
    version="1.0.0",
    description="Search GitHub repositories, issues, or code. No API key required for public content.",
    author="brain",
    tags=["github", "search", "code", "repositories", "api"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="query",
            type="string",
            description="Search query (supports GitHub search syntax, e.g. 'fastapi stars:>1000 language:python')",
            required=True,
        ),
        SkillParameterSchema(
            name="search_type",
            type="string",
            description="What to search: 'repositories', 'issues', 'code', 'users'",
            required=False,
            default="repositories",
        ),
        SkillParameterSchema(
            name="sort",
            type="string",
            description="Sort by: 'stars', 'forks', 'updated', 'best-match'",
            required=False,
            default="best-match",
        ),
        SkillParameterSchema(
            name="max_results",
            type="int",
            description="Maximum number of results to return (1-30)",
            required=False,
            default=10,
        ),
    ],
)
async def github_search(
    query: str,
    search_type: str = "repositories",
    sort: str = "best-match",
    max_results: int = 10,
) -> dict:
    """Search GitHub using the REST API."""
    import httpx

    # Validate inputs
    valid_types = {"repositories", "issues", "code", "users"}
    if search_type not in valid_types:
        search_type = "repositories"

    max_results = max(1, min(30, int(max_results)))

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "IronCore-Agent/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params: dict = {"q": query, "per_page": max_results}
    if sort != "best-match":
        params["sort"] = sort

    url = f"https://api.github.com/search/{search_type}"

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            return {"error": "GitHub rate limit reached. Set GITHUB_TOKEN env var for more requests."}
        if exc.response.status_code == 422:
            return {"error": f"Invalid search query: {query}"}
        return {"error": f"GitHub API error: {exc.response.status_code}"}
    except Exception as exc:
        logger.warning("github_search failed: %s", exc)
        return {"error": str(exc)}

    items = data.get("items", [])
    total = data.get("total_count", 0)

    def _format_repo(item: dict) -> dict:
        return {
            "name": item.get("full_name", ""),
            "description": item.get("description") or "",
            "url": item.get("html_url", ""),
            "stars": item.get("stargazers_count", 0),
            "forks": item.get("forks_count", 0),
            "language": item.get("language") or "Unknown",
            "updated": item.get("updated_at", ""),
            "topics": item.get("topics", [])[:5],
        }

    def _format_issue(item: dict) -> dict:
        return {
            "title": item.get("title", ""),
            "url": item.get("html_url", ""),
            "state": item.get("state", ""),
            "repo": item.get("repository_url", "").split("repos/")[-1],
            "created": item.get("created_at", ""),
            "author": item.get("user", {}).get("login", ""),
        }

    def _format_code(item: dict) -> dict:
        return {
            "name": item.get("name", ""),
            "path": item.get("path", ""),
            "url": item.get("html_url", ""),
            "repo": item.get("repository", {}).get("full_name", ""),
        }

    def _format_user(item: dict) -> dict:
        return {
            "login": item.get("login", ""),
            "url": item.get("html_url", ""),
            "type": item.get("type", ""),
        }

    formatters = {
        "repositories": _format_repo,
        "issues": _format_issue,
        "code": _format_code,
        "users": _format_user,
    }
    fmt = formatters.get(search_type, _format_repo)

    return {
        "query": query,
        "search_type": search_type,
        "total_count": total,
        "results": [fmt(item) for item in items],
        "rate_limited": not bool(token),
    }
