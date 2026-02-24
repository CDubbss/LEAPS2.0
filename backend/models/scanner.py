from typing import Optional

from pydantic import BaseModel, Field

from .fundamentals import FundamentalData
from .ml import MLPrediction
from .options import SpreadCandidate, SpreadType
from .sentiment import TickerSentiment


class ScannerFilters(BaseModel):
    symbols: Optional[list[str]] = None          # None = use default universe
    strategies: list[SpreadType] = Field(
        default=[SpreadType.LEAP_CALL, SpreadType.LEAPS_SPREAD_CALL]
    )
    min_dte: int = 30
    max_dte: int = 90
    leaps_min_dte: int = 365                     # used when LEAP strategies selected
    leaps_max_dte: int = 730
    min_iv_rank: float = 10.0
    max_iv_rank: float = 70.0
    min_volume: int = 100
    min_open_interest: int = 500
    max_bid_ask_spread_pct: float = 0.15
    min_fundamental_score: float = 40.0
    min_sentiment_score: float = 35.0
    min_probability_of_profit: float = 0.45
    min_ml_quality_score: float = 45.0
    max_results: int = 50
    # Spread width / cost controls (two-leg spreads only; single-leg LEAPS are exempt)
    target_spread_widths: list[float] = Field(default=[])  # empty = any width
    max_spread_width: Optional[float] = None               # hard cap in $
    max_debit_pct_of_spread: float = 1.0                   # 1.0 = no cap; 0.25 = pay ≤25% of width
    max_net_debit: Optional[float] = None                  # hard cap on net debit in $
    # Delta filter — applied to absolute value of long leg delta
    min_long_delta: float = 0.0                            # 0.0 = no minimum
    max_long_delta: float = 1.0                            # 1.0 = no maximum


class RiskScore(BaseModel):
    composite_score: float          # 0-100
    iv_rank_component: float
    bid_ask_component: float
    fundamental_component: float
    sentiment_component: float
    liquidity_component: float
    breakdown: dict[str, float]


class RankedSpread(BaseModel):
    rank: int
    spread: SpreadCandidate
    fundamentals: FundamentalData
    sentiment: TickerSentiment
    ml_prediction: MLPrediction
    risk_score: RiskScore


class ScannerResult(BaseModel):
    scan_id: str
    scan_time: str
    filters_used: ScannerFilters
    total_candidates_evaluated: int
    results: list[RankedSpread]
    scan_duration_seconds: float
