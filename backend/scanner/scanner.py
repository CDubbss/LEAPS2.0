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
from backend.data.schwab_client import SchwabClient
from backend.data.yfinance_client import YFinanceClient
from backend.models.fundamentals import FundamentalData
from backend.models.options import OptionQuote, SpreadCandidate, SpreadType
from backend.models.scanner import RankedSpread, ScannerFilters, ScannerResult
from backend.models.sentiment import TickerSentiment
from backend.scanner.fundamentals_scorer import FundamentalsScorer
from backend.scanner.options_filter import OptionsFilter
from backend.scanner.risk_scorer import RiskScorer
from backend.scanner.spread_constructor import SpreadConstructor
from backend.scanner.universe import UniverseBuilder
from backend.ml.outcome_logger import OutcomeLogger
from backend.sentiment.aggregator import SentimentAggregator
from backend.sentiment.sentiment_scorer import SentimentScorer

logger = logging.getLogger(__name__)

# FMP rate limit — free tier is 250 calls/day; keep at 1 concurrent
FMP_SEMAPHORE = asyncio.Semaphore(1)
# yfinance concurrency is managed per-call inside yfinance_client._run_sync


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
        schwab_client: Optional[SchwabClient] = None,
    ):
        self.yf = yf_client
        self.schwab = schwab_client  # None until token file exists
        self.fmp = fmp_client
        self.news = news_aggregator
        self.sentiment_scorer = sentiment_scorer
        self.sentiment_aggregator = sentiment_aggregator
        self.ml_ranker = ml_ranker
        self.cache = cache
        self.settings = settings or get_settings()

        if self.schwab and self.schwab.is_available:
            logger.info("Options chain source: Schwab (real-time, broker greeks)")
        else:
            logger.info("Options chain source: yfinance (15-min delayed)")

        self.universe_builder = UniverseBuilder()
        self.options_filter = OptionsFilter()
        self.spread_constructor = SpreadConstructor()
        self.fundamentals_scorer = FundamentalsScorer()
        self.risk_scorer = RiskScorer()
        self.outcome_logger = OutcomeLogger()
        self._feature_engineer = None  # lazy-init to avoid circular import

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

        # Propagate earnings data from fundamentals to each candidate
        for cand in all_candidates:
            fund = fundamentals_map.get(cand.underlying)
            if fund:
                cand.days_to_earnings = fund.days_to_earnings
                cand.next_earnings_date = fund.next_earnings_date

        # Earnings proximity filter — drop candidates that don't meet the window
        # when earnings_play=True; for earnings strategy types always enforce window.
        has_earnings_strategies = any(
            s in filters.strategies
            for s in [SpreadType.EARNINGS_CALL, SpreadType.EARNINGS_PUT]
        )
        if has_earnings_strategies or filters.earnings_play:
            before = len(all_candidates)

            def _earnings_ok(c: SpreadCandidate) -> bool:
                in_window = (
                    c.days_to_earnings is not None
                    and filters.earnings_min_days <= c.days_to_earnings <= filters.earnings_max_days
                )
                if c.spread_type in _EARNINGS_TYPES:
                    # Earnings strategy types always require a confirmed date in window
                    return in_window
                if filters.earnings_play:
                    # earnings_play=True applied to other strategy types:
                    # pass through if date is unknown (can't confirm, don't penalize)
                    return in_window or c.days_to_earnings is None
                # Non-earnings strategy, earnings_play=False — always passes
                return True

            all_candidates = [c for c in all_candidates if _earnings_ok(c)]
            logger.info(
                "Earnings proximity filter: %d → %d candidates (window %d–%d days)",
                before, len(all_candidates),
                filters.earnings_min_days, filters.earnings_max_days,
            )

        # Stage 5: Sentiment
        sentiment_map = await self._fetch_sentiment(unique_symbols)

        # Populate IV rank on each candidate now that we have it
        iv_rank_map = await self._fetch_iv_ranks(unique_symbols, all_candidates)
        for cand in all_candidates:
            cand.iv_rank = iv_rank_map.get(cand.underlying, 50.0)

        # Populate HV and 52-week IV range (used for iv_vs_hv_ratio, iv_percentile features)
        hv_map = await self._fetch_hv_data(unique_symbols)
        for cand in all_candidates:
            hv, iv_high, iv_low = hv_map.get(cand.underlying, (0.30, 0.60, 0.15))
            cand.hv_30d = hv
            cand.iv_52w_high = iv_high
            cand.iv_52w_low = iv_low

        # Stage 6: ML inference — build full 23-feature vectors, use predict_from_features
        from backend.ml.features import FeatureEngineer
        if self._feature_engineer is None:
            self._feature_engineer = FeatureEngineer()
        feature_vectors = [
            self._feature_engineer.build(
                spread=cand,
                fundamentals=fundamentals_map.get(cand.underlying, FundamentalData(symbol=cand.underlying)),
                sentiment=sentiment_map.get(cand.underlying, _neutral_sentiment(cand.underlying)),
                spot_price=cand.spot_price,
                hv_30d=cand.hv_30d or 0.30,
                iv_52w_high=cand.iv_52w_high or 0.60,
                iv_52w_low=cand.iv_52w_low or 0.15,
            )
            for cand in all_candidates
        ]
        ml_predictions = self.ml_ranker.predict_from_features(feature_vectors)

        # Stage 7: Risk scoring
        risk_scores = []
        for cand in all_candidates:
            fund = fundamentals_map.get(cand.underlying, FundamentalData(symbol=cand.underlying))
            sent = sentiment_map.get(cand.underlying, _neutral_sentiment(cand.underlying))
            risk_scores.append(self.risk_scorer.score(cand, fund, sent))

        # Stage 8: Apply ML filter + rank
        reject_ml = reject_pop = reject_fund = reject_sent = 0
        ranked = []
        for i, (cand, ml_pred, risk) in enumerate(
            zip(all_candidates, ml_predictions, risk_scores)
        ):
            # Post-ML quality filter
            if ml_pred.spread_quality_score < filters.min_ml_quality_score:
                reject_ml += 1
                continue
            if not (filters.min_iv_rank <= cand.iv_rank <= filters.max_iv_rank):
                reject_ml += 1  # reuse counter; IV rank is a quality gate
                continue
            if cand.probability_of_profit < filters.min_probability_of_profit:
                reject_pop += 1
                continue
            fund = fundamentals_map.get(cand.underlying, FundamentalData(symbol=cand.underlying))
            sent = sentiment_map.get(cand.underlying, _neutral_sentiment(cand.underlying))
            if (fund.fundamental_score or 0) < filters.min_fundamental_score:
                reject_fund += 1
                continue
            if sent.sentiment_score < filters.min_sentiment_score:
                reject_sent += 1
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

        # Sort by ML quality score descending
        ranked.sort(key=lambda x: x.ml_prediction.spread_quality_score, reverse=True)

        # Apply per-symbol diversity cap (keeps best N spreads per ticker)
        symbol_counts: dict[str, int] = {}
        diverse: list = []
        for item in ranked:
            sym = item.spread.underlying
            count = symbol_counts.get(sym, 0)
            if count >= filters.max_results_per_symbol:
                continue
            symbol_counts[sym] = count + 1
            diverse.append(item)
        ranked = diverse

        # Assign final ranks
        for i, item in enumerate(ranked):
            item.rank = i + 1

        logger.info(
            "Scan %s complete: %d candidates → %d passed (rejected: ml=%d pop=%d fund=%d sent=%d) in %.1fs",
            scan_id,
            len(all_candidates),
            len(ranked),
            reject_ml, reject_pop, reject_fund, reject_sent,
            time.time() - start_time,
        )

        # Log ranked spreads for ML training (non-blocking, safe to fail)
        try:
            self.outcome_logger.log_scan_results(scan_id, ranked)
        except Exception as e:
            logger.warning("Outcome logging failed (scan unaffected): %s", e)

        return ScannerResult(
            scan_id=scan_id,
            scan_time=datetime.utcnow().isoformat(),
            filters_used=filters,
            total_candidates_evaluated=len(all_candidates),
            results=ranked[: filters.max_results],
            scan_duration_seconds=round(time.time() - start_time, 2),
        )

    # ------------------------------------------------------------------
    # Data-source helpers — try Schwab first, fall back to yfinance
    # ------------------------------------------------------------------

    async def _get_quote(self, symbol: str) -> dict:
        if self.schwab and self.schwab.is_available:
            try:
                return await self.schwab.get_quote(symbol)
            except Exception as e:
                logger.debug("Schwab quote failed for %s (%s), using yfinance", symbol, e)
        return await self.yf.get_quote(symbol)

    async def _get_expirations(self, symbol: str) -> list[str]:
        if self.schwab and self.schwab.is_available:
            try:
                return await self.schwab.get_expirations(symbol)
            except Exception as e:
                logger.debug("Schwab expirations failed for %s (%s), using yfinance", symbol, e)
        return await self.yf.get_expirations(symbol)

    async def _get_options_chain(
        self, symbol: str, expiry: str, spot: float
    ) -> tuple[list[OptionQuote], list[OptionQuote]]:
        if self.schwab and self.schwab.is_available:
            try:
                return await self.schwab.get_options_chain(symbol, expiry, spot)
            except Exception as e:
                logger.debug("Schwab chain failed for %s %s (%s), using yfinance", symbol, expiry, e)
        return await self.yf.get_options_chain(symbol, expiry, spot)

    # ------------------------------------------------------------------

    async def _fetch_and_construct(
        self, symbols: list[str], filters: ScannerFilters
    ) -> list[SpreadCandidate]:
        """Stage 2+3: Fetch options chains and construct spreads for all symbols."""

        async def process_symbol(symbol: str) -> list[SpreadCandidate]:
            try:
                # --- Quote (cached 60s) ---
                quote_key = f"quote:{symbol}"
                quote = await self.cache.get(quote_key)
                if not quote:
                    quote = await self._get_quote(symbol)
                    await self.cache.set(quote_key, quote, self.settings.CACHE_TTL_QUOTES)
                spot = quote["price"]
                price_52w_high = float(quote.get("fifty_two_week_high") or 0.0)
                price_52w_low = float(quote.get("fifty_two_week_low") or 0.0)
                if spot <= 0:
                    return []

                # --- Expirations (cached 5m) ---
                exp_key = f"expirations:{symbol}"
                expirations = await self.cache.get(exp_key)
                if not expirations:
                    expirations = await self._get_expirations(symbol)
                    await self.cache.set(exp_key, expirations, self.settings.CACHE_TTL_CHAINS)
                if not expirations:
                    return []

                all_spreads: list[SpreadCandidate] = []

                # Pre-filter expirations by DTE
                today = date.today()
                has_spread_strategies = any(
                    s in filters.strategies
                    for s in [SpreadType.BULL_CALL, SpreadType.BEAR_PUT]
                )
                has_leaps_strategies = any(
                    s in filters.strategies
                    for s in [SpreadType.LEAP_CALL, SpreadType.LEAP_PUT, SpreadType.LEAPS_SPREAD_CALL]
                )
                has_earnings_strategies = any(
                    s in filters.strategies
                    for s in [SpreadType.EARNINGS_CALL, SpreadType.EARNINGS_PUT]
                )

                valid_expiries: list[str] = []
                for exp in expirations:
                    try:
                        dte = (date.fromisoformat(exp) - today).days
                    except ValueError:
                        continue
                    include = False
                    if has_spread_strategies and filters.min_dte <= dte <= filters.max_dte:
                        include = True
                    if has_leaps_strategies and filters.leaps_min_dte <= dte <= filters.leaps_max_dte:
                        include = True
                    if has_earnings_strategies and filters.min_dte <= dte <= filters.max_dte:
                        include = True
                    if include:
                        valid_expiries.append(exp)

                for expiry in valid_expiries[:5]:  # limit to 5 per symbol
                    try:
                        # --- Options chain (cached 5m) ---
                        chain_key = f"chain:{symbol}:{expiry}"
                        cached_chain = await self.cache.get(chain_key)
                        if cached_chain:
                            calls = [OptionQuote.model_validate(q) for q in cached_chain["calls"]]
                            puts  = [OptionQuote.model_validate(q) for q in cached_chain["puts"]]
                        else:
                            calls, puts = await self._get_options_chain(symbol, expiry, spot)
                            # Only cache non-empty chains — caching empty results
                            # would poison all subsequent scans within the TTL window
                            if calls or puts:
                                await self.cache.set(
                                    chain_key,
                                    {"calls": [q.model_dump(mode="json") for q in calls],
                                     "puts":  [q.model_dump(mode="json") for q in puts]},
                                    self.settings.CACHE_TTL_CHAINS,
                                )
                            else:
                                logger.debug("Empty chain %s %s — not caching", symbol, expiry)

                        spreads = self.spread_constructor.build_all_spreads(
                            calls=calls,
                            puts=puts,
                            strategies=filters.strategies,
                            spot_price=spot,
                        )
                        ba_filtered = [
                            s for s in spreads
                            if _passes_ba_filter(s, filters.max_bid_ask_spread_pct)
                        ]
                        filtered = _apply_spread_filters(ba_filtered, filters)
                        iv_skew = _compute_iv_skew(calls, puts)
                        for s in filtered:
                            s.spot_price = spot
                            s.price_52w_high = price_52w_high
                            s.price_52w_low = price_52w_low
                            s.iv_skew = iv_skew
                        all_spreads.extend(filtered)
                    except Exception as e:
                        logger.warning("Chain error %s %s: %s", symbol, expiry, e)
                        continue

                if not all_spreads:
                    logger.debug(
                        "No candidates for %s (valid_expiries=%d)",
                        symbol, len(valid_expiries),
                    )
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
                # Only cache if we got real data. An empty company_name means
                # FMP returned 429/error — don't cache so the next scan retries.
                if fund.company_name:
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


    async def _fetch_hv_data(
        self, symbols: list[str]
    ) -> dict[str, tuple[float, float, float]]:
        """
        Fetch 30-day HV and 52-week IV range (HV proxy) for each symbol.
        Returns dict: symbol -> (hv_30d, iv_52w_high, iv_52w_low).
        Falls back to (0.30, 0.60, 0.15) on any error — matches FeatureEngineer defaults.
        Cached with same TTL as chains to avoid redundant yfinance calls.
        """
        _FALLBACK = (0.30, 0.60, 0.15)

        async def fetch_one(symbol: str) -> tuple[str, tuple[float, float, float]]:
            cache_key = f"hv_data:{symbol}"
            cached = await self.cache.get(cache_key)
            if cached is not None:
                try:
                    parts = [float(x) for x in str(cached).split(",")]
                    if len(parts) == 3:
                        return symbol, (parts[0], parts[1], parts[2])
                except Exception:
                    pass
            try:
                iv_data = await self.yf.get_historical_iv(symbol)
                result = (
                    iv_data.get("current_iv", 0.30),
                    iv_data.get("iv_52w_high", 0.60),
                    iv_data.get("iv_52w_low", 0.15),
                )
                await self.cache.set(
                    cache_key,
                    f"{result[0]},{result[1]},{result[2]}",
                    self.settings.CACHE_TTL_CHAINS,
                )
                return symbol, result
            except Exception:
                return symbol, _FALLBACK

        results = await asyncio.gather(*[fetch_one(sym) for sym in symbols], return_exceptions=True)
        output: dict[str, tuple[float, float, float]] = {}
        for r in results:
            if isinstance(r, Exception):
                continue
            sym, val = r
            output[sym] = val
        return output


