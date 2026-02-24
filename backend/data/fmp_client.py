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

from backend.data.base_client import BaseAPIClient
from backend.models.fundamentals import FundamentalData

logger = logging.getLogger(__name__)


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

    def __init__(self, api_key: str, base_url: str = "https://financialmodelingprep.com/stable"):
        super().__init__(base_url=base_url, api_key=api_key)

    async def get_full_fundamentals(self, symbol: str) -> FundamentalData:
        """
        Fetch and aggregate fundamentals. All FMP calls run concurrently.
        Falls back to empty/default values if any call fails.
        """
        try:
            base_params = {"symbol": symbol, "apikey": self.api_key}

            profile_task = self._get("/profile", base_params)
            metrics_task = self._get("/key-metrics", {**base_params, "limit": 1})
            income_task = self._get("/income-statement", {**base_params, "limit": 2})
            balance_task = self._get("/balance-sheet-statement", {**base_params, "limit": 1})
            earnings_task = self._get("/earnings", {**base_params, "limit": 1})

            results = await asyncio.gather(
                profile_task,
                metrics_task,
                income_task,
                balance_task,
                earnings_task,
                return_exceptions=True,
            )

            profile_data = results[0] if not isinstance(results[0], Exception) else []
            metrics_data = results[1] if not isinstance(results[1], Exception) else []
            income_data = results[2] if not isinstance(results[2], Exception) else []
            balance_data = results[3] if not isinstance(results[3], Exception) else []
            earnings_data = results[4] if not isinstance(results[4], Exception) else []

            return self._normalize(
                symbol, profile_data, metrics_data, income_data, balance_data, earnings_data
            )

        except Exception as e:
            logger.warning("Failed to fetch fundamentals for %s: %s", symbol, e)
            return FundamentalData(symbol=symbol)

    def _normalize(
        self,
        symbol: str,
        profile_raw: Any,
        metrics_raw: Any,
        income_raw: Any,
        balance_raw: Any,
        earnings_raw: Any,
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
        total_debt = safe_float(balance, "totalDebt")
        total_equity = safe_float(balance, "totalStockholdersEquity") or safe_float(balance, "totalEquity")
        debt_to_equity = None
        if total_debt is not None and total_equity and total_equity != 0:
            debt_to_equity = total_debt / abs(total_equity)

        # Next earnings date
        next_earnings = None
        days_to_earnings = None
        earnings_date_str = earnings.get("date", "") or earnings.get("reportedDate", "")
        if earnings_date_str:
            try:
                next_earnings = date.fromisoformat(str(earnings_date_str)[:10])
                days_to_earnings = (next_earnings - date.today()).days
            except ValueError:
                pass

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
