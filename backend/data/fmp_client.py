"""
Financial Modeling Prep (FMP) client for company fundamentals.
Uses the stable API (https://financialmodelingprep.com/stable/) as of 2025.
User has an FMP API key. Free tier = 250 calls/day.
Redis caching at 24h TTL keeps usage well within limits.
"""

import asyncio
import logging
from datetime import date
from typing import Any, Optional

import yfinance as yf

from backend.data.base_client import BaseAPIClient
from backend.models.fundamentals import FundamentalData

logger = logging.getLogger(__name__)


def _fetch_yf_debt_to_equity(symbol: str) -> Optional[float]:
    """
    Fallback: fetch debtToEquity from yfinance ticker.info.
    Yahoo Finance reports this as a percentage (e.g. 45.2 = 45.2%),
    so divide by 100 to match FMP's decimal ratio format.
    Returns None if unavailable or on any error.
    """
    try:
        info = yf.Ticker(symbol).info
        val = info.get("debtToEquity")
        if val is None:
            return None
        ratio = float(val) / 100.0
        return ratio if ratio >= 0 else None
    except Exception as e:
        logger.debug("yfinance debtToEquity fallback failed %s: %s", symbol, e)
        return None


def _fetch_yf_next_earnings_date(symbol: str) -> Optional[date]:
    """
    Fallback: fetch the next upcoming earnings date from yfinance.
    Tries ticker.calendar first, then get_earnings_dates().
    Returns None on any failure or if no future date is available.
    """
    today = date.today()
    try:
        ticker = yf.Ticker(symbol)

        # Attempt 1: calendar dict (yfinance >= 0.2)
        try:
            cal = ticker.calendar
            if isinstance(cal, dict):
                for d in cal.get("Earnings Date", []):
                    d = d.date() if hasattr(d, "date") else d
                    if d >= today:
                        return d
        except Exception:
            pass

        # Attempt 2: get_earnings_dates DataFrame
        try:
            import pandas as pd
            df = ticker.get_earnings_dates(limit=8)
            if df is not None and not df.empty:
                future = sorted(
                    idx.date() for idx in df.index if idx.date() >= today
                )
                if future:
                    return future[0]
        except Exception:
            pass

    except Exception as e:
        logger.debug("yfinance earnings date fallback failed %s: %s", symbol, e)
    return None


