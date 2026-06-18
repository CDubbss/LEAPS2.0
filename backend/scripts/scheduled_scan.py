"""
Automated scheduled options scan.

Runs the full 8-stage pipeline and saves results to logs/scheduled_scans/.
The outcome logger records candidates for ML training automatically.
Does NOT require the FastAPI server to be running — it initializes all
dependencies directly.

Usage:
    # Run with defaults from scan_config.json
    backend/.venv/Scripts/python.exe -m backend.scripts.scheduled_scan

    # Run with a custom filter config
    backend/.venv/Scripts/python.exe -m backend.scripts.scheduled_scan --config path/to/config.json

    # Preview filters without running
    backend/.venv/Scripts/python.exe -m backend.scripts.scheduled_scan --dry-run
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

LOG_DIR = _PROJECT_ROOT / "logs" / "scheduled_scans"
DEFAULT_CONFIG = _PROJECT_ROOT / "backend" / "scripts" / "scan_config.json"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"scan_{ts}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_file


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _load_filters(config_path: Path) -> dict:
    """Load filter overrides from JSON. Returns empty dict if file not found."""
    if not config_path.exists():
        logger.info("No config file at %s — using ScannerFilters defaults.", config_path)
        return {}
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    logger.info("Loaded scan config from %s", config_path)
    return cfg


# ---------------------------------------------------------------------------
# Scanner initialization (no FastAPI)
# ---------------------------------------------------------------------------

async def _build_scanner():
    import redis.asyncio as aioredis

    from backend.api.cache import RedisCache
    from backend.config.settings import get_settings
    from backend.data.fmp_client import FMPClient
    from backend.data.news_aggregator import NewsAggregator
    from backend.data.schwab_client import SchwabClient
    from backend.data.yfinance_client import YFinanceClient
    from backend.ml.model import SpreadRanker
    from backend.scanner.scanner import OptionsScanner
    from backend.sentiment.aggregator import SentimentAggregator
    from backend.sentiment.finbert_loader import FinBERTLoader
    from backend.sentiment.sentiment_scorer import SentimentScorer

    settings = get_settings()

    # Redis — RedisCache catches connection errors and falls back to in-memory
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    cache = RedisCache(redis_client)
    try:
        await redis_client.ping()
        logger.info("Redis connected: %s", settings.REDIS_URL)
    except Exception as e:
        logger.warning("Redis unavailable (%s) — scan will proceed with in-memory cache.", e)

    # FinBERT — loads ~450MB model; subsequent runs use local HuggingFace cache
    logger.info("Loading FinBERT model (first run downloads ~450MB)...")
    finbert = FinBERTLoader(settings)
    finbert.load()
    logger.info("FinBERT ready.")

    # ML model — placeholder until trained
    ml_ranker = SpreadRanker(
        model_path=settings.ML_MODEL_PATH,
        scaler_path=settings.ML_FEATURE_SCALER_PATH,
    )
    ml_ranker.load()

    # Data clients
    yf_client = YFinanceClient()
    schwab_client = SchwabClient(
        app_key=settings.SCHWAB_APP_KEY,
        app_secret=settings.SCHWAB_APP_SECRET,
        token_path=settings.SCHWAB_TOKEN_PATH,
    )
    fmp_client = FMPClient(api_key=settings.FMP_API_KEY)
    news_agg = NewsAggregator(yf_client)
    sent_scorer = SentimentScorer(finbert)
    sent_agg = SentimentAggregator()

    scanner = OptionsScanner(
        yf_client=yf_client,
        schwab_client=schwab_client,
        fmp_client=fmp_client,
        news_aggregator=news_agg,
        sentiment_scorer=sent_scorer,
        sentiment_aggregator=sent_agg,
        ml_ranker=ml_ranker,
        cache=cache,
        settings=settings,
    )

    return scanner, redis_client


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

async def run_scan(filters_override: dict, dry_run: bool = False) -> None:
    from backend.models.scanner import ScannerFilters

    filters = ScannerFilters(**filters_override)

    if dry_run:
        logger.info("[DRY RUN] Filters that would be used:")
        logger.info("%s", filters.model_dump_json(indent=2))
        return

    scanner, redis_client = await _build_scanner()

    logger.info(
        "Starting scan — strategies=%s  universe=%s  leaps_dte=%d–%d",
        [s.value for s in filters.strategies],
        filters.index_groups or "ALL",
        filters.leaps_min_dte,
        filters.leaps_max_dte,
    )

    result = await scanner.scan(filters)

    # Save JSON results
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = LOG_DIR / f"results_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)

    logger.info(
        "Scan complete: %d candidates → %d results in %.1fs",
        result.total_candidates_evaluated,
        len(result.results),
        result.scan_duration_seconds,
    )
    logger.info("Results saved to: %s", out_file)

    await redis_client.aclose()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run a scheduled options scan.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Path to JSON filter config (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved filters and exit without scanning.",
    )
    args = parser.parse_args()

    log_file = _setup_logging()
    logger.info("=" * 60)
    logger.info("Scheduled scan — %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Log file: %s", log_file)
    logger.info("=" * 60)

    filters_override = _load_filters(Path(args.config))

    try:
        asyncio.run(run_scan(filters_override, dry_run=args.dry_run))
    except KeyboardInterrupt:
        logger.info("Scan interrupted.")
    except Exception as e:
        logger.exception("Scan failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
