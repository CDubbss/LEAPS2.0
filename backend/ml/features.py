"""
Feature engineering for the XGBoost spread ranker.
Builds a 23-feature FeatureVector from spread + fundamentals + sentiment data.
"""

import logging
import math
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
        hv_30d: float = 0.30,
        iv_52w_high: float = 0.60,
        iv_52w_low: float = 0.15,
    ) -> FeatureVector:
        long = spread.long_leg
        short = spread.short_leg

        _nan = float("nan")

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

        # --- IV skew (from spread candidate, computed during chain processing) ---
        iv_skew_val = spread.iv_skew if spread.iv_skew != 0.0 else _nan

        # --- Fundamental features ---
        # Use NaN for missing values so XGBoost learns the optimal split direction
        # for missing data rather than treating "no FMP data" as a specific value.
        pe_raw = fundamentals.pe_ratio
        pe = min(float(pe_raw), 100.0) if pe_raw is not None else _nan
        rev_growth = float(fundamentals.revenue_growth_yoy) if fundamentals.revenue_growth_yoy is not None else _nan
        debt_eq = float(fundamentals.debt_to_equity) if fundamentals.debt_to_equity is not None else _nan
        gross_margin = float(fundamentals.gross_margin) if fundamentals.gross_margin is not None else _nan
        fund_score = float(fundamentals.fundamental_score) if fundamentals.fundamental_score is not None else _nan

        # --- Sentiment ---
        sent_score = sentiment.sentiment_score
        sent_compound = sentiment.avg_compound

        # --- Technical context (52w high/low from spread candidate via yfinance quote) ---
        p52h_val = spread.price_52w_high
        p52l_val = spread.price_52w_low
        p52h = (spot_price - p52h_val) / p52h_val if p52h_val > 0 else _nan
        p52l = (spot_price - p52l_val) / p52l_val if p52l_val > 0 else _nan

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
            iv_skew=iv_skew_val,
            # Fundamentals
            pe_ratio=pe,
            revenue_growth=rev_growth,
            debt_to_equity=debt_eq,
            gross_margin=gross_margin,
            fundamental_score=fund_score,
            # Sentiment
            sentiment_score=float(sent_score),
            sentiment_compound=float(sent_compound),
            # Technical
            price_vs_52w_high_pct=p52h,
            price_vs_52w_low_pct=p52l,
            sector_relative_strength=float("nan"),  # no data source — XGBoost treats as missing
        )

    def to_numpy(self, fv: FeatureVector):
        """Convert FeatureVector to numpy array in canonical feature order."""
        import numpy as np
        return np.array([[getattr(fv, name) for name in FEATURE_NAMES]], dtype=float)