class FMPClient(BaseAPIClient):
    """
    Fetches and normalizes company fundamental data from FMP stable API.

    Key endpoints used (all under /stable/):
      GET /profile               -> company info, market cap
      GET /key-metrics           -> ROE, ROA, FCF yield, current ratio, earnings yield
      GET /income-statement      -> revenue, gross profit, operating income, EPS
      GET /balance-sheet-statement -> total debt, total equity
      GET /earnings              -> next earnings date
    """

    _CALLS_PER_SYMBOL = 5   # profile + metrics + income + balance + earnings
    _DAILY_BUDGET = 240     # leave 10-call buffer from the 250/day free-tier limit

    def __init__(self, api_key: str, base_url: str = "https://financialmodelingprep.com/stable"):
        super().__init__(base_url=base_url, api_key=api_key)
        self._calls_today: int = 0
        self._budget_date: Optional[date] = None

    def _budget_ok(self) -> bool:
        today = date.today()
        if self._budget_date != today:
            self._calls_today = 0
            self._budget_date = today
        return self._calls_today + self._CALLS_PER_SYMBOL <= self._DAILY_BUDGET

    async def get_full_fundamentals(self, symbol: str) -> FundamentalData:
        """
        Fetch and aggregate fundamentals. Requests are sequential to avoid
        hammering FMP rate limits (free tier: 250 calls/day).
        Falls back to empty/default values if any call fails.
        """
        if not self._budget_ok():
            logger.warning(
                "FMP daily budget exhausted (%d/%d calls used) — skipping %s; "
                "fundamentals will be NaN for this symbol",
                self._calls_today, self._DAILY_BUDGET, symbol,
            )
            return FundamentalData(symbol=symbol)

        self._calls_today += self._CALLS_PER_SYMBOL
        base_params = {"symbol": symbol, "apikey": self.api_key}

        async def _safe_get(path, extra=None):
            try:
                return await self._get(path, {**base_params, **(extra or {})})
            except Exception as e:
                logger.debug("FMP %s %s skipped: %s", path, symbol, e)
                return []

        profile_data  = await _safe_get("/profile")
        metrics_data  = await _safe_get("/key-metrics",            {"limit": 1})
        income_data   = await _safe_get("/income-statement",       {"limit": 2})
        balance_data  = await _safe_get("/balance-sheet-statement",{"limit": 1})
        earnings_data = await _safe_get("/earnings",               {"limit": 1})

        # Fallback: if FMP balance sheet unavailable (e.g. 402), fetch D/E from yfinance
        yf_de_ratio: Optional[float] = None
        if not balance_data:
            yf_de_ratio = await asyncio.to_thread(_fetch_yf_debt_to_equity, symbol)
            if yf_de_ratio is not None:
                logger.debug("yfinance D/E fallback for %s: %.3f", symbol, yf_de_ratio)

        # Fallback: if FMP /earnings unavailable (free-tier plan limit), fetch from yfinance.
        # FMP returns a 200 with {"Error Message": "..."} on plan limits — not an exception —
        # so check for a valid non-empty list rather than plain truthiness.
        earnings_valid = isinstance(earnings_data, list) and len(earnings_data) > 0
        yf_next_earnings: Optional[date] = None
        if not earnings_valid:
            yf_next_earnings = await asyncio.to_thread(_fetch_yf_next_earnings_date, symbol)
            if yf_next_earnings is not None:
                logger.debug("yfinance earnings fallback for %s: %s", symbol, yf_next_earnings)

        return self._normalize(
            symbol, profile_data, metrics_data, income_data, balance_data, earnings_data,
            yf_de_ratio=yf_de_ratio,
            yf_next_earnings=yf_next_earnings,
        )

    def _normalize(
        self,
        symbol: str,
        profile_raw: Any,
        metrics_raw: Any,
        income_raw: Any,
        balance_raw: Any,
        earnings_raw: Any,
        yf_de_ratio: Optional[float] = None,
        yf_next_earnings: Optional[date] = None,
    ) -> FundamentalData:
        # FMP stable API returns lists; take first element
        profile = profile_raw[0] if isinstance(profile_raw, list) and profile_raw else {}
        metrics = metrics_raw[0] if isinstance(metrics_raw, list) and metrics_raw else {}
        income_curr = income_raw[0] if isinstance(income_raw, list) and income_raw else {}
        income_prev = income_raw[1] if isinstance(income_raw, list) and len(income_raw) > 1 else {}
        balance = balance_raw[0] if isinstance(balance_raw, list) and balance_raw else {}
        earnings = earnings_raw[0] if isinstance(earnings_raw, list) and earnings_raw else {}

        def safe_float(d: dict, key: str) -> Optional[float]:
            val = d.get(key)
            try:
                return float(val) if val is not None and val != "" else None
            except (TypeError, ValueError):
                return None

        # PE ratio: derive from earningsYield (earningsYield = EPS/Price, so PE = 1/earningsYield)
        earnings_yield = safe_float(metrics, "earningsYield")
        pe_ratio = (1.0 / earnings_yield) if earnings_yield and earnings_yield > 0 else None

        # Revenue growth YoY
        rev_curr = safe_float(income_curr, "revenue")
        rev_prev = safe_float(income_prev, "revenue")
        rev_growth = None
        if rev_curr and rev_prev and rev_prev != 0:
            rev_growth = (rev_curr - rev_prev) / abs(rev_prev)

        # Earnings (EPS) growth YoY
        eps_curr = safe_float(income_curr, "eps")
        eps_prev = safe_float(income_prev, "eps")
        earnings_growth = None
        if eps_curr is not None and eps_prev and eps_prev != 0:
            earnings_growth = (eps_curr - eps_prev) / abs(eps_prev)

        # Gross margin
        gross_profit = safe_float(income_curr, "grossProfit")
        revenue = safe_float(income_curr, "revenue")
        gross_margin = None
        if gross_profit is not None and revenue and revenue != 0:
            gross_margin = gross_profit / revenue

        # Operating margin (not a direct field — compute from income statement)
        operating_income = safe_float(income_curr, "operatingIncome")
        operating_margin = None
        if operating_income is not None and revenue and revenue != 0:
            operating_margin = operating_income / revenue

        # Net margin (compute from income statement)
        net_income = safe_float(income_curr, "netIncome")
        net_margin = None
        if net_income is not None and revenue and revenue != 0:
            net_margin = net_income / revenue

        # Debt-to-equity (totalDebt / totalStockholdersEquity)
        # Falls back to yfinance-sourced value if FMP balance sheet unavailable
        total_debt = safe_float(balance, "totalDebt")
        total_equity = safe_float(balance, "totalStockholdersEquity") or safe_float(balance, "totalEquity")
        debt_to_equity = None
        if total_debt is not None and total_equity and total_equity != 0:
            debt_to_equity = total_debt / abs(total_equity)
        if debt_to_equity is None and yf_de_ratio is not None:
            debt_to_equity = yf_de_ratio

        # Next earnings date — FMP first, yfinance fallback
        next_earnings = None
        days_to_earnings = None
        earnings_date_str = earnings.get("date", "") or earnings.get("reportedDate", "")
        if earnings_date_str:
            try:
                next_earnings = date.fromisoformat(str(earnings_date_str)[:10])
            except ValueError:
                pass
        if next_earnings is None and yf_next_earnings is not None:
            next_earnings = yf_next_earnings
        if next_earnings is not None:
            diff = (next_earnings - date.today()).days
            days_to_earnings = diff if diff >= 0 else None

        return FundamentalData(
            symbol=symbol,
            company_name=profile.get("companyName", ""),
            sector=profile.get("sector", ""),
            industry=profile.get("industry", ""),
            market_cap=safe_float(profile, "marketCap") or 0.0,
            pe_ratio=pe_ratio,
            forward_pe=None,  # not available in stable API without additional endpoint
            peg_ratio=None,   # not available in stable API free tier
            price_to_book=None,  # not available in stable API free tier
            price_to_sales=None,  # not available in stable API free tier
            revenue_growth_yoy=rev_growth,
            earnings_growth_yoy=earnings_growth,
            debt_to_equity=debt_to_equity,
            current_ratio=safe_float(metrics, "currentRatio"),
            gross_margin=gross_margin,
            operating_margin=operating_margin,
            net_margin=net_margin,
            return_on_equity=safe_float(metrics, "returnOnEquity"),
            return_on_assets=safe_float(metrics, "returnOnAssets"),
            free_cash_flow_yield=safe_float(metrics, "freeCashFlowYield"),
            next_earnings_date=next_earnings,
            days_to_earnings=days_to_earnings,
        )
