"""ML model API routes."""

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_ml_ranker
from backend.ml.model import SpreadRanker

router = APIRouter()


@router.get("/feature-importance", response_model=dict[str, float])
async def get_feature_importance(
    ranker: SpreadRanker = Depends(get_ml_ranker),
) -> dict[str, float]:
    """Return the ML model's feature importances for dashboard display."""
    return ranker.get_feature_importance()


@router.get("/status")
async def get_ml_status(
    ranker: SpreadRanker = Depends(get_ml_ranker),
) -> dict:
    """Return ML model status (trained vs placeholder mode)."""
    return {
        "is_trained": not ranker._is_placeholder,
        "mode": "placeholder" if ranker._is_placeholder else "trained",
        "model_path": ranker.model_path,
        "message": (
            "ML model is in placeholder mode. Run scans to collect data, "
            "then train with: python -m backend.ml.train"
            if ranker._is_placeholder
            else "ML model is trained and active."
        ),
    }
