"""
XGBoost SpreadRanker model.
Predicts a spread_quality_score (0-100) for each spread candidate.

Cold Start Strategy:
    On Day 1, no training data exists. The model returns placeholder scores
    (50.0 ± noise) so the system is functional. Real ML kicks in after
    ~500 labeled historical spread outcomes are logged.

Training:
    Run: python -m backend.ml.train
    Requires: backend/ml/data/spread_outcomes.db (filled by daily scanner logging)
"""

import logging
import os
import random
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from backend.models.ml import FeatureVector, MLPrediction
from backend.models.options import SpreadCandidate

logger = logging.getLogger(__name__)

_ml_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ml_inference")


class SpreadRanker:
    """
    XGBoost-based spread quality ranker.
    Loaded from disk at startup if artifact exists, otherwise runs in placeholder mode.
    """

    def __init__(self, model_path: str, scaler_path: str):
        self.model_path = model_path
        self.scaler_path = scaler_path
        self.pipeline = None
        self._is_placeholder = True

    def load(self) -> None:
        """Load trained model from disk. Falls back to placeholder if not found."""
        if os.path.exists(self.model_path):
            try:
                import joblib
                self.pipeline = joblib.load(self.model_path)
                self._is_placeholder = False
                logger.info("ML model loaded from %s", self.model_path)
            except Exception as e:
                logger.warning("Failed to load ML model (%s) — using placeholder", e)
                self._is_placeholder = True
        else:
            logger.info(
                "ML model artifact not found at %s — running in placeholder mode. "
                "Collect spread outcomes and run `python -m backend.ml.train` to train.",
                self.model_path,
            )
            self._is_placeholder = True

    def predict_batch(
        self, candidates: list[SpreadCandidate]
    ) -> list[MLPrediction]:
        """
        Synchronous batch prediction.
        If model is not trained, returns placeholder predictions (50.0 ± noise).
        Each candidate gets a prediction in the same order.
        """
        if self._is_placeholder or not candidates:
            return [self._placeholder_prediction(c) for c in candidates]

        try:
            from backend.ml.features import FeatureEngineer, FEATURE_NAMES
            # In live inference the scanner has already built FeatureVectors
            # This path is for direct spread list → predictions
            engineer = FeatureEngineer()
            # Build dummy feature vectors from spread data only (limited features)
            X = self._spreads_to_array(candidates)
            scores = self.pipeline.predict(X)
            return [
                self._build_prediction(float(np.clip(scores[i], 0, 100)), candidates[i])
                for i in range(len(candidates))
            ]
        except Exception as e:
            logger.error("ML inference error: %s", e)
            return [self._placeholder_prediction(c) for c in candidates]

    def predict_from_features(
        self, feature_vectors: list[FeatureVector]
    ) -> list[MLPrediction]:
        """
        Predict from pre-built FeatureVectors (used by scanner pipeline).
        This is the primary inference path.
        """
        if self._is_placeholder or not feature_vectors:
            return [self._placeholder_from_fv(fv) for fv in feature_vectors]

        try:
            from backend.ml.features import FEATURE_NAMES
            X = np.array(
                [[getattr(fv, name) for name in FEATURE_NAMES] for fv in feature_vectors],
                dtype=float,
            )
            scores = self.pipeline.predict(X)
            importances = self._get_importances()
            return [
                MLPrediction(
                    spread_quality_score=float(np.clip(scores[i], 0, 100)),
                    expected_return_pct=self._estimate_return(feature_vectors[i], scores[i]),
                    probability_of_profit=float(feature_vectors[i].iv_rank / 100),
                    confidence=self._compute_confidence(scores[i]),
                    feature_importances=importances,
                    is_placeholder=False,
                )
                for i in range(len(feature_vectors))
            ]
        except Exception as e:
            logger.error("Feature-based ML inference error: %s", e)
            return [self._placeholder_from_fv(fv) for fv in feature_vectors]

    def get_feature_importance(self) -> dict[str, float]:
        """Return feature importances dict for UI display."""
        if self._is_placeholder or self.pipeline is None:
            from backend.ml.features import FEATURE_NAMES
            return {name: 1.0 / len(FEATURE_NAMES) for name in FEATURE_NAMES}
        return self._get_importances()

    def _get_importances(self) -> dict[str, float]:
        try:
            from backend.ml.features import FEATURE_NAMES
            booster = self.pipeline.named_steps.get("xgb") or self.pipeline[-1]
            raw = booster.get_booster().get_score(importance_type="gain")
            total = sum(raw.values()) or 1
            normalized = {k: round(v / total, 4) for k, v in raw.items()}
            # Map f0, f1, ... back to feature names if needed
            result = {}
            for i, name in enumerate(FEATURE_NAMES):
                key = f"f{i}"
                result[name] = normalized.get(key, normalized.get(name, 0.0))
            return result
        except Exception:
            from backend.ml.features import FEATURE_NAMES
            return {name: 0.0 for name in FEATURE_NAMES}

    @staticmethod
    def _placeholder_prediction(spread: SpreadCandidate) -> MLPrediction:
        """Deterministic-ish placeholder based on spread characteristics."""
        # Use PoP and bid-ask quality to make a rough quality estimate
        base = 40.0
        base += spread.probability_of_profit * 20
        base += spread.bid_ask_quality_score * 20
        # Add small noise for variety
        score = max(20.0, min(80.0, base + random.uniform(-5, 5)))

        return MLPrediction(
            spread_quality_score=round(score, 2),
            expected_return_pct=round(spread.max_profit / max(spread.net_debit, 0.01) * 100, 2),
            probability_of_profit=spread.probability_of_profit,
            confidence=0.3,  # low confidence in placeholder mode
            feature_importances={},
            is_placeholder=True,
        )

    @staticmethod
    def _placeholder_from_fv(fv: FeatureVector) -> MLPrediction:
        base = 40.0 + fv.fundamental_score * 0.2 + fv.sentiment_score * 0.1
        score = max(20.0, min(80.0, base + random.uniform(-5, 5)))
        return MLPrediction(
            spread_quality_score=round(score, 2),
            expected_return_pct=round(fv.max_risk_reward_ratio * 30, 2),
            probability_of_profit=max(0.3, min(0.75, fv.iv_rank / 100 * 0.5 + 0.3)),
            confidence=0.3,
            feature_importances={},
            is_placeholder=True,
        )

    @staticmethod
    def _build_prediction(score: float, spread: SpreadCandidate) -> MLPrediction:
        return MLPrediction(
            spread_quality_score=score,
            expected_return_pct=round(spread.max_profit / max(spread.net_debit, 0.01) * 100, 2),
            probability_of_profit=spread.probability_of_profit,
            confidence=SpreadRanker._compute_confidence(score),
            feature_importances={},
            is_placeholder=False,
        )

    @staticmethod
    def _estimate_return(fv: FeatureVector, score: float) -> float:
        """Rough annualized return estimate based on score and DTE."""
        dte = max(fv.dte, 1)
        rr = fv.max_risk_reward_ratio
        pop = max(0.35, min(0.80, score / 100))
        expected = (pop * rr - (1 - pop)) * 100
        annualized = expected * (365 / dte)
        return round(max(-100.0, min(500.0, annualized)), 2)

    @staticmethod
    def _compute_confidence(score: float) -> float:
        """Map quality score to model confidence (higher scores = more confident)."""
        if score >= 75:
            return 0.80
        if score >= 60:
            return 0.65
        if score >= 45:
            return 0.50
        return 0.35

    @staticmethod
    def _spreads_to_array(candidates: list[SpreadCandidate]):
        """Build minimal feature array from spread candidates (for direct prediction)."""
        rows = []
        for c in candidates:
            rows.append([
                c.iv_rank,
                (c.long_leg.bid + c.long_leg.ask) / 2,
                abs(c.long_leg.delta),
                c.long_leg.gamma,
                c.long_leg.theta,
                float(c.dte),
                c.probability_of_profit,
                c.bid_ask_quality_score,
                c.spread_width,
                c.max_profit / max(c.net_debit, 0.01),
                c.net_debit,
            ])
        return np.array(rows, dtype=float)
