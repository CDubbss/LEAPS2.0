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
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from backend.api.cache import RedisCache
from backend.api.limiter import limiter
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
    logger.info("Connecting to Redis...")
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
    logger.info("Loading ML model...")
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


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds standard security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # HSTS — only meaningful when served over HTTPS
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Restrict what the page itself can load/execute
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        return response


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status code, and response time for every request."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        logger.info(
            "%s %s %s %.3fs %s",
            request.method,
            request.url.path,
            response.status_code,
            duration,
            request.client.host if request.client else "unknown",
        )
        return response


# ---------------------------------------------------------------------------
# HTTP Basic Auth middleware (review/staging access)
# ---------------------------------------------------------------------------

# Simple in-memory brute-force guard: track consecutive failures per IP.
# Not a substitute for proper auth, but raises the bar against scripted attacks.
_auth_failures: dict[str, list[float]] = defaultdict(list)
_AUTH_WINDOW_SECONDS = 300   # 5-minute sliding window
_AUTH_MAX_FAILURES = 10       # lock out after 10 failures in the window


def _is_locked_out(ip: str) -> bool:
    now = time.time()
    # Prune old entries outside the window
    _auth_failures[ip] = [t for t in _auth_failures[ip] if now - t < _AUTH_WINDOW_SECONDS]
    return len(_auth_failures[ip]) >= _AUTH_MAX_FAILURES


def _record_failure(ip: str) -> None:
    _auth_failures[ip].append(time.time())


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """HTTP Basic Auth gate — only active when REVIEW_PASSWORD is set."""

    _PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._PUBLIC_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        if _is_locked_out(client_ip):
            logger.warning("Auth lockout active for %s", client_ip)
            return StarletteResponse(
                "Too many failed attempts — try again later",
                status_code=429,
                headers={"Retry-After": str(_AUTH_WINDOW_SECONDS)},
            )

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

        _record_failure(client_ip)
        logger.warning("Failed auth attempt from %s for %s", client_ip, request.url.path)
        return StarletteResponse(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Leaps2.0 Review"'},
        )


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

settings = get_settings()

app = FastAPI(
    title="Leaps2.0 — Options Scanner & ML Tool",
    description=(
        "Scans the market for LEAPS and vertical spread opportunities using "
        "fundamental analysis, FinBERT sentiment scoring, and XGBoost ML ranking."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiter state & exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware (applied in reverse registration order: last-registered = outermost)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

if settings.REVIEW_PASSWORD:
    app.add_middleware(BasicAuthMiddleware)

# Register API routers
app.include_router(scanner.router, prefix="/api/v1/scanner", tags=["Scanner"])
app.include_router(options.router, prefix="/api/v1/options", tags=["Options"])
app.include_router(sentiment.router, prefix="/api/v1/sentiment", tags=["Sentiment"])
app.include_router(fundamentals.router, prefix="/api/v1/fundamentals", tags=["Fundamentals"])
app.include_router(ml.router, prefix="/api/v1/ml", tags=["ML"])


@app.get("/health")
async def health_check(request: Request):
    """Public health check — returns minimal status info only."""
    return {
        "status": "ok",
        "finbert_loaded": request.app.state.finbert_loader.is_loaded(),
        "ml_trained": not request.app.state.ml_ranker._is_placeholder,
    }


if __name__ == "__main__":
    import uvicorn
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
