"""
Main scanner orchestrator.
Coordinates all pipeline stages: data fetching, filtering, spread construction,
fundamentals, sentiment, ML inference, risk scoring, ranking.
"""

import asyncio
import logging
import time
import uuid
from datetime import date, datetime
from typing import Optional

from backend.api.cache import RedisCache
from backend.config.settings import Settings, get_settings
from backend.data.fmp_client import FMPClient
from backend.data.news_aggregator import NewsAggregator
from backend.data.yfinance_client import YFinanceClient
from backend.models.fundamentals import FundamentalData
from backend.models.options import SpreadCandidate, SpreadType
from backend.models.scanner import RankedSpread, ScannerFilters, ScannerResult
from backend.models.sentiment import TickerSentiment
from backend.scanner.fundamentals_scorer import FundamentalsScorer
from backend.scanner.options_filter import OptionsFilter
from backend.scanner.risk_scorer import RiskScorer
from backend.scanner.spread_constructor import SpreadConstructor
from backend.scanner.universe import UniverseBuilder
from backend.sentiment.aggregator import SentimentAggregator
from backend.sentiment.sentiment_scorer import SentimentScorer

logger = logging.getLogger(__name__)

# Concurrency limits to avoid overwhelming free-tier APIs
YFINANCE_SEMAPHORE = asyncio.Semaphore(6)   # yfinance concurrent fetches
FMP_SEMAPHORE = asyncio.Semaphore(3)          # FMP rate limit


