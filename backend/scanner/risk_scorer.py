"""
Composite risk score computation.
Combines: IV rank, bid-ask quality, fundamentals, sentiment, liquidity.
Score range 0-100; higher = better risk profile for entering the trade.
"""

from backend.models.fundamentals import FundamentalData
from backend.models.options import SpreadCandidate
from backend.models.scanner import RiskScore
from backend.models.sentiment import TickerSentiment


class RiskScorer:
    """
    Composite risk score (0-100, higher = better risk-adjusted setup).

    Formula:
        composite = (
            iv_rank_component     * 0.25 +
            bid_ask_component     * 0.20 +
            fundamental_component * 0.25 +
            sentiment_component   * 0.15 +
            liquidity_component   * 0.15
        )
    """

    WEIGHTS = {
        "iv_rank": 0.25,
        "bid_ask": 0.20,
        "fundamental": 0.25,
        "sentiment": 0.15,
        "liquidity": 0.15,
    }

    def score(
        self,
        spread: SpreadCandidate,
        fundamentals: FundamentalData,
        sentiment: TickerSentiment,
    ) -> RiskScore:
        components = {
            "iv_rank": self._iv_rank_score(spread.iv_rank),
            "bid_ask": self._bid_ask_score(spread.bid_ask_quality_score),
            "fundamental": fundamentals.fundamental_score or 50.0,
            "sentiment": sentiment.sentiment_score,
            "liquidity": self._liquidity_score(spread.long_leg),
        }

        composite = sum(components[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        return RiskScore(
            composite_score=round(composite, 2),
            iv_rank_component=round(components["iv_rank"], 2),
            bid_ask_component=round(components["bid_ask"], 2),
            fundamental_component=round(components["fundamental"], 2),
            sentiment_component=round(components["sentiment"], 2),
            liquidity_component=round(components["liquidity"], 2),
            breakdown=components,
        )

    @staticmethod
    def _iv_rank_score(iv_rank: float) -> float:
        """
        For debit spreads (bull call / bear put / LEAPS):
        Lower IV rank is better — you're buying options cheaply.
        Score is inversely related to IV rank:
            IV rank 0  → score 100 (options are historically cheap)
            IV rank 50 → score 50
            IV rank 100 → score 0
        """
        return float(max(0.0, 100.0 - iv_rank))

    @staticmethod
    def _bid_ask_score(ba_quality: float) -> float:
        """
        bid_ask_quality_score is already 0-1 from SpreadConstructor.
        Scale to 0-100.
        """
        return float(max(0.0, min(100.0, ba_quality * 100)))

    @staticmethod
    def _liquidity_score(long_leg) -> float:
        """
        Score based on open interest and volume of the long leg.
        OI/1000 * 50 + volume/500 * 50, capped at 100.
        """
        oi_score = min(50.0, (long_leg.open_interest / 1000) * 50)
        vol_score = min(50.0, (long_leg.volume / 500) * 50)
        return round(oi_score + vol_score, 2)
