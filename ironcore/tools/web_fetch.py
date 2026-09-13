"""
IronCore Tool: Web Fetch
========================
Fetch and extract content from web pages.
Supports: raw HTML, cleaned text (readability), or Markdown conversion.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)

_MAX_BODY_SIZE = 512 * 1024  # 512 KB limit for returned content


def _html_to_text(html: str) -> str:
    """Lightweight HTML→text extraction (no external dependency)."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _html_to_markdown(html: str) -> str:
    """Convert HTML to basic Markdown."""
    md = html
    # Headers
    for i in range(1, 7):
        md = re.sub(rf"<h{i}[^>]*>(.*?)</h{i}>", rf"{'#' * i} \1\n\n", md, flags=re.DOTALL | re.IGNORECASE)
    # Bold / italic
    md = re.sub(r"<(strong|b)>(.*?)</\1>", r"**\2**", md, flags=re.DOTALL | re.IGNORECASE)
    md = re.sub(r"<(em|i)>(.*?)</\1>", r"*\2*", md, flags=re.DOTALL | re.IGNORECASE)
    # Links
    md = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r"[\2](\1)", md, flags=re.DOTALL | re.IGNORECASE)
    # Lists
    md = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", md, flags=re.DOTALL | re.IGNORECASE)
    # Paragraphs
    md = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", md, flags=re.DOTALL | re.IGNORECASE)
    # Line breaks
    md = re.sub(r"<br\s*/?>", "\n", md, flags=re.IGNORECASE)
    # Remove script/style
    md = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", md, flags=re.DOTALL | re.IGNORECASE)
    # Remove remaining tags
    md = re.sub(r"<[^>]+>", "", md)
    # Collapse blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


@skill(
    name="web_fetch",
    version="1.0.0",
    description="Fetch content from a URL. Returns text, HTML, or Markdown.",
    long_description="Download a web page and extract its content in the requested format.",
    author="brain",
    tags=["web", "fetch", "scrape"],
    risk_level=RiskLevel.MEDIUM,
    requires_network=True,
    estimated_latency_ms=3000.0,
    cost_tier="free",
    parameters=[
        SkillParameterSchema(name="url", type="string", description="URL to fetch", required=True),
        SkillParameterSchema(
            name="format",
            type="string",
            description="Output format: 'text', 'html', or 'markdown'",
            required=False,
            default="text",
            enum_values=["text", "html", "markdown"],
        ),
        SkillParameterSchema(name="max_length", type="int", description="Maximum content length in characters", required=False, default=50000),
    ],
)
async def web_fetch(url: str, format: str = "text", max_length: int = 50000) -> str:
    """Fetch a URL and return its content."""
    if not url.startswith(("http://", "https://")):
        return json.dumps({"error": "URL must start with http:// or https://"})

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; IronCore/1.0; +https://ironcore.dev)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, max_redirects=5) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            raw = resp.text[:_MAX_BODY_SIZE]

            if "text/html" in content_type or "application/xhtml" in content_type:
                if format == "html":
                    content = raw
                elif format == "markdown":
                    content = _html_to_markdown(raw)
                else:
                    content = _html_to_text(raw)
            else:
                content = raw

            content = content[:max_length]

            return json.dumps({
                "url": str(resp.url),
                "status_code": resp.status_code,
                "content_type": content_type,
                "length": len(content),
                "content": content,
            }, ensure_ascii=False)

    except httpx.HTTPStatusError as exc:
        return json.dumps({"error": f"HTTP {exc.response.status_code}: {exc.response.reason_phrase}", "url": url})
    except Exception as exc:
        return json.dumps({"error": str(exc), "url": url})
