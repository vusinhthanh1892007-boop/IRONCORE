---
name: ironcore-crypto
description: Get real-time cryptocurrency prices, market cap, and 24h change. Free via CoinGecko — no API key needed.
metadata: {"openclaw": {"emoji": "₿", "requires": {"bins": ["python3"]}}}
---

# IronCore Crypto Price

Fetch live crypto prices from CoinGecko's free public API. No API key required.

## When to use
Trigger when the user asks about Bitcoin, Ethereum, altcoin prices, market data, crypto portfolio, or "how much is X worth".

## Supported coins (CoinGecko IDs)
Common ones: `bitcoin`, `ethereum`, `solana`, `tether`, `binancecoin`, `ripple`, `cardano`, `dogecoin`, `polkadot`, `chainlink`, `avalanche-2`, `matic-network`, `uniswap`, `litecoin`, `monero`

## How to run

```python
python3 -c "
import urllib.request, json, sys

coins = 'bitcoin,ethereum,solana'  # REPLACE with requested coins
currency = 'usd'                    # REPLACE with user's preferred currency

url = f'https://api.coingecko.com/api/v3/simple/price?ids={coins}&vs_currencies={currency}&include_24hr_change=true&include_market_cap=true'
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.load(r)
    print(f'=== Crypto Prices ({currency.upper()}) ===')
    for coin, info in data.items():
        price = info.get(currency, 'N/A')
        change = info.get(f'{currency}_24h_change', 0)
        mcap = info.get(f'{currency}_market_cap', 0)
        arrow = '▲' if change >= 0 else '▼'
        print(f'{coin.upper():12} \${price:>14,.2f}  {arrow} {abs(change):.2f}%  MCap: \${mcap:>18,.0f}')
except Exception as e:
    print(f'Error: {e}. CoinGecko may be rate-limiting — wait 60s and retry.')
"
```

## Steps
1. Parse which coins the user wants (convert common names to CoinGecko IDs if needed: BTC→bitcoin, ETH→ethereum, etc.)
2. Determine which currency (default USD, support EUR/VND/JPY/GBP etc.)
3. Run the command above with the appropriate coin list and currency
4. Present results in a clean table with price, 24h change direction, and market cap

## Rate limits
CoinGecko free tier: 10–30 requests/minute. If you hit a rate limit, wait 60 seconds and retry.
