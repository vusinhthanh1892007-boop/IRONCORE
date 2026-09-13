"""
IronCore Tool: currency_convert
================================
Convert between currencies using the free ExchangeRate-API (v6) or
Open Exchange Rates. Falls back to frankfurter.app (ECB rates, free, no key).
"""

from __future__ import annotations

import logging
import os

from ironcore.core.engine import RiskLevel
from ironcore.skills.registry import SkillParameterSchema, skill

logger = logging.getLogger(__name__)


@skill(
    name="currency_convert",
    version="1.0.0",
    description="Convert between currencies using live exchange rates. Free via frankfurter.app (ECB rates) or ExchangeRate-API.",
    author="brain",
    tags=["currency", "exchange", "finance", "conversion", "free"],
    risk_level=RiskLevel.LOW,
    requires_network=True,
    parameters=[
        SkillParameterSchema(
            name="amount",
            type="float",
            description="Amount to convert (e.g. 100.0)",
            required=True,
        ),
        SkillParameterSchema(
            name="from_currency",
            type="string",
            description="Source currency ISO code (e.g. 'USD', 'EUR', 'VND', 'JPY')",
            required=True,
        ),
        SkillParameterSchema(
            name="to_currency",
            type="string",
            description="Target currency ISO code (e.g. 'USD', 'EUR', 'VND', 'GBP')",
            required=True,
        ),
        SkillParameterSchema(
            name="to_currencies",
            type="string",
            description="Comma-separated list of additional target currencies for bulk conversion (e.g. 'EUR,GBP,JPY'). Optional.",
            required=False,
            default="",
        ),
    ],
)
async def currency_convert(
    amount: float,
    from_currency: str,
    to_currency: str,
    to_currencies: str = "",
) -> dict:
    """Convert currency using live rates from frankfurter.app (ECB) or ExchangeRate-API."""
    import httpx

    amount = float(amount)
    from_code = from_currency.strip().upper()
    to_code = to_currency.strip().upper()

    # Build full list of target currencies
    extra = [c.strip().upper() for c in to_currencies.split(",") if c.strip()]
    all_targets = list(dict.fromkeys([to_code] + extra))  # deduplicate, keep order

    # Try ExchangeRate-API first if key is available
    api_key = os.environ.get("EXCHANGERATE_API_KEY")
    if api_key:
        result = await _exchangerate_api(api_key, amount, from_code, all_targets)
        if "error" not in result:
            return result

    # Fallback: frankfurter.app (European Central Bank rates, free, no key)
    return await _frankfurter(amount, from_code, all_targets)


async def _frankfurter(amount: float, from_code: str, to_codes: list[str]) -> dict:
    """Use frankfurter.app (ECB daily reference rates)."""
    import httpx

    to_param = ",".join(to_codes)
    params = {
        "amount": amount,
        "from": from_code,
        "to": to_param,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://api.frankfurter.app/latest", params=params)
            if resp.status_code == 404:
                return {
                    "error": f"Currency not supported. Frankfurter.app supports major currencies only. "
                             f"Unsupported: '{from_code}' or '{to_param}'"
                }
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("frankfurter currency_convert failed: %s", exc)
        return {"error": str(exc)}

    rates = data.get("rates", {})
    if not rates:
        return {"error": f"No exchange rate data for {from_code} → {to_param}"}

    conversions = {}
    for code, rate in rates.items():
        conversions[code] = {
            "rate": rate,
            "result": round(amount * rate, 4) if rate else None,
        }

    primary_code = to_codes[0]
    primary = conversions.get(primary_code, {})

    return {
        "from": from_code,
        "amount": amount,
        "primary_result": primary.get("result"),
        "primary_currency": primary_code,
        "rate": primary.get("rate"),
        "all_conversions": conversions,
        "date": data.get("date"),
        "source": "frankfurter.app (ECB reference rates)",
    }


async def _exchangerate_api(api_key: str, amount: float, from_code: str, to_codes: list[str]) -> dict:
    """Use ExchangeRate-API v6."""
    import httpx

    url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{from_code}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code in (401, 403):
                return {"error": "Invalid ExchangeRate-API key"}
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"error": str(exc)}

    if data.get("result") != "success":
        return {"error": data.get("error-type", "ExchangeRate-API error")}

    conversion_rates = data.get("conversion_rates", {})
    conversions = {}
    for code in to_codes:
        rate = conversion_rates.get(code)
        if rate:
            conversions[code] = {"rate": rate, "result": round(amount * rate, 4)}
        else:
            conversions[code] = {"error": f"Unsupported currency: {code}"}

    primary_code = to_codes[0]
    primary = conversions.get(primary_code, {})

    return {
        "from": from_code,
        "amount": amount,
        "primary_result": primary.get("result"),
        "primary_currency": primary_code,
        "rate": primary.get("rate"),
        "all_conversions": conversions,
        "date": data.get("time_last_update_utc", ""),
        "source": "exchangerate-api.com",
    }
