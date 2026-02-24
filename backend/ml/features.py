"""
Feature engineering for the XGBoost spread ranker.
Builds a 23-feature FeatureVector from spread + fundamentals + sentiment data.
"""

import logging
from datetime import date

from backend.models.fundamentals import FundamentalData
from backend.models.ml import FeatureVector
from backend.models.options import SpreadCandidate, SpreadType
from backend.models.sentiment import TickerSentiment

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "iv_rank",
    "iv_percentile",
    "bid_ask_spread_pct",
    "delta",
    "gamma",
    "theta_per_day",
    "dte",
    "moneyness",
    "spread_width_pct",
    "max_risk_reward_ratio",
    "net_debit_pct_of_spread",
    "iv_vs_hv_ratio",
    "iv_skew",
    "pe_ratio",
    "revenue_growth",
    "debt_to_equity",
    "gross_margin",
    "fundamental_score",
    "sentiment_score",
    "sentiment_compound",
    "price_vs_52w_high_pct",
    "price_vs_52w_low_pct",
    "sector_relative_strength",
]


class FeatureEngineer:
    """
    Converts a (SpreadCandidate, FundamentalData, TickerSentiment, spot_price) tuple
    into a FeatureVector suitable for ML inference or training.
    Missing values are replaced with sensible defaults.
    """

    def build(
        self,
        spread: SpreadCandidate,
        fundamentals: FundamentalData,
        sentiment: TickerSentiment,
        spot_price: float,
        hv_30d: float = 0.30,  # 30-day historical volatility (default 30%)
        iv_52w_high: float = 0.60,
        iv_52w_low: float = 0.15,
        price_52w_high: float = 0.0,
        price_52w_low: float = 0.0,
    ) -> FeatureVector:
        long = spread.long_leg
        short = spread.short_leg

        # --- Options mechanics ---
        iv = long.implied_volatility
        iv_range = max(iv_52w_high - iv_52w_low, 0.01)
        iv_rank = spread.iv_rank
        iv_percentile = max(0.0, min(100.0, (iv - iv_52w_low) / iv_range * 100))

        mid_long = (long.bid + long.ask) / 2
        ba_pct_long = (long.ask - long.bid) / mid_long if mid_long > 0 else 0.15

        moneyness = (long.strike - spot_price) / spot_price if spot_price > 0 else 0.0

        # --- Spread structure ---
        spread_width = spread.spread_width
        spread_width_pct = spread_width / spot_price if spot_price > 0 else 0.0

        if spread.max_loss > 0:
            rr_ratio = spread.max_profit / spread.max_loss
        else:
            rr_ratio = 0.0

        if spread_width > 0:
            net_debit_pct = spread.net_debit / spread_width
        else:
            net_debit_pct = 1.0  # for LEAPS, no spread width

        # --- Volatility regime ---
        iv_vs_hv = iv / hv_30d if hv_30d > 0 else 1.0

        # --- Fundamental features ---
        pe = fundamentals.pe_ratio or 25.0
        pe = min(pe, 100.0)  # cap extreme PE for normalization
        rev_growth = fundamentals.revenue_growth_yoy or 0.0
        debt_eq = fundamentals.debt_to_equity or 0.5
        gross_margin = fundamentals.gross_margin or 0.30
        fund_score = fundamentals.fundamental_score or 50.0

        # --- Sentiment ---
        sent_score = sentiment.sentiment_score
        sent_compound = sentiment.avg_compound

        # --- Technical context ---
        p52h = (spot_price - price_52w_high) / price_52w_high if price_52w_high > 0 else 0.0
        p52l = (spot_price - price_52w_low) / price_52w_low if price_52w_low > 0 else 0.0

        return FeatureVector(
            # Options
            iv_rank=float(iv_rank),
            iv_percentile=float(iv_percentile),
            bid_ask_spread_pct=float(ba_pct_long),
            delta=float(abs(long.delta)),
            gamma=float(long.gamma),
            theta_per_day=float(long.theta),
            dte=float(spread.dte),
            moneyness=float(moneyness),
            # Spread structure
            spread_width_pct=float(spread_width_pct),
            max_risk_reward_ratio=float(rr_ratio),
            net_debit_pct_of_spread=float(net_debit_pct),
            # Volatility
            iv_vs_hv_ratio=float(iv_vs_hv),
            iv_skew=0.0,  # placeholder — requires additional data
            # Fundamentals
            pe_ratio=float(pe),
            revenue_growth=float(rev_growth),
            debt_to_equity=float(debt_eq),
            gross_margin=float(gross_margin),
            fundamental_score=float(fund_score),
            # Sentiment
            sentiment_score=float(sent_score),
            sentiment_compound=float(sent_compound),
            # Technical
            price_vs_52w_high_pct=float(p52h),
            price_vs_52w_low_pct=float(p52l),
            sector_relative_strength=0.5,  # placeholder
        )

    def to_numpy(self, fv: FeatureVector):
        """Convert FeatureVector to numpy array in canonical feature order."""
        import numpy as np
        return np.array([[getattr(fv, name) for name in FEATURE_NAMES]], dtype=float)
