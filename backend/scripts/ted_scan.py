"""Automated "The Ted" candidate scan.

Sweeps the universe for symbols with earnings 7-14 days out, pre-screens them on
the direction-independent gates, and caches the ranked list under the same key
the /ted/candidates API serves (`ted:candidates`). The TedPage candidates panel
then populates automatically — no manual ticker entry.

Does NOT require the FastAPI server; it builds its own yfinance client + cache.
Schedule it on weekdays (Windows Task Scheduler) to keep the list warm; it
self-skips weekends and NYSE holidays (exit 0) unless --allow-market-closed.

Usage:
    backend/.venv/Scripts/python.exe -m backend.scripts.ted_scan
    backend/.venv/Scripts/python.exe -m backend.scripts.ted_scan --limit 60
    backend/.venv/Scripts/python.exe -m backend.scripts.ted_scan --symbols AAPL,MSFT,NVDA
    backend/.venv/Scripts/python.exe -m backend.scripts.ted_scan --dry-run   # don't write cache
"""

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# UTF-8 stdout/stderr guard (HANDOFF §6) — cp1252 consoles/redirected logs crash
# on non-latin glyphs. errors="replace" is a belt-and-suspenders fallback.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger(__name__)


async def _run(symbols: list[str], concurrency: int, write_cache: bool) -> dict:
    import redis.asyncio as aioredis

    from backend.api.cache import RedisCache
    from backend.config.settings import get_settings
    from backend.data.yfinance_client import YFinanceClient
    from backend.scanner.ted_scanner import (
        CANDIDATES_CACHE_KEY,
        CANDIDATES_TTL,
        build_candidate_payload,
    )

    from backend.ml import ted_outcomes

    settings = get_settings()
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    cache = RedisCache(redis_client)
    try:
        await redis_client.ping()
        logger.info("Redis connected: %s", settings.REDIS_URL)
    except Exception as e:
        logger.warning("Redis unavailable (%s) — per-symbol earnings cache disabled.", e)

    yf_client = YFinanceClient()

    logger.info("Sweeping %d symbols (concurrency=%d) for earnings 7-14 days out…",
                len(symbols), concurrency)
    payload = await build_candidate_payload(
        symbols, yf_client, cache, concurrency=concurrency
    )

    if write_cache:
        await cache.set(CANDIDATES_CACHE_KEY, payload, CANDIDATES_TTL)
        logger.info("Cached under '%s' (TTL %dh).", CANDIDATES_CACHE_KEY, CANDIDATES_TTL // 3600)
        n_logged = ted_outcomes.log_candidates(payload)
        logger.info("Track record: logged/updated %d qualifying candidate(s).", n_logged)
    else:
        logger.info("[dry-run] cache + track record not written.")

    try:
        await redis_client.aclose()
    except Exception:
        pass
    return payload


async def _run_label() -> dict:
    """Read exit-time IV for rows whose exit_by has passed and record the buildup."""
    from backend.data.yfinance_client import YFinanceClient
    from backend.ml import ted_outcomes
    from backend.scanner.ted_scanner import atm_quote

    yf_client = YFinanceClient()
    due = ted_outcomes.due_for_label()
    logger.info("%d row(s) due for labeling.", len(due))
    for row in due:
        expiry, side = row.get("expiry"), row.get("option_side") or "call"
        exit_iv = exit_price = None
        if expiry:
            q = await atm_quote(yf_client, row["symbol"], expiry, side)
            if q is not None:
                exit_iv, exit_price = q["iv"], q["price"]
        ted_outcomes.record_outcome(row["id"], exit_iv, exit_price)
        logger.info(
            "  %s: entry IV %s → exit IV %s",
            row["symbol"], row.get("entry_iv"), exit_iv,
        )
    return ted_outcomes.summary()


def _row(c: dict) -> str:
    ivr = c.get("iv_room")
    ivr_txt = "Y" if ivr else ("·" if ivr is None else "N")
    eiv = c.get("entry_iv")
    eiv_txt = f"{eiv:.0f}%" if eiv else "—"
    direction = (c.get("inferred_direction") or "—")[:4]
    gates = (f"{c['gates_passed']}/{c['gates_total']}"
             if c.get("gates_passed") is not None else "—")
    big = f"{c['big_mover_count']}/8"
    att = "Y" if c["attention"] else "·"
    return (f"  {c['symbol']:<7}{c['days_out']:>5}  "
            f"{(c['qualifying_expiry'] or '—'):<11}{direction:>5}{eiv_txt:>8}"
            f"{ivr_txt:>7}{big:>6}{att:>5}{gates:>7}")


def _print_summary(payload: dict) -> None:
    cands = payload["candidates"]
    qual = [c for c in cands if c["qualifies"]]
    tier1 = [c for c in cands if c.get("tier") == "pass_all"]
    tier2 = [c for c in cands if c.get("tier") == "pass_most"]
    hdr = (f"  {'SYM':<7}{'days':>5}  {'exp(1-2d)':<11}{'dir':>5}{'entryIV':>8}"
           f"{'ivRoom':>7}{'bigMv':>6}{'att':>5}{'gates':>7}")

    print("=" * 78)
    print(f"Ted candidates — window {payload['window']['from']} .. {payload['window']['to']}")
    print(f"  {len(cands)} in window · {len(qual)} qualifying (Gate 1+2) · "
          f"{len(tier1)} pass-all · {len(tier2)} pass-most")
    print("  (gates = auto-evaluable gates passed for the trend-inferred direction;")
    print("   Gate 5 contra-catalyst + Gate 3 sizing are still yours to confirm.)")

    print("\n  TIER 1 — passes ALL auto gates (TRADE-ready, pending your G3/G5 confirm)")
    print("-" * 78)
    print(hdr)
    print("-" * 78)
    for c in tier1:
        print(_row(c))
    if not tier1:
        print("  (none today)")

    print("\n  TIER 2 — passes MOST gates (CAUTION — review the flags)")
    print("-" * 78)
    print(hdr)
    print("-" * 78)
    for c in tier2:
        print(_row(c))
    if not tier2:
        print("  (none today)")
    print("=" * 78)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Automated Ted candidate scan.")
    ap.add_argument("--symbols", help="Comma-separated symbols instead of the full universe.")
    ap.add_argument("--limit", type=int, default=0, help="Cap the universe to the first N symbols.")
    ap.add_argument("--concurrency", type=int, default=8, help="Max concurrent yfinance calls.")
    ap.add_argument("--dry-run", action="store_true", help="Don't write the cache / track record.")
    ap.add_argument("--label", action="store_true",
                    help="Read exit IV for due track-record rows instead of scanning.")
    ap.add_argument("--allow-market-closed", action="store_true",
                    help="Run even on a weekend or NYSE holiday (quotes will be "
                         "stale). By default the scan skips non-trading days.")
    args = ap.parse_args()

    # Only run on NYSE trading days. yfinance still answers when the market is
    # shut — it serves the prior session's stale chain — so a weekend/holiday
    # run would cache stale entry IVs and log bad track-record rows. Skip before
    # any work; exit 0 because a non-trading day is the expected outcome, not a
    # failure. --dry-run is exempt (writes nothing); --allow-market-closed forces
    # a real run.
    from backend.data.market_calendar import market_closed_reason
    closed = market_closed_reason(date.today())
    if closed and not (args.allow_market_closed or args.dry_run):
        logger.info(
            "Market closed — %s (%s). Skipping Ted scan. "
            "Use --allow-market-closed to override.",
            closed, date.today().strftime("%A %Y-%m-%d"),
        )
        sys.exit(0)
    if closed:
        logger.warning(
            "Market closed (%s) — running anyway (%s).",
            closed, "dry-run" if args.dry_run else "--allow-market-closed set",
        )

    if args.label:
        from backend.ml import ted_outcomes
        try:
            asyncio.run(_run_label())
        except Exception as e:
            logger.exception("Ted labeling failed: %s", e)
            sys.exit(1)
        s = ted_outcomes.summary()
        print("=" * 68)
        print(f"Ted track record: {s['total']} logged · {s['open']} open · "
              f"{s['labeled']} labeled")
        if s["labeled"]:
            print(f"  Mean IV buildup (entry→exit): {s['avg_iv_change']} pts · "
                  f"{s['iv_up']}/{s['labeled']} built IV")
        print("=" * 68)
        return

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        from backend.scanner.universe import DEFAULT_UNIVERSE
        symbols = list(DEFAULT_UNIVERSE)
        if args.limit > 0:
            symbols = symbols[: args.limit]

    try:
        payload = asyncio.run(_run(symbols, args.concurrency, write_cache=not args.dry_run))
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(1)
    except Exception as e:
        logger.exception("Ted scan failed: %s", e)
        sys.exit(1)

    _print_summary(payload)

    if not args.dry_run:
        from backend.ml import ted_outcomes
        s = ted_outcomes.summary()
        extra = f" · mean IV buildup {s['avg_iv_change']}pts" if s["labeled"] else ""
        print(f"Track record: {s['total']} logged · {s['open']} open · "
              f"{s['labeled']} labeled{extra}")


if __name__ == "__main__":
    main()
