"""
IronCore Tool: crypto_price
============================
Fetch real-time cryptocurrency prices and market data using
the CoinGecko API (free tier, no API key required).
"""

from __future__ import annotations

import logging

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)


@skill(
    name="crypto_price",
    version="1.0.0",
    description="Get real-time crypto prices and market data from CoinGecko. Free, no API key needed.",
    author="brain",
    tags=["crypto", "bitcoin", "price", "finance", "api", "free"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="coins",
            type="string",
            description="Comma-separated list of coin IDs (CoinGecko IDs, e.g. 'bitcoin,ethereum,solana')",
            required=True,
        ),
        SkillParameterSchema(
            name="currency",
            type="string",
            description="Target currency for price conversion (e.g. 'usd', 'eur', 'vnd', 'jpy')",
            required=False,
            default="usd",
        ),
        SkillParameterSchema(
            name="include_24h_change",
            type="bool",
            description="Include 24-hour price change percentage",
            required=False,
            default=True,
        ),
        SkillParameterSchema(
            name="include_market_cap",
            type="bool",
            description="Include market capitalization",
            required=False,
            default=False,
        ),
    ],
)
async def crypto_price(
    coins: str,
    currency: str = "usd",
    include_24h_change: bool = True,
    include_market_cap: bool = False,
) -> dict:
    """Fetch cryptocurrency prices from CoinGecko API."""
    import httpx

    # Normalize inputs
    coin_list = [c.strip().lower() for c in coins.split(",") if c.strip()]
    if not coin_list:
        return {"error": "No coin IDs provided"}
    if len(coin_list) > 20:
        return {"error": "Too many coins requested (max 20)"}

    currency = currency.strip().lower()
    ids_param = ",".join(coin_list)

    params: dict = {
        "ids": ids_param,
        "vs_currencies": currency,
        "include_24hr_change": str(include_24h_change).lower(),
        "include_market_cap": str(include_market_cap).lower(),
        "include_last_updated_at": "true",
    }

    url = "https://api.coingecko.com/api/v3/simple/price"

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "IronCore-Agent/1.0", "Accept": "application/json"},
        ) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                return {"error": "CoinGecko rate limit reached. Try again in 60 seconds."}
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return {"error": f"CoinGecko API error: {exc.response.status_code}"}
    except Exception as exc:
        logger.warning("crypto_price failed: %s", exc)
        return {"error": str(exc)}

    if not data:
        return {"error": "No price data returned. Check the coin IDs (use CoinGecko IDs like 'bitcoin', not 'BTC')."}

    results = {}
    for coin_id, price_data in data.items():
        entry: dict = {
            "price": price_data.get(currency),
            "currency": currency.upper(),
        }
        change_key = f"{currency}_24h_change"
        if include_24h_change and change_key in price_data:
            entry["change_24h_pct"] = round(price_data[change_key], 2)
        mcap_key = f"{currency}_market_cap"
        if include_market_cap and mcap_key in price_data:
            entry["market_cap"] = price_data.get(mcap_key)
        if "last_updated_at" in price_data:
            entry["last_updated_unix"] = price_data["last_updated_at"]
        results[coin_id] = entry

    # Report coins that were not found
    missing = [c for c in coin_list if c not in results]

    return {
        "prices": results,
        "currency": currency.upper(),
        "coins_not_found": missing,
        "source": "coingecko.com",
    }
