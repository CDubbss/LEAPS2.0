from typing import Optional

from pydantic import BaseModel, Field

from .fundamentals import FundamentalData
from .ml import MLPrediction
from .options import SpreadCandidate, SpreadType
from .sentiment import TickerSentiment


class ScannerFilters(BaseModel):
    symbols: Optional[list[str]] = Field(
        default=None,
        max_length=100,  # prevent DoS via giant symbol lists
        description="Ticker symbols to scan. Max 100. None = default universe.",
    )
    strategies: list[SpreadType] = Field(
        default=[SpreadType.LEAP_CALL, SpreadType.LEAPS_SPREAD_CALL]
    )
    min_dte: int = Field(default=30, ge=1, le=1825)
    max_dte: int = Field(default=90, ge=1, le=1825)
    leaps_min_dte: int = Field(default=365, ge=30, le=1825)
    leaps_max_dte: int = Field(default=730, ge=30, le=1825)
    min_iv_rank: float = Field(default=10.0, ge=0.0, le=100.0)
    max_iv_rank: float = Field(default=70.0, ge=0.0, le=100.0)
    min_volume: int = Field(default=100, ge=0, le=10_000_000)
    min_open_interest: int = Field(default=500, ge=0, le=10_000_000)
    max_bid_ask_spread_pct: float = Field(default=0.50, ge=0.0, le=1.0)
    min_fundamental_score: float = Field(default=40.0, ge=0.0, le=100.0)
    min_sentiment_score: float = Field(default=35.0, ge=0.0, le=100.0)
    min_probability_of_profit: float = Field(default=0.45, ge=0.0, le=1.0)
    min_ml_quality_score: float = Field(default=45.0, ge=0.0, le=100.0)
    max_results: int = Field(default=50, ge=1, le=200)
    # Spread width / cost controls (two-leg spreads only; single-leg LEAPS are exempt)
    target_spread_widths: list[float] = Field(default=[], max_length=20)
    max_spread_width: Optional[float] = Field(default=None, ge=0.0, le=100_000.0)
    max_debit_pct_of_spread: float = Field(default=1.0, ge=0.0, le=1.0)
    max_net_debit: Optional[float] = Field(default=None, ge=0.0, le=100_000.0)
    # Delta filter — applied to absolute value of long leg delta
    min_long_delta: float = Field(default=0.0, ge=0.0, le=1.0)
    max_long_delta: float = Field(default=1.0, ge=0.0, le=1.0)


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
