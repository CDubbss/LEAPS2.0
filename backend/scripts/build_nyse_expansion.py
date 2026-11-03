"""Source + liquidity-filter the NYSE-expansion universe tier (Schwab-backed).

Pulls NYSE-listed common stocks from the free Nasdaq Trader symbol directory,
drops anything already in the core ``DEFAULT_UNIVERSE``, and keeps the names that
clear liquidity + optionability gates. Writes the survivors to
``backend/scanner/data/nyse_expansion.txt``; ``universe.py`` loads that file as
``_NYSE_EXPANSION``.

Why Schwab and not yfinance:
  The first cut used yfinance to probe each symbol's option chain. A full ~2,000
  symbol sweep tripped yfinance's options rate limit partway through, and the
  probe swallowed the ``YFRateLimitError`` as "no-options" — silently truncating
  the universe to the alphabetical first half with no error. Schwab is the
  scanner's PRIMARY options source (authenticated, ~120 req/min, no scraping
  throttle), so a name that passes here is one the live scanner can actually
  trade. Every Schwab failure is retried and, if still failing, recorded as
  ``error`` / UNRESOLVED — never as a clean gate result.

Gates (all sourced from Schwab):
  - price >= --min-price                 (quote.lastPrice / quote.mark)
  - avg volume >= --min-volume           (fundamental.avg1YearVolume, else avg10DaysVolume)
  - market cap >= --min-market-cap       (price * fundamental.sharesOutstanding) -- BEST-EFFORT:
        enforced only when shares are reported; names whose shares Schwab does not
        report (common for ADRs, e.g. VALE) PASS this gate flagged, so the other
        three gates decide them rather than a missing data field.
  - optionable with a LEAPS-dated expiry >= 365 DTE   (get_expirations)

Pipeline (two passes to keep per-symbol chain calls cheap):
  1. Batch quote screen  -> price / volume / market cap, ~1 Schwab call per 200 names.
  2. Per-survivor LEAPS   -> one chain call each, rate-paced to ~100/min.

Prerequisite: a valid Schwab token (``backend/scripts/schwab_auth``). The token is
valid 7 days from auth; this prints the remaining lifetime at startup.

    python -m backend.scripts.build_nyse_expansion --limit 40 --dry-run   # quick smoke
    python -m backend.scripts.build_nyse_expansion --dry-run              # full sweep, review file only
    python -m backend.scripts.build_nyse_expansion                        # full sweep -> live list (only if clean)
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# UTF-8 stdout/stderr guard (HANDOFF §6) — cp1252 consoles crash on non-latin glyphs.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("build_nyse_expansion")

NASDAQ_TRADER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
OUT_FILE = _PROJECT_ROOT / "backend" / "scanner" / "data" / "nyse_expansion.txt"
REVIEW_FILE = _PROJECT_ROOT / "backend" / "scanner" / "data" / "nyse_expansion.review.txt"

LEAPS_MIN_DTE = 365
DEFAULT_MIN_PRICE = 10.0
DEFAULT_MIN_AVG_VOLUME = 500_000
DEFAULT_MIN_MARKET_CAP = 2_000_000_000.0

# Schwab pacing. Their market-data tier allows ~120 req/min; stay comfortably under.
QUOTE_BATCH_SIZE = 200          # symbols per batched get_quotes call
LEAPS_CHUNK = 40                # concurrent-ish chain probes per paced chunk
LEAPS_TARGET_RATE_PER_MIN = 100


# --------------------------------------------------------------------------- #
# Symbol directory (free, unlimited — no throttle)
# --------------------------------------------------------------------------- #

def fetch_nyse_commons(exchanges: tuple[str, ...] = ("N",)) -> list[str]:
    """NYSE-listed common-stock tickers from the Nasdaq Trader directory.

    Pipe-delimited columns: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|
    Round Lot Size|Test Issue|NASDAQ Symbol. Exchange codes: N=NYSE,
    A=NYSE American, P=NYSE Arca. Drops ETFs, test issues, and non-plain tickers
    (dots/suffixes => preferred shares, warrants, units, when-issued).
    """
    req = Request(NASDAQ_TRADER_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    rows = text.splitlines()
    if not rows:
        return []
    header = rows[0].split("|")
    idx = {name: i for i, name in enumerate(header)}
    try:
        c_sym, c_exch, c_etf, c_test = (
            idx["ACT Symbol"], idx["Exchange"], idx["ETF"], idx["Test Issue"])
    except KeyError as e:
        raise RuntimeError(f"Unexpected symbol-directory format (missing {e})") from e

    out: set[str] = set()
    for line in rows[1:]:
        if line.startswith("File Creation Time"):   # directory trailer
            continue
        parts = line.split("|")
        if len(parts) <= c_test:
            continue
        sym = parts[c_sym].strip().upper()
        if parts[c_exch].strip() not in exchanges:
            continue
        if parts[c_etf].strip() == "Y" or parts[c_test].strip() == "Y":
            continue
        if not sym or not sym.isalpha() or len(sym) > 5:
            continue
        out.add(sym)
    return sorted(out)


# --------------------------------------------------------------------------- #
# Pure gate logic (network-free — unit-tested directly)
# --------------------------------------------------------------------------- #

def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def normalize_quote(entry: dict) -> dict:
    """Extract {price, avg_volume, shares, market_cap} from a raw Schwab quote entry.

    - price: quote.lastPrice, falling back to quote.mark.
    - avg_volume: fundamental.avg1YearVolume (stable long-run liquidity),
      falling back to fundamental.avg10DaysVolume.
    - shares: fundamental.sharesOutstanding (absent for some ADRs/foreign names).
    - market_cap: price * shares, or None when either input is missing.
    Any value that is missing or non-numeric becomes None rather than raising.
    """
    q = entry.get("quote", {}) or {}
    f = entry.get("fundamental", {}) or {}

    def _num(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    price = _num(q.get("lastPrice")) or _num(q.get("mark"))
    avg_vol = _num(f.get("avg1YearVolume")) or _num(f.get("avg10DaysVolume"))
    shares = _num(f.get("sharesOutstanding"))
    mcap = price * shares if (price and shares) else None
    return {"price": price, "avg_volume": avg_vol, "shares": shares, "market_cap": mcap}


def screen_quote(norm: dict, *, min_price: float, min_vol: float,
                 min_mcap: float) -> tuple[bool, str]:
    """(kept, reason) for the price/volume/market-cap screen.

    Price and average volume are HARD gates (missing => dropped as 'missing-data').
    Market cap is BEST-EFFORT: enforced when derivable, but a name whose shares
    outstanding Schwab does not report passes with reason 'ok-mcap-unknown' so the
    other gates decide it (avoids dropping liquid ADRs on a missing data field).
    """
    price = norm.get("price")
    vol = norm.get("avg_volume")
    mcap = norm.get("market_cap")
    if price is None or vol is None:
        return False, "missing-data"
    if price < min_price:
        return False, "low-price"
    if vol < min_vol:
        return False, "low-volume"
    if mcap is not None and mcap < min_mcap:
        return False, "low-mcap"
    return True, "ok" if mcap is not None else "ok-mcap-unknown"


def has_leaps_expiry(expirations: list[str], today: date,
                     min_dte: int = LEAPS_MIN_DTE) -> bool:
    """True if any expiration is >= min_dte days out (a LEAPS-dated contract)."""
    cutoff = today + timedelta(days=min_dte)
    for e in expirations:
        d = _parse_date(e)
        if d and d >= cutoff:
            return True
    return False


# --------------------------------------------------------------------------- #
# Schwab passes (retry/back off; failures => UNRESOLVED, never a clean result)
# --------------------------------------------------------------------------- #

async def _with_retry(factory, *, what: str, retries: int = 3, base_delay: float = 2.0):
    """Await factory(); on any exception retry with exponential backoff, then re-raise."""
    for attempt in range(retries + 1):
        try:
            return await factory()
        except Exception as e:
            if attempt == retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning("  %s failed (%s) — retry %d/%d in %.0fs",
                           what, e.__class__.__name__, attempt + 1, retries, delay)
            await asyncio.sleep(delay)


async def quote_screen(client, candidates: list[str], *, min_price: float,
                       min_vol: float, min_mcap: float,
                       batch_size: int = QUOTE_BATCH_SIZE):
    """Pass 1: batched price/volume/market-cap screen.

    Returns (survivors, reasons, mcap_unknown, unresolved). A batch that keeps
    failing after retries puts its whole batch into `unresolved` (counted under
    reason 'error') — it is NOT recorded as a clean drop.
    """
    survivors: list[str] = []
    reasons: dict[str, int] = {}
    mcap_unknown = 0
    unresolved: list[str] = []

    total = len(candidates)
    for i in range(0, total, batch_size):
        batch = candidates[i:i + batch_size]
        try:
            raw = await _with_retry(lambda b=batch: client.get_quotes_raw(b),
                                    what=f"quote batch [{i}:{i + len(batch)}]")
        except Exception as e:
            logger.error("  quote batch [%d:%d] UNRESOLVED after retries: %s",
                         i, i + len(batch), e)
            unresolved.extend(batch)
            reasons["error"] = reasons.get("error", 0) + len(batch)
            continue

        for sym in batch:
            entry = raw.get(sym)
            if entry is None:
                # Schwab grouped it under "errors" — not a tradeable symbol for us.
                reasons["unknown-symbol"] = reasons.get("unknown-symbol", 0) + 1
                continue
            norm = normalize_quote(entry)
            ok, why = screen_quote(norm, min_price=min_price, min_vol=min_vol,
                                   min_mcap=min_mcap)
            reasons[why] = reasons.get(why, 0) + 1
            if ok:
                survivors.append(sym)
                if norm["market_cap"] is None:
                    mcap_unknown += 1

        logger.info("  quote-screened %d/%d — %d survivors",
                    min(i + batch_size, total), total, len(survivors))
        await asyncio.sleep(0.5)  # gentle between batches

    return sorted(set(survivors)), reasons, mcap_unknown, unresolved


async def leaps_screen(client, survivors: list[str], today: date, *,
                       min_dte: int = LEAPS_MIN_DTE, chunk: int = LEAPS_CHUNK,
                       target_rate_per_min: int = LEAPS_TARGET_RATE_PER_MIN):
    """Pass 2: per-survivor optionability + LEAPS-expiry check, rate-paced.

    Returns (kept, reasons, unresolved). A symbol whose chain call keeps failing
    goes into `unresolved` (reason 'error') — crucially NOT bucketed as
    'no-options', which was the old silent-truncation failure mode.
    """
    kept: list[str] = []
    reasons: dict[str, int] = {}
    unresolved: list[str] = []
    total = len(survivors)
    min_chunk_seconds = chunk / (target_rate_per_min / 60.0) if target_rate_per_min else 0.0

    async def _one(sym: str):
        try:
            exps = await _with_retry(lambda: client.get_expirations(sym),
                                     what=f"expiries {sym}")
            return sym, exps, None
        except Exception as e:
            return sym, None, e

    for i in range(0, total, chunk):
        t0 = time.monotonic()
        batch = survivors[i:i + chunk]
        for sym, exps, err in await asyncio.gather(*[_one(s) for s in batch]):
            if err is not None:
                unresolved.append(sym)
                reasons["error"] = reasons.get("error", 0) + 1
            elif not exps:
                reasons["no-options"] = reasons.get("no-options", 0) + 1
            elif has_leaps_expiry(exps, today, min_dte):
                kept.append(sym)
                reasons["ok"] = reasons.get("ok", 0) + 1
            else:
                reasons["no-leaps"] = reasons.get("no-leaps", 0) + 1

        logger.info("  LEAPS-checked %d/%d — %d kept",
                    min(i + chunk, total), total, len(kept))
        elapsed = time.monotonic() - t0
        if elapsed < min_chunk_seconds:
            await asyncio.sleep(min_chunk_seconds - elapsed)

    return sorted(set(kept)), reasons, unresolved


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def _render(survivors: list[str], unresolved: list[str], args, exchanges,
            mcap_unknown: int) -> str:
    lines = [
        f"# NYSE expansion tier — generated {datetime.now().isoformat(timespec='seconds')}",
        f"# source: Schwab (quotes + option chains); symbol list: {NASDAQ_TRADER_URL}",
        f"# gates: price>={args.min_price} avg_vol>={args.min_volume} "
        f"mcap>={args.min_market_cap:.0f} (best-effort) LEAPS>={LEAPS_MIN_DTE}d "
        f"exchanges={exchanges}",
        f"# {len(survivors)} symbols, disjoint from the core DEFAULT_UNIVERSE "
        f"({mcap_unknown} kept with market cap unknown)",
    ]
    if unresolved:
        lines.append(
            f"# WARNING: {len(unresolved)} symbol(s) UNRESOLVED (Schwab errors) and "
            f"NOT screened: {', '.join(unresolved[:40])}{' …' if len(unresolved) > 40 else ''}"
        )
    lines += ["", *survivors]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

async def _run(args) -> int:
    from backend.config.settings import get_settings
    from backend.data.schwab_client import SchwabClient
    from backend.scanner.universe import DEFAULT_UNIVERSE

    settings = get_settings()
    client = SchwabClient(
        app_key=settings.SCHWAB_APP_KEY,
        app_secret=settings.SCHWAB_APP_SECRET,
        token_path=settings.SCHWAB_TOKEN_PATH,
    )
    if not client.is_available:
        logger.error(
            "Schwab client unavailable — options sourcing needs a valid token. "
            "Run: backend\\.venv\\Scripts\\python.exe -m backend.scripts.schwab_auth"
        )
        return 2
    days = client.token_days_remaining()
    if days is not None:
        logger.info("Schwab token ~%.1f day(s) of refresh lifetime remaining.", days)
        if days < 0.5:
            logger.warning("Schwab token is nearly expired — re-auth before a long sweep.")

    core = set(DEFAULT_UNIVERSE)
    today = date.today()
    exchanges = tuple(x.strip().upper() for x in args.exchanges.split(",") if x.strip())

    logger.info("Fetching NYSE symbol directory (exchanges=%s)...", exchanges)
    commons = fetch_nyse_commons(exchanges)
    candidates = [s for s in commons if s not in core]
    logger.info("%d NYSE commons; %d remain after removing the core universe.",
                len(commons), len(candidates))
    if args.limit > 0:
        candidates = candidates[: args.limit]
        logger.info("Capped to %d candidates for this run.", len(candidates))

    logger.info("Pass 1/2 — batch quote screen (price/volume/market-cap)...")
    survivors, q_reasons, mcap_unknown, unresolved_q = await quote_screen(
        client, candidates, min_price=args.min_price, min_vol=args.min_volume,
        min_mcap=args.min_market_cap,
    )
    logger.info("Quote screen: %d survivors (%d mcap-unknown). Drops: %s",
                len(survivors), mcap_unknown,
                dict(sorted(q_reasons.items(), key=lambda kv: -kv[1])))

    logger.info("Pass 2/2 — per-survivor LEAPS optionability (%d names)...", len(survivors))
    kept, l_reasons, unresolved_l = await leaps_screen(client, survivors, today)
    logger.info("LEAPS screen: %d kept. Results: %s",
                len(kept), dict(sorted(l_reasons.items(), key=lambda kv: -kv[1])))

    unresolved = sorted(set(unresolved_q) | set(unresolved_l))
    logger.info("KEPT %d / %d candidates. UNRESOLVED (Schwab errors): %d",
                len(kept), len(candidates), len(unresolved))

    body = _render(kept, unresolved, args, exchanges, mcap_unknown)

    # Never silently ship a truncated universe: a live write requires a clean
    # sweep (unresolved <= --max-unresolved). Otherwise fall back to a review file.
    if args.dry_run:
        REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_FILE.write_text(body, encoding="utf-8")
        logger.info("[dry-run] wrote REVIEW file (not the live list): %s", REVIEW_FILE)
        return 0

    if len(unresolved) > args.max_unresolved:
        REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_FILE.write_text(body, encoding="utf-8")
        logger.error(
            "REFUSING to write the live list: %d symbol(s) unresolved (Schwab errors) "
            "exceeds --max-unresolved=%d. Wrote REVIEW file instead: %s. "
            "Re-run when the sweep is clean.",
            len(unresolved), args.max_unresolved, REVIEW_FILE,
        )
        return 3

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(body, encoding="utf-8")
    logger.info("Wrote live expansion list: %s", OUT_FILE)
    logger.info("Restart any running backend and re-run setup_scheduler.ps1 if the "
                "NYSE task isn't registered yet.")
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Build the NYSE-expansion universe tier (Schwab-backed).")
    ap.add_argument("--min-price", type=float, default=DEFAULT_MIN_PRICE)
    ap.add_argument("--min-volume", type=int, default=DEFAULT_MIN_AVG_VOLUME)
    ap.add_argument("--min-market-cap", type=float, default=DEFAULT_MIN_MARKET_CAP)
    ap.add_argument("--exchanges", default="N",
                    help="Comma list of NYSE codes: N=NYSE, A=NYSE American, P=NYSE Arca.")
    ap.add_argument("--limit", type=int, default=0, help="Cap candidates (for a quick test run).")
    ap.add_argument("--max-unresolved", type=int, default=0,
                    help="Max Schwab-error symbols tolerated before refusing a live write.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Write a .review.txt copy + print, but DON'T touch the live list.")
    args = ap.parse_args()

    try:
        rc = asyncio.run(_run(args))
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
