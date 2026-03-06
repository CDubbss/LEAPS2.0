"""
Diagnostic script — run from project root:
    python diag_scan.py

Phase 1: Confirms spreads are built (already passing).
Phase 2: Simulates the FULL post-construction pipeline to find which
         filter is rejecting all candidates.
"""

import asyncio
import random
from datetime import date

TEST_SYMBOLS = ["SPY", "AAPL"]   # small subset to keep it fast


async def main():
    from backend.data.yfinance_client import YFinanceClient
    from backend.scanner.spread_constructor import SpreadConstructor
    from backend.scanner.options_filter import OptionsFilter
    from backend.scanner.fundamentals_scorer import FundamentalsScorer
    from backend.scanner.risk_scorer import RiskScorer
    from backend.models.options import SpreadType
    from backend.models.scanner import ScannerFilters
    from backend.models.fundamentals import FundamentalData
    from backend.models.sentiment import TickerSentiment
    from backend.models.ml import MLPrediction
    from backend.scanner.scanner import _passes_ba_filter, _apply_spread_filters, _neutral_sentiment

    yf = YFinanceClient()
    sc = SpreadConstructor()
    fund_scorer = FundamentalsScorer()
    risk_scorer = RiskScorer()
    today = date.today()

    # Use the same defaults the UI sends
    filters = ScannerFilters(
        strategies=["leap_call", "leaps_spread_call"],
        leaps_min_dte=250,
        leaps_max_dte=730,
        min_dte=30,
        max_dte=90,
        min_long_delta=0.0,
        max_long_delta=1.0,
        max_bid_ask_spread_pct=0.50,
        min_ml_quality_score=45.0,
        min_fundamental_score=40.0,
        min_sentiment_score=35.0,
        min_probability_of_profit=0.45,
        max_debit_pct_of_spread=0.25,
        target_spread_widths=[],
        max_spread_width=None,
        max_net_debit=None,
    )

    print(f"\n{'='*60}")
    print(f"Full pipeline simulation — {today}")
    print(f"Filters: leaps_min_dte={filters.leaps_min_dte}, "
          f"max_ba={filters.max_bid_ask_spread_pct*100:.0f}%, "
          f"min_ml={filters.min_ml_quality_score}, "
          f"min_pop={filters.min_probability_of_profit}, "
          f"min_fund={filters.min_fundamental_score}, "
          f"min_sent={filters.min_sentiment_score}")
    print(f"{'='*60}\n")

    all_candidates = []

    for symbol in TEST_SYMBOLS:
        print(f"--- {symbol} ---")
        try:
            quote = await yf.get_quote(symbol)
            spot = quote["price"]
            if spot <= 0:
                print("  SKIP: spot=0")
                continue

            expirations = await yf.get_expirations(symbol)
            valid_expiries = []
            for exp in expirations:
                try:
                    dte = (date.fromisoformat(exp) - today).days
                except ValueError:
                    continue
                if filters.leaps_min_dte <= dte <= filters.leaps_max_dte:
                    valid_expiries.append(exp)

            print(f"  Valid expiries: {valid_expiries[:8]}")

            for expiry in valid_expiries[:3]:   # limit to 3 for speed
                calls, puts = await yf.get_options_chain(symbol, expiry, spot)
                raw = sc.build_all_spreads(
                    calls=calls, puts=puts,
                    strategies=filters.strategies,
                    spot_price=spot,
                )
                ba_ok = [s for s in raw if _passes_ba_filter(s, filters.max_bid_ask_spread_pct)]
                filtered = _apply_spread_filters(ba_ok, filters)
                dte_val = (date.fromisoformat(expiry) - today).days
                print(f"  {expiry} ({dte_val}d): raw={len(raw)} ba_ok={len(ba_ok)} spread_filter_ok={len(filtered)}")
                all_candidates.extend(filtered)

        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\nTotal candidates after construction+spread filters: {len(all_candidates)}")
    if not all_candidates:
        print(">>> PROBLEM IS IN CONSTRUCTION or SPREAD FILTERS (already shown above)")
        return

    # ----------------------------------------------------------------
    # Simulate ML quality filter
    # ----------------------------------------------------------------
    def placeholder_ml_score(cand) -> float:
        base = 40.0
        base += cand.probability_of_profit * 20
        base += cand.bid_ask_quality_score * 20
        # deterministic (no random) so we see the base score
        return max(20.0, min(80.0, base))

    reject_ml = reject_pop = reject_fund = reject_sent = 0
    pass_all = 0

    # Neutral sentiment/fundamentals (simulates FMP/FinBERT working normally)
    neutral_fund = fund_scorer.score(FundamentalData(symbol="TEST"))
    neutral_sent = _neutral_sentiment("TEST")

    ml_scores = []
    for cand in all_candidates:
        ml_score = placeholder_ml_score(cand)
        ml_scores.append(ml_score)

        if ml_score < filters.min_ml_quality_score:
            reject_ml += 1
            continue
        if cand.probability_of_profit < filters.min_probability_of_profit:
            reject_pop += 1
            continue
        if (neutral_fund.fundamental_score or 0) < filters.min_fundamental_score:
            reject_fund += 1
            continue
        if neutral_sent.sentiment_score < filters.min_sentiment_score:
            reject_sent += 1
            continue
        pass_all += 1

    print(f"\n--- Post-construction filter breakdown ---")
    print(f"  ML scores range: {min(ml_scores):.1f} – {max(ml_scores):.1f}  (min required: {filters.min_ml_quality_score})")
    print(f"  PoP range: {min(c.probability_of_profit for c in all_candidates):.3f} – "
          f"{max(c.probability_of_profit for c in all_candidates):.3f}  (min required: {filters.min_probability_of_profit})")
    print(f"  Neutral fundamental_score: {neutral_fund.fundamental_score}  (min required: {filters.min_fundamental_score})")
    print(f"  Neutral sentiment_score:   {neutral_sent.sentiment_score}  (min required: {filters.min_sentiment_score})")
    print()
    print(f"  Rejected by ML quality:     {reject_ml}")
    print(f"  Rejected by PoP:            {reject_pop}")
    print(f"  Rejected by fundamental:    {reject_fund}")
    print(f"  Rejected by sentiment:      {reject_sent}")
    print(f"  >>> PASSED ALL FILTERS:     {pass_all}")

    if pass_all == 0:
        # Show sample candidates to understand why
        print(f"\nSample candidates that failed:")
        for cand in all_candidates[:5]:
            ml = placeholder_ml_score(cand)
            print(f"  {cand.spread_type.value} {cand.underlying} "
                  f"strike={cand.long_leg.strike:.0f} "
                  f"dte={cand.dte} "
                  f"pop={cand.probability_of_profit:.3f} "
                  f"ba_quality={cand.bid_ask_quality_score:.3f} "
                  f"ml_score={ml:.1f} "
                  f"delta={cand.long_leg.delta:.3f}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
