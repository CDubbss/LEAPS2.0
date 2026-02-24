"""
yfinance-based options data client.
All options chain data, quotes, news, and IV history come from here.
Greeks are NOT provided by yfinance — they are computed by greeks_calculator.py.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Optional

import pandas as pd
import yfinance as yf

from backend.models.options import OptionQuote, OptionType, OptionsChain
from backend.models.sentiment import NewsArticle
from backend.scanner.greeks_calculator import compute_greeks

logger = logging.getLogger(__name__)

# Thread pool for yfinance (synchronous library, must not block async loop)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="yfinance")

RISK_FREE_RATE = 0.05  # approximate 3-month T-bill rate


def _run_sync(fn, *args):
    """Run a synchronous function in the thread pool."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn, *args)


class YFinanceClient:
    """
    Async wrapper around the synchronous yfinance library.
    All public methods are async; blocking yfinance calls run in a thread pool.
    """

    async def get_quote(self, symbol: str) -> dict:
        """Fetch real-time spot price + 52-week high/low."""

        def _fetch():
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            return {
                "symbol": symbol,
                "price": float(info.last_price or 0),
                "fifty_two_week_high": float(info.year_high or 0),
                "fifty_two_week_low": float(info.year_low or 0),
                "previous_close": float(info.previous_close or 0),
            }

        return await _run_sync(_fetch)

    async def get_expirations(self, symbol: str) -> list[str]:
        """Return all available expiration date strings for a symbol."""

        def _fetch():
            return list(yf.Ticker(symbol).options)

        return await _run_sync(_fetch)

    async def get_options_chain(
        self, symbol: str, expiration: str, spot_price: float
    ) -> tuple[list[OptionQuote], list[OptionQuote]]:
        """
        Fetch options chain for a given expiration.
        Returns (calls, puts) as lists of OptionQuote with computed greeks.
        """

        def _fetch():
            return yf.Ticker(symbol).option_chain(expiration)

        chain = await _run_sync(_fetch)

        exp_date = date.fromisoformat(expiration)
        dte = (exp_date - date.today()).days
        T = max(dte / 365.0, 1 / 365.0)  # at least 1 day to avoid div/0

        calls = self._normalize_df(
            chain.calls, symbol, exp_date, OptionType.CALL, spot_price, T
        )
        puts = self._normalize_df(
            chain.puts, symbol, exp_date, OptionType.PUT, spot_price, T
        )
        return calls, puts

    def _normalize_df(
        self,
        df: pd.DataFrame,
        underlying: str,
        expiration: date,
        option_type: OptionType,
        spot_price: float,
        T: float,
    ) -> list[OptionQuote]:
        quotes = []
        for _, row in df.iterrows():
            try:
                iv = float(row.get("impliedVolatility", 0) or 0)
                strike = float(row.get("strike", 0) or 0)
                bid = float(row.get("bid", 0) or 0)
                ask = float(row.get("ask", 0) or 0)
                mid = round((bid + ask) / 2, 4)
                volume = int(row.get("volume", 0) or 0)
                oi = int(row.get("openInterest", 0) or 0)
                last = float(row.get("lastPrice", mid) or mid)

                # Compute greeks via Black-Scholes
                greeks = compute_greeks(
                    S=spot_price,
                    K=strike,
                    T=T,
                    r=RISK_FREE_RATE,
                    sigma=iv,
                    option_type=option_type.value,
                )

                # Build contract symbol if not present
                symbol = str(row.get("contractSymbol", f"{underlying}_opt"))

                quotes.append(
                    OptionQuote(
                        symbol=symbol,
                        underlying=underlying,
                        expiration=expiration,
                        strike=strike,
                        option_type=option_type,
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        last=last,
                        volume=volume,
                        open_interest=oi,
                        implied_volatility=iv,
                        delta=greeks["delta"],
                        gamma=greeks["gamma"],
                        theta=greeks["theta"],
                        vega=greeks["vega"],
                        rho=greeks["rho"],
                    )
                )
            except Exception as e:
                logger.debug("Skipping bad option row: %s", e)
                continue
        return quotes

    async def get_full_chain(self, symbol: str, expiration: str) -> OptionsChain:
        """Build a complete OptionsChain including spot price."""
        quote = await self.get_quote(symbol)
        spot = quote["price"]
        calls, puts = await self.get_options_chain(symbol, expiration, spot)
        exp_date = date.fromisoformat(expiration)
        return OptionsChain(
            underlying=symbol,
            spot_price=spot,
            quote_time=datetime.utcnow().isoformat(),
            expirations=[exp_date],
            calls=calls,
            puts=puts,
        )

    async def get_news(self, symbol: str) -> list[NewsArticle]:
        """Fetch recent news articles for a ticker via yfinance."""

        def _fetch():
            return yf.Ticker(symbol).news or []

        raw = await _run_sync(_fetch)
        articles = []
        for item in raw[:20]:  # cap at 20 articles
            try:
                # yfinance ≥1.1 nests content under item["content"]
                c = item.get("content", item)
                title = c.get("title", "")
                if not title:
                    continue
                url = (c.get("canonicalUrl") or {}).get("url", "") or (
                    c.get("clickThroughUrl") or {}).get("url", "")
                source = (c.get("provider") or {}).get("displayName", "")
                pub_date = c.get("pubDate", "") or c.get("displayTime", "")
                articles.append(
                    NewsArticle(
                        title=title,
                        description=c.get("summary", "") or c.get("description", ""),
                        url=url,
                        published_at=pub_date,
                        source=source,
                    )
                )
            except Exception:
                continue
        return articles

    async def get_historical_iv(self, symbol: str) -> dict[str, float]:
        """
        Approximate 52-week IV range by pulling 1 year of daily historical
        closing prices and computing 30-day rolling HV as IV proxy.
        Returns: {"current_iv": ..., "iv_52w_high": ..., "iv_52w_low": ...}
        """

        def _fetch():
            hist = yf.Ticker(symbol).history(period="1y", interval="1d")
            return hist["Close"]

        closes = await _run_sync(_fetch)
        if closes is None or len(closes) < 30:
            return {"current_iv": 0.3, "iv_52w_high": 0.6, "iv_52w_low": 0.15}

        # Compute 30-day rolling annualized HV
        log_returns = closes.pct_change().dropna()
        rolling_hv = log_returns.rolling(window=30).std() * (252**0.5)
        rolling_hv = rolling_hv.dropna()

        current_iv = float(rolling_hv.iloc[-1]) if len(rolling_hv) > 0 else 0.3
        iv_52w_high = float(rolling_hv.max()) if len(rolling_hv) > 0 else 0.6
        iv_52w_low = float(rolling_hv.min()) if len(rolling_hv) > 0 else 0.15

        return {
            "current_iv": current_iv,
            "iv_52w_high": max(iv_52w_high, current_iv + 0.01),
            "iv_52w_low": min(iv_52w_low, current_iv - 0.01),
        }

    async def compute_iv_rank(self, symbol: str, current_iv: Optional[float] = None) -> float:
        """
        Compute IV Rank (0-100).
        IV Rank = (current_iv - 52w_low) / (52w_high - 52w_low) * 100
        """
        iv_data = await self.get_historical_iv(symbol)
        iv = current_iv if current_iv is not None else iv_data["current_iv"]
        high = iv_data["iv_52w_high"]
        low = iv_data["iv_52w_low"]
        if high == low:
            return 50.0
        rank = (iv - low) / (high - low) * 100
        return float(max(0.0, min(100.0, rank)))

    async def get_historical_volatility(self, symbol: str, days: int = 30) -> float:
        """Compute N-day historical volatility (annualized)."""

        def _fetch():
            hist = yf.Ticker(symbol).history(period=f"{days * 2}d", interval="1d")
            return hist["Close"]

        closes = await _run_sync(_fetch)
        if closes is None or len(closes) < days:
            return 0.3
        log_returns = closes.pct_change().dropna().iloc[-days:]
        hv = float(log_returns.std() * (252**0.5))
        return hv if hv > 0 else 0.3