class OptionsScanner:
    """
    8-Stage Options Scanning Pipeline:
        1. Universe — determine symbols to scan
        2. Options chains — fetch from yfinance (concurrent)
        3. Filter + construct spreads
        4. Fundamentals — fetch from FMP (concurrent, cached)
        5. News + sentiment — fetch news, run FinBERT batch
        6. ML inference — XGBoost spread quality scores
        7. Risk scoring — composite 5-factor score
        8. Rank + return results
    """

    def __init__(
        self,
        yf_client: YFinanceClient,
        fmp_client: FMPClient,
        news_aggregator: NewsAggregator,
        sentiment_scorer: SentimentScorer,
        sentiment_aggregator: SentimentAggregator,
        ml_ranker,  # SpreadRanker — imported lazily to avoid circular import
        cache: RedisCache,
        settings: Optional[Settings] = None,
    ):
        self.yf = yf_client
        self.fmp = fmp_client
        self.news = news_aggregator
        self.sentiment_scorer = sentiment_scorer
        self.sentiment_aggregator = sentiment_aggregator
        self.ml_ranker = ml_ranker
        self.cache = cache
        self.settings = settings or get_settings()

        self.universe_builder = UniverseBuilder()
        self.options_filter = OptionsFilter()
        self.spread_constructor = SpreadConstructor()
        self.fundamentals_scorer = FundamentalsScorer()
        self.risk_scorer = RiskScorer()

    async def scan(self, filters: ScannerFilters) -> ScannerResult:
        """Run the full pipeline and return ranked spread candidates."""
        start_time = time.time()
        scan_id = str(uuid.uuid4())

        logger.info("Starting scan %s", scan_id)

        # Stage 1: Universe
        symbols = await self.universe_builder.build(filters)
        logger.info("Scanning %d symbols", len(symbols))

        # Stage 2+3: Options chains + filter + spread construction
        all_candidates = await self._fetch_and_construct(symbols, filters)
        logger.info("Constructed %d spread candidates", len(all_candidates))

        if not all_candidates:
            return ScannerResult(
                scan_id=scan_id,
                scan_time=datetime.utcnow().isoformat(),
                filters_used=filters,
                total_candidates_evaluated=0,
                results=[],
                scan_duration_seconds=round(time.time() - start_time, 2),
            )

        unique_symbols = list({c.underlying for c in all_candidates})

        # Stage 4: Fundamentals
        fundamentals_map = await self._fetch_fundamentals(unique_symbols)

        # Stage 5: Sentiment
        sentiment_map = await self._fetch_sentiment(unique_symbols)

        # Populate IV rank on each candidate now that we have it
        iv_rank_map = await self._fetch_iv_ranks(unique_symbols, all_candidates)
        for cand in all_candidates:
            cand.iv_rank = iv_rank_map.get(cand.underlying, 50.0)

        # Stage 6: ML inference
        ml_predictions = self.ml_ranker.predict_batch(all_candidates)

        # Stage 7: Risk scoring
        risk_scores = []
        for cand in all_candidates:
            fund = fundamentals_map.get(cand.underlying, FundamentalData(symbol=cand.underlying))
            sent = sentiment_map.get(cand.underlying, _neutral_sentiment(cand.underlying))
            risk_scores.append(self.risk_scorer.score(cand, fund, sent))

        # Stage 8: Apply ML filter + rank
        ranked = []
        for i, (cand, ml_pred, risk) in enumerate(
            zip(all_candidates, ml_predictions, risk_scores)
        ):
            # Post-ML quality filter
            if ml_pred.spread_quality_score < filters.min_ml_quality_score:
                continue
            if cand.probability_of_profit < filters.min_probability_of_profit:
                continue
            fund = fundamentals_map.get(cand.underlying, FundamentalData(symbol=cand.underlying))
            sent = sentiment_map.get(cand.underlying, _neutral_sentiment(cand.underlying))
            if (fund.fundamental_score or 0) < filters.min_fundamental_score:
                continue
            if sent.sentiment_score < filters.min_sentiment_score:
                continue

            ranked.append(
                RankedSpread(
                    rank=0,  # filled below
                    spread=cand,
                    fundamentals=fund,
                    sentiment=sent,
                    ml_prediction=ml_pred,
                    risk_score=risk,
                )
            )

        # Sort by ML quality score descending, assign ranks
        ranked.sort(key=lambda x: x.ml_prediction.spread_quality_score, reverse=True)
        for i, item in enumerate(ranked):
            item.rank = i + 1

        logger.info(
            "Scan %s complete: %d candidates → %d passed filters in %.1fs",
            scan_id,
            len(all_candidates),
            len(ranked),
            time.time() - start_time,
        )

        return ScannerResult(
            scan_id=scan_id,
            scan_time=datetime.utcnow().isoformat(),
            filters_used=filters,
            total_candidates_evaluated=len(all_candidates),
            results=ranked[: filters.max_results],
            scan_duration_seconds=round(time.time() - start_time, 2),
        )

    async def _fetch_and_construct(
        self, symbols: list[str], filters: ScannerFilters
    ) -> list[SpreadCandidate]:
        """Stage 2+3: Fetch options chains and construct spreads for all symbols."""

        async def process_symbol(symbol: str) -> list[SpreadCandidate]:
            async with YFINANCE_SEMAPHORE:
                try:
                    quote = await self.yf.get_quote(symbol)
                    spot = quote["price"]
                    if spot <= 0:
                        return []

                    expirations = await self.yf.get_expirations(symbol)
                    if not expirations:
                        return []

                    all_spreads: list[SpreadCandidate] = []

                    # Pre-filter expirations by DTE to avoid fetching useless chains
                    today = date.today()
                    has_spread_strategies = any(
                        s in filters.strategies
                        for s in [SpreadType.BULL_CALL, SpreadType.BEAR_PUT]
                    )
                    has_leaps_strategies = any(
                        s in filters.strategies
                        for s in [SpreadType.LEAP_CALL, SpreadType.LEAP_PUT, SpreadType.LEAPS_SPREAD_CALL]
                    )

                    valid_expiries: list[str] = []
                    for exp in expirations:
                        try:
                            dte = (date.fromisoformat(exp) - today).days
                        except ValueError:
                            continue
                        if has_spread_strategies and filters.min_dte <= dte <= filters.max_dte:
                            valid_expiries.append(exp)
                        elif has_leaps_strategies and filters.leaps_min_dte <= dte <= filters.leaps_max_dte:
                            valid_expiries.append(exp)

                    for expiry in valid_expiries[:8]:  # limit to 8 per symbol
                        try:
                            calls, puts = await self.yf.get_options_chain(
                                symbol, expiry, spot
                            )
                            spreads = self.spread_constructor.build_all_spreads(
                                calls=calls,
                                puts=puts,
                                strategies=filters.strategies,
                                spot_price=spot,
                            )
                            # Apply bid-ask + spread width/cost filters
                            ba_filtered = [
                                s for s in spreads
                                if s.bid_ask_quality_score
                                >= (1 - filters.max_bid_ask_spread_pct)
                            ]
                            filtered = _apply_spread_filters(ba_filtered, filters)
                            all_spreads.extend(filtered)
                        except Exception as e:
                            logger.debug("Chain error %s %s: %s", symbol, expiry, e)
                            continue

                    return all_spreads

                except Exception as e:
                    logger.warning("Failed to process %s: %s", symbol, e)
                    return []

        tasks = [process_symbol(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_candidates: list[SpreadCandidate] = []
        for result in results:
            if isinstance(result, Exception):
                logger.debug("Symbol task error: %s", result)
            else:
                all_candidates.extend(result)

        return all_candidates

    async def _fetch_fundamentals(
        self, symbols: list[str]
    ) -> dict[str, FundamentalData]:
        """Stage 4: Fetch and score fundamentals for all unique symbols (cached)."""
        ttl = self.settings.CACHE_TTL_FUNDAMENTALS

        async def fetch_one(symbol: str) -> FundamentalData:
            async with FMP_SEMAPHORE:
                cache_key = f"fundamentals:{symbol}"
                cached = await self.cache.get(cache_key)
                if cached:
                    return FundamentalData(**cached)
                fund = await self.fmp.get_full_fundamentals(symbol)
                fund = self.fundamentals_scorer.score(fund)
                await self.cache.set(cache_key, fund, ttl)
                return fund

        tasks = [fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.warning("Fundamentals error %s: %s", symbol, result)
                output[symbol] = FundamentalData(symbol=symbol)
            else:
                output[symbol] = result
        return output

    async def _fetch_sentiment(
        self, symbols: list[str]
    ) -> dict[str, TickerSentiment]:
        """Stage 5: Fetch news and run FinBERT sentiment for all symbols."""
        ttl = self.settings.CACHE_TTL_SENTIMENT

        async def fetch_one(symbol: str) -> TickerSentiment:
            cache_key = f"sentiment_v2:{symbol}"
            cached = await self.cache.get(cache_key)
            if cached:
                return TickerSentiment(**cached)

            articles = await self.news.get_news(symbol)
            texts = [
                (a.title + " " + (a.description or "")).strip()
                for a in articles
                if a.title
            ]

            if not texts:
                neutral = _neutral_sentiment(symbol)
                await self.cache.set(cache_key, neutral.model_dump(), ttl)
                return neutral

            scored = await self.sentiment_scorer.score_texts_async(texts)
            # Filter articles to those with text (same ordering as scored)
            scored_articles = [a for a in articles if a.title]
            aggregated = self.sentiment_aggregator.aggregate(
                symbol=symbol,
                results=scored,
                articles=scored_articles,
                headlines=[a.title for a in articles[:5]],
            )
            await self.cache.set(cache_key, aggregated.model_dump(), ttl)
            return aggregated

        tasks = [fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.warning("Sentiment error %s: %s", symbol, result)
                output[symbol] = _neutral_sentiment(symbol)
            else:
                output[symbol] = result
        return output

    async def _fetch_iv_ranks(
        self, symbols: list[str], candidates: list[SpreadCandidate]
    ) -> dict[str, float]:
        """Compute IV rank for each symbol using long leg IV."""
        # Use the average IV of each symbol's candidates as current IV proxy
        iv_by_symbol: dict[str, list[float]] = {}
        for cand in candidates:
            iv_by_symbol.setdefault(cand.underlying, []).append(
                cand.long_leg.implied_volatility
            )

        async def compute_one(symbol: str) -> tuple[str, float]:
            cache_key = f"iv_rank:{symbol}"
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return symbol, float(cached)
            ivs = iv_by_symbol.get(symbol, [])
            current_iv = sum(ivs) / len(ivs) if ivs else None
            rank = await self.yf.compute_iv_rank(symbol, current_iv)
            await self.cache.set(cache_key, rank, self.settings.CACHE_TTL_CHAINS)
            return symbol, rank

        tasks = [compute_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for result in results:
            if isinstance(result, Exception):
                continue
            symbol, rank = result
            output[symbol] = rank
        return output


def _apply_spread_filters(
    spreads: list[SpreadCandidate], filters: ScannerFilters
) -> list[SpreadCandidate]:
    """Filter spread candidates by width and cost constraints."""
    out = []
    for s in spreads:
        # Single-leg LEAPS have no short leg — exempt from width/cost filters
        if s.short_leg is None:
            out.append(s)
            continue
        w = s.spread_width
        # Target widths: if any selected, candidate must match one exactly
        if filters.target_spread_widths and not any(
            abs(w - tw) < 0.01 for tw in filters.target_spread_widths
        ):
            continue
        # Max spread width hard cap
        if filters.max_spread_width is not None and w > filters.max_spread_width:
            continue
        # Max debit as fraction of spread width (e.g. 0.25 = pay ≤25% of width)
        if w > 0 and s.net_debit / w > filters.max_debit_pct_of_spread:
            continue
        # Max net debit absolute cap
        if filters.max_net_debit is not None and s.net_debit > filters.max_net_debit:
            continue
        out.append(s)
    return out


def _neutral_sentiment(symbol: str) -> TickerSentiment:
    """Return a neutral (50/50/50) sentiment when news is unavailable."""
    return TickerSentiment(
        symbol=symbol,
        articles_analyzed=0,
        avg_positive=0.33,
        avg_negative=0.33,
        avg_neutral=0.34,
        avg_compound=0.0,
        sentiment_label="neutral",
        sentiment_score=50.0,
        top_headlines=[],
        analyzed_at=datetime.utcnow().isoformat(),
    )
