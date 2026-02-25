from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the backend/.env regardless of where uvicorn is launched from
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Financial Modeling Prep (fundamentals)
    FMP_API_KEY: str = ""
    FMP_BASE_URL: str = "https://financialmodelingprep.com/stable"

    # FinBERT
    FINBERT_MODEL_NAME: str = "ProsusAI/finbert"
    FINBERT_MAX_LENGTH: int = 512
    FINBERT_BATCH_SIZE: int = 16
    FINBERT_DEVICE: str = "cpu"  # set to "cuda" if GPU available

    # ML
    ML_MODEL_PATH: str = "ml/artifacts/spread_ranker.joblib"
    ML_FEATURE_SCALER_PATH: str = "ml/artifacts/feature_scaler.joblib"

    # Scanner defaults
    SCANNER_MIN_VOLUME: int = 100
    SCANNER_MIN_OPEN_INTEREST: int = 500
    SCANNER_MAX_BID_ASK_SPREAD_PCT: float = 0.15
    SCANNER_MIN_DTE: int = 30
    SCANNER_LEAPS_MIN_DTE: int = 365

    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    CACHE_TTL_QUOTES: int = Field(default=60, ge=1, le=86400)
    CACHE_TTL_FUNDAMENTALS: int = Field(default=86400, ge=1, le=604800)
    CACHE_TTL_CHAINS: int = Field(default=300, ge=1, le=86400)
    CACHE_TTL_SENTIMENT: int = Field(default=3600, ge=1, le=86400)
    CACHE_TTL_ML: int = Field(default=300, ge=1, le=86400)

    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # CORS — comma-separated or JSON array in .env, e.g.:
    # ALLOWED_ORIGINS=["http://localhost:5173","https://yourdomain.com"]
    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"]
    )

    # Review access (set to enable HTTP Basic Auth for public sharing)
    REVIEW_PASSWORD: str = ""

    # Rate limiting
    RATE_LIMIT_SCAN: str = "5/minute"
    RATE_LIMIT_SENTIMENT: str = "20/minute"
    RATE_LIMIT_DEFAULT: str = "60/minute"


@lru_cache
def get_settings() -> Settings:
    return Settings()
