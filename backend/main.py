"""
Leaps2.0 — Options Scanner & ML Tool
FastAPI application entry point.

Startup sequence (via lifespan):
    1. Connect to Redis cache
    2. Load FinBERT model into memory (~450MB, CPU)
    3. Load XGBoost ML model (placeholder mode if not yet trained)

Run:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Swagger docs:
    http://localhost:8000/docs
"""

import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from backend.api.cache import RedisCache
from backend.api.routes import fundamentals, ml, options, scanner, sentiment
from backend.config.settings import get_settings
from backend.ml.model import SpreadRanker
from backend.sentiment.finbert_loader import FinBERTLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load and tear down expensive resources around the app lifecycle."""
    settings = get_settings()

    # --- Redis ---
    logger.info("Connecting to Redis at %s", settings.REDIS_URL)
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis unavailable (%s) — using in-process fallback cache", e)
        redis_client = None  # type: ignore[assignment]

    app.state.cache = RedisCache(redis_client)  # type: ignore[arg-type]

    # --- FinBERT ---
    logger.info("Loading FinBERT model (ProsusAI/finbert)...")
    finbert_loader = FinBERTLoader(settings)
    try:
        finbert_loader.load()
        logger.info("FinBERT ready")
    except Exception as e:
        logger.error(
            "FinBERT load failed: %s\n"
            "Ensure torch is installed: pip install torch --index-url https://download.pytorch.org/whl/cpu\n"
            "Then: pip install transformers tokenizers",
            e,
        )
    app.state.finbert_loader = finbert_loader

    # --- ML Model ---
    logger.info("Loading ML model from %s", settings.ML_MODEL_PATH)
    ml_ranker = SpreadRanker(
        model_path=settings.ML_MODEL_PATH,
        scaler_path=settings.ML_FEATURE_SCALER_PATH,
    )
    ml_ranker.load()
    app.state.ml_ranker = ml_ranker

    logger.info("Leaps2.0 startup complete — all systems ready")
    yield

    # --- Shutdown ---
    logger.info("Shutting down Leaps2.0...")
    finbert_loader.unload()
    if redis_client:
        await redis_client.aclose()
    logger.info("Shutdown complete")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth gate — only active when REVIEW_PASSWORD is set."""

    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                expected = get_settings().REVIEW_PASSWORD
                if expected and secrets.compare_digest(password, expected):
                    return await call_next(request)
            except Exception:
                pass
        return StarletteResponse(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Leaps2.0 Review"'},
        )


app = FastAPI(
    title="Leaps2.0 — Options Scanner & ML Tool",
    description=(
        "Scans the market for LEAPS and vertical spread opportunities using "
        "fundamental analysis, FinBERT sentiment scoring, and XGBoost ML ranking."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if get_settings().REVIEW_PASSWORD:
    app.add_middleware(BasicAuthMiddleware)

# Register API routers
app.include_router(scanner.router, prefix="/api/v1/scanner", tags=["Scanner"])
app.include_router(options.router, prefix="/api/v1/options", tags=["Options"])
app.include_router(sentiment.router, prefix="/api/v1/sentiment", tags=["Sentiment"])
app.include_router(fundamentals.router, prefix="/api/v1/fundamentals", tags=["Fundamentals"])
app.include_router(ml.router, prefix="/api/v1/ml", tags=["ML"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    settings = get_settings()
    return {
        "status": "ok",
        "finbert_loaded": app.state.finbert_loader.is_loaded(),
        "ml_trained": not app.state.ml_ranker._is_placeholder,
        "redis_url": settings.REDIS_URL,
    }


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )

# Serve the production React build at "/" (must be last so API routes match first)
_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