def _compute_iv_skew(calls: list, puts: list) -> float:
    """25-delta put IV minus 25-delta call IV — positive skew = fear premium."""
    otm_puts = [p for p in puts if 0.10 <= abs(p.delta) <= 0.40 and p.implied_volatility > 0]
    otm_calls = [c for c in calls if 0.10 <= c.delta <= 0.40 and c.implied_volatility > 0]
    if not otm_puts or not otm_calls:
        return 0.0
    put_25d = min(otm_puts, key=lambda p: abs(abs(p.delta) - 0.25))
    call_25d = min(otm_calls, key=lambda c: abs(c.delta - 0.25))
    return round(put_25d.implied_volatility - call_25d.implied_volatility, 4)


def _passes_ba_filter(spread: SpreadCandidate, max_pct: float) -> bool:
    """
    Direct bid-ask spread % check against each leg.
    Replaces the quality-score gate which was miscalibrated for LEAPS.
    A spread_pct > max_pct on any leg fails.  If bid=0 (no market), let it through
    so the quality score displayed in the UI reflects the actual situation.
    """
    def leg_ok(opt) -> bool:
        mid = (opt.bid + opt.ask) / 2
        if mid <= 0:
            return True  # can't compute — don't filter blind
        return (opt.ask - opt.bid) / mid <= max_pct

    if not leg_ok(spread.long_leg):
        return False
    if spread.short_leg and not leg_ok(spread.short_leg):
        return False
    return True


