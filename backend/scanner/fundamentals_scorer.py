"""
Converts raw FundamentalData into a single normalized 0-100 score.
Higher score = better fundamental quality for options trading.
"""

import math
from typing import Optional

from backend.models.fundamentals import FundamentalData


class FundamentalsScorer:
    """
    Multi-factor fundamental scoring model.

    Weights:
        PE score:       15%  — valuation
        Growth score:   25%  — revenue + earnings growth
        Debt score:     20%  — balance sheet health
        Margin score:   20%  — profitability
        ROE score:      10%  — capital efficiency
        FCF score:      10%  — cash generation
    """

    WEIGHTS = {
        "pe": 0.15,
        "growth": 0.25,
        "debt": 0.20,
        "margin": 0.20,
        "roe": 0.10,
        "fcf": 0.10,
    }

    def score(self, fund: FundamentalData) -> FundamentalData:
        """Compute and attach fundamental_score to the model. Returns updated model."""
        components = {
            "pe": self._pe_score(fund.pe_ratio),
            "growth": self._growth_score(fund.revenue_growth_yoy, fund.earnings_growth_yoy),
            "debt": self._debt_score(fund.debt_to_equity),
            "margin": self._margin_score(fund.gross_margin, fund.operating_margin),
            "roe": self._roe_score(fund.return_on_equity),
            "fcf": self._fcf_score(fund.free_cash_flow_yield),
        }

        composite = sum(components[k] * self.WEIGHTS[k] for k in components)
        fund.fundamental_score = round(composite, 2)
        return fund

    @staticmethod
    def _pe_score(pe: Optional[float]) -> float:
        """
        Score PE ratio.
        < 0 (negative earnings):    5
        0-15 (cheap):              100
        15-25 (fair value):         80
        25-40 (growth premium):     55
        > 40 (expensive):           20
        """
        if pe is None:
            return 50.0  # neutral if unknown
        if pe <= 0:
            return 5.0
        if pe <= 15:
            return 100.0
        if pe <= 25:
            return 100.0 - (pe - 15) * 2.0  # 100 → 80
        if pe <= 40:
            return 80.0 - (pe - 25) * 1.67  # 80 → 55
        return max(0.0, 55.0 - (pe - 40) * 1.75)  # 55 → 0 at PE=71

    @staticmethod
    def _growth_score(rev_growth: Optional[float], earn_growth: Optional[float]) -> float:
        """Score based on YoY revenue and earnings growth (decimal)."""
        def single_score(g: Optional[float]) -> float:
            if g is None:
                return 50.0
            if g >= 0.30:
                return 100.0
            if g >= 0.15:
                return 75.0 + (g - 0.15) / 0.15 * 25
            if g >= 0.05:
                return 50.0 + (g - 0.05) / 0.10 * 25
            if g >= 0.0:
                return 30.0 + g / 0.05 * 20
            # Negative growth
            return max(0.0, 30.0 + g * 150)  # -0.20 → 0

        rev = single_score(rev_growth)
        earn = single_score(earn_growth)
        # Weighted average: earnings count more
        return round(rev * 0.4 + earn * 0.6, 2)

    @staticmethod
    def _debt_score(de_ratio: Optional[float]) -> float:
        """
        Score Debt/Equity ratio.
        < 0 (net cash):   100
        0-0.5:             90
        0.5-1.0:           70
        1.0-2.0:           50
        2.0-3.0:           25
        > 3.0:              5
        """
        if de_ratio is None:
            return 50.0
        if de_ratio < 0:
            return 100.0
        if de_ratio <= 0.5:
            return 90.0
        if de_ratio <= 1.0:
            return 90.0 - (de_ratio - 0.5) * 40
        if de_ratio <= 2.0:
            return 70.0 - (de_ratio - 1.0) * 20
        if de_ratio <= 3.0:
            return 50.0 - (de_ratio - 2.0) * 25
        return max(0.0, 25.0 - (de_ratio - 3.0) * 5)

    @staticmethod
    def _margin_score(gross: Optional[float], operating: Optional[float]) -> float:
        """Score gross + operating margins (both as decimals)."""
        def gross_score(g: Optional[float]) -> float:
            if g is None:
                return 50.0
            if g >= 0.60:
                return 100.0
            if g >= 0.40:
                return 70.0 + (g - 0.40) / 0.20 * 30
            if g >= 0.20:
                return 40.0 + (g - 0.20) / 0.20 * 30
            return max(0.0, g / 0.20 * 40)

        def op_score(op: Optional[float]) -> float:
            if op is None:
                return 50.0
            if op >= 0.25:
                return 100.0
            if op >= 0.10:
                return 60.0 + (op - 0.10) / 0.15 * 40
            if op >= 0.0:
                return op / 0.10 * 60
            return max(0.0, 30.0 + op * 100)  # negative margins

        return round(gross_score(gross) * 0.5 + op_score(operating) * 0.5, 2)

    @staticmethod
    def _roe_score(roe: Optional[float]) -> float:
        """Score Return on Equity (decimal)."""
        if roe is None:
            return 50.0
        if roe >= 0.40:
            return 100.0
        if roe >= 0.20:
            return 70.0 + (roe - 0.20) / 0.20 * 30
        if roe >= 0.10:
            return 40.0 + (roe - 0.10) / 0.10 * 30
        if roe >= 0.0:
            return roe / 0.10 * 40
        return max(0.0, 20.0 + roe * 100)

    @staticmethod
    def _fcf_score(fcf_yield: Optional[float]) -> float:
        """Score Free Cash Flow yield (decimal)."""
        if fcf_yield is None:
            return 50.0
        if fcf_yield >= 0.08:
            return 100.0
        if fcf_yield >= 0.04:
            return 60.0 + (fcf_yield - 0.04) / 0.04 * 40
        if fcf_yield >= 0.0:
            return fcf_yield / 0.04 * 60
        return max(0.0, 20.0 + fcf_yield * 200)  # negative FCF