_LEAPS_TYPES = {SpreadType.LEAP_CALL, SpreadType.LEAP_PUT, SpreadType.LEAPS_SPREAD_CALL}
_EARNINGS_TYPES = {SpreadType.EARNINGS_CALL, SpreadType.EARNINGS_PUT}


def _apply_spread_filters(
    spreads: list[SpreadCandidate], filters: ScannerFilters
) -> list[SpreadCandidate]:
    """Filter spread candidates by delta, DTE, width, and cost constraints."""
    out = []
    for s in spreads:
        # DTE filter — checked per-spread to prevent cross-contamination when both
        # spread and LEAPS strategies are active (e.g. a LEAPS_SPREAD_CALL built from
        # a short-dated expiry that was valid for BULL_CALL).
        if s.spread_type in _LEAPS_TYPES:
            if not (filters.leaps_min_dte <= s.dte <= filters.leaps_max_dte):
                continue
        elif s.spread_type in _EARNINGS_TYPES:
            # Earnings plays target expirations that straddle the earnings date.
            # Use the general min/max_dte range as the contract DTE window —
            # the earnings proximity gate is enforced separately in scan().
            if not (filters.min_dte <= s.dte <= filters.max_dte):
                continue
        else:
            if not (filters.min_dte <= s.dte <= filters.max_dte):
                continue

        # Delta filter — applies to all spread types (absolute value of long leg delta)
        long_delta = abs(s.long_leg.delta)
        if long_delta < filters.min_long_delta or long_delta > filters.max_long_delta:
            continue

        # Absolute IV filter — long leg implied volatility
        long_iv = s.long_leg.implied_volatility
        if long_iv < filters.min_iv or long_iv > filters.max_iv:
            continue

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
        # Max debit as fraction of spread width — applied to all two-leg spreads
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
