"""
"The Ted" — Earnings IV-Buildup gate checker (ported from the standalone CLI,
IV-Buildup Gate Checklist v1.3, 14 gates).

Strategy: buy a single call/put 7-14 days before earnings, expiry 1-2 days past
the print, exit BEFORE earnings. Profits from IV building into the event, not
the outcome.

Pure logic module — no FastAPI, no I/O. The route layer gathers market data and
this module evaluates every gate (unlike the CLI, a hard fail does not stop
evaluation — the UI shows the full checklist with a NO TRADE verdict).
"""

from datetime import date, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Thresholds — ported verbatim from app.py v1.3
MIN_DAYS_OUT = 7
MAX_DAYS_OUT = 14
IDEAL_DAYS_LOW, IDEAL_DAYS_HIGH = 10, 12
MIN_EXPIRY_PAST, MAX_EXPIRY_PAST = 1, 2
MIN_ACCOUNT_PCT = 50.0
IV_EXCESS_LIMIT = 20.0          # Gate 12: current IV must be < 90d avg + 20pts
THETA_RATIO_LIMIT = 30.0        # Gate 13: theta drag < 30% of projected IV gain
BIG_MOVE_PCT = 8.0              # Gate 7: "big mover" = 8%+ post-earnings move
BIG_MOVE_MIN_COUNT = 3          # ...in at least 3 of the last 8 earnings
ATTENTION_MIN_MCAP = 10e9       # Gate 6 proxy
ATTENTION_MIN_CHAIN_OI = 10_000
LIQUIDITY_MIN_OI = 200          # Gate 8
LIQUIDITY_MAX_SPREAD_PCT = 0.10
CHEAP_OPTION_PRICE = 5.0        # sizing: cap 2 contracts if <$5 and <10 days
CHEAP_OPTION_MAX_CONTRACTS = 2


class TedInputs(BaseModel):
    """User-provided inputs (the interactive parts of the CLI)."""
    symbol: str
    direction: Literal["bull", "bear"]
    account_balance: float = Field(gt=0)
    contracts: int = Field(default=1, ge=1)
    expected_iv_gain: float = Field(default=10.0, gt=0, description="Expected IV point gain over hold")
    bmo_amc: Literal["bmo", "amc"] = "amc"
    no_contra: bool = Field(default=False, description="User confirmed no contra-catalysts before exit")
    # Manual overrides for gates whose auto-detection may be unavailable
    attention_override: Optional[bool] = None
    analyst_override: Optional[bool] = None


class TedMarketData(BaseModel):
    """Auto-gathered market data (the route layer fills this)."""
    earnings_date: Optional[date] = None
    expiration: Optional[date] = None          # chosen/qualifying expiry
    option_price: Optional[float] = None       # per share, chosen contract
    theta_per_day: Optional[float] = None      # $ per contract per day (positive)
    vega: Optional[float] = None               # per share
    market_cap: Optional[float] = None
    chain_total_oi: Optional[int] = None
    strike_oi: Optional[int] = None
    strike_bid: Optional[float] = None
    strike_ask: Optional[float] = None
    current_iv: Optional[float] = None         # percent, e.g. 45.0
    avg_iv_90: Optional[float] = None          # percent (HV-proxy approximation)
    past_moves: list[float] = Field(default_factory=list, description="Abs % next-day moves, last 8 earnings")
    price_drift_ok: Optional[bool] = None      # Gate 10
    sector_trend_ok: Optional[bool] = None     # Gate 11
    sector_etf: Optional[str] = None
    analyst_aligned: Optional[bool] = None     # Gate 9 (None = data unavailable)


class GateResult(BaseModel):
    num: int
    name: str
    status: Literal["pass", "warn", "fail", "manual"]
    detail: str = ""
    hard: bool = False
    auto: bool = True


class TedReport(BaseModel):
    symbol: str
    direction: str
    option_type: str
    days_out: Optional[int]
    gates: list[GateResult]
    iv_score: int          # of 6
    dir_score: int         # of 3
    hard_fails: list[int]
    verdict: Literal["TRADE", "CAUTION", "WEAK", "NO_TRADE"]
    verdict_detail: str
    sizing_notes: list[str]
    recommended_contracts: int
    total_cost: Optional[float]
    pct_of_account: Optional[float]
    exit_by: Optional[date]
    exit_window_text: str


def _exit_timing(earnings_date: date, bmo_amc: str) -> tuple[date, str]:
    """Port of the CLI's exit-timing block (lines 364-378)."""
    if bmo_amc == "amc":
        return earnings_date, (
            f"Exit {earnings_date.strftime('%a %b %d')} before close "
            "(3:00-3:45 PM EDT / 1:00-1:45 PM MDT). Never hold through the print."
        )
    exit_day = earnings_date - timedelta(days=1)
    while exit_day.weekday() >= 5:
        exit_day -= timedelta(days=1)
    return exit_day, (
        f"Exit prior day EOD — {exit_day.strftime('%a %b %d')} "
        "(3:00-3:30 PM EDT / 1:00-1:30 PM MDT). Never hold overnight into earnings."
    )


def evaluate_gates(inp: TedInputs, md: TedMarketData, today: Optional[date] = None) -> TedReport:
    today = today or date.today()
    gates: list[GateResult] = []
    hard_fails: list[int] = []
    iv_score = 0
    dir_score = 0
    sizing_notes: list[str] = []
    weekend_flag = False
    option_type = "CALL" if inp.direction == "bull" else "PUT"

    def add(num, name, status, detail="", hard=False, auto=True):
        gates.append(GateResult(num=num, name=name, status=status, detail=detail, hard=hard, auto=auto))
        if hard and status == "fail":
            hard_fails.append(num)

    # ── Gate 01 — earnings timing ────────────────────────────────────
    days_out: Optional[int] = None
    if md.earnings_date is None:
        add(1, "Earnings date unknown", "fail",
            "No confirmed earnings date from FMP or yfinance.", hard=True)
    else:
        days_out = (md.earnings_date - today).days
        if days_out < MIN_DAYS_OUT:
            add(1, f"Earnings {days_out}d out — below {MIN_DAYS_OUT}-day minimum", "fail",
                "IV already peaked. Too late to capture the buildup.", hard=True)
        elif days_out > MAX_DAYS_OUT:
            add(1, f"Earnings {days_out}d out — above {MAX_DAYS_OUT}-day maximum", "fail",
                "Too early — theta drag without IV. Check back later.", hard=True)
        elif IDEAL_DAYS_LOW <= days_out <= IDEAL_DAYS_HIGH:
            add(1, f"Earnings {days_out}d out — ideal window (10-12 days)", "pass")
        else:
            add(1, f"Earnings {days_out}d out — minimum met (prefer 10-12)", "pass")

    # ── Gate 02 — expiry 1-2 days past earnings ──────────────────────
    if md.expiration is None or md.earnings_date is None:
        add(2, "No qualifying expiration", "fail",
            "No listed expiry falls 1-2 days past earnings.", hard=True)
    else:
        days_past = (md.expiration - md.earnings_date).days
        if days_past < MIN_EXPIRY_PAST or days_past > MAX_EXPIRY_PAST:
            add(2, f"Expiry is {days_past}d past earnings (need 1-2)", "fail",
                "Too short = theta kills. Too long = paying for time you don't need.", hard=True)
        else:
            add(2, f"Expiry {days_past}d past earnings — correct", "pass")

    # ── Gate 03 — position ≥ 50% of account ──────────────────────────
    total_cost = pct_account = None
    if md.option_price and md.option_price > 0:
        total_cost = md.option_price * inp.contracts * 100
        pct_account = (total_cost / inp.account_balance) * 100
        if pct_account < MIN_ACCOUNT_PCT:
            add(3, f"Position is {pct_account:.1f}% of account — need >=50%", "fail",
                f"${total_cost:,.0f} on ${inp.account_balance:,.0f}. Size up or skip — no token trades.",
                hard=True)
        else:
            add(3, f"Position is {pct_account:.1f}% of account — conviction confirmed", "pass",
                f"${total_cost:,.0f} total cost")
    else:
        add(3, "Cannot price the contract", "fail",
            "No usable quote for the chosen strike.", hard=True)

    # ── Gate 04 — directional conviction ─────────────────────────────
    add(4, f"Directional conviction established: {inp.direction.upper()} -> {option_type}",
        "pass", auto=False)

    # ── Gate 05 — no contra-catalysts (manual confirmation) ──────────
    if inp.no_contra:
        add(5, "No contra-catalysts in window — clean setup", "pass", auto=False)
    else:
        add(5, "Contra-catalysts not ruled out", "fail",
            "Confirm no scheduled events (Fed, product launch, analyst day...) before your exit. "
            "Earnings must be the only event in the window.", hard=True, auto=False)

    # ── Gate 06 — market attention ────────────────────────────────────
    if inp.attention_override is not None:
        attention = inp.attention_override
        detail, auto = "Manual override", False
    else:
        attention = bool(
            (md.market_cap or 0) >= ATTENTION_MIN_MCAP
            or (md.chain_total_oi or 0) >= ATTENTION_MIN_CHAIN_OI
        )
        detail = (f"Market cap ${(md.market_cap or 0) / 1e9:.0f}B, "
                  f"chain OI {md.chain_total_oi or 0:,}")
        auto = True
    if attention:
        add(6, "High market attention confirmed", "pass", detail, auto=auto)
        iv_score += 1
    else:
        add(6, "Limited market attention", "warn",
            detail + " — unknown names don't see IV buildup; nobody's buying the options.", auto=auto)

    # ── Gate 07 — historical big mover ────────────────────────────────
    if md.past_moves:
        big = [m for m in md.past_moves if abs(m) >= BIG_MOVE_PCT]
        moves_txt = ", ".join(f"{m:+.1f}%" for m in md.past_moves[:8])
        if len(big) >= BIG_MOVE_MIN_COUNT:
            add(7, f"Historically big earnings mover ({len(big)}/{len(md.past_moves)} moves >=8%)",
                "pass", f"Last moves: {moves_txt}")
            iv_score += 1
        else:
            add(7, f"Not a historically big mover ({len(big)}/{len(md.past_moves)} moves >=8%)",
                "warn", f"Last moves: {moves_txt} — MMs price IV from history; thin buildup runway.")
    else:
        add(7, "No post-earnings move history available", "warn",
            "Could not compute past earnings moves — verify manually.")

    # ── Gate 08 — liquidity at the chosen strike ──────────────────────
    mid = None
    if md.strike_bid is not None and md.strike_ask is not None and md.strike_ask > 0:
        mid = (md.strike_bid + md.strike_ask) / 2
    if mid and mid > 0 and md.strike_oi is not None:
        spread_pct = (md.strike_ask - md.strike_bid) / mid
        if md.strike_oi >= LIQUIDITY_MIN_OI and spread_pct <= LIQUIDITY_MAX_SPREAD_PCT:
            add(8, "High options volume / liquidity confirmed", "pass",
                f"OI {md.strike_oi:,}, bid-ask {spread_pct * 100:.1f}% of mid")
            iv_score += 1
        else:
            add(8, "Liquidity concern", "warn",
                f"OI {md.strike_oi:,}, bid-ask {spread_pct * 100:.1f}% of mid — "
                "wide spreads eat returns on entry and exit both.")
    else:
        add(8, "Liquidity unknown", "warn", "No usable bid/ask/OI at the chosen strike.")

    # ── Gate 12 — current IV vs 90-day average ────────────────────────
    if md.current_iv is not None and md.avg_iv_90 is not None:
        iv_excess = md.current_iv - md.avg_iv_90
        if iv_excess > IV_EXCESS_LIMIT:
            add(12, f"IV is {iv_excess:+.1f}pts above 90-day avg — buildup may be priced in", "warn",
                "You may be buying the peak. Vega works against you from entry. "
                "(90d avg is an HV-based approximation.)")
        else:
            add(12, f"IV is {iv_excess:+.1f}pts above 90-day avg — room to run", "pass",
                f"Current {md.current_iv:.0f}% vs 90d avg {md.avg_iv_90:.0f}% (HV-proxy approximation)")
            iv_score += 1
    else:
        add(12, "IV history unavailable", "warn", "Could not compute 90-day IV baseline.")

    # ── Gate 13 — theta drag vs projected IV gain ─────────────────────
    if (md.theta_per_day is not None and md.vega is not None and days_out and days_out > 0):
        total_theta_cost = md.theta_per_day * inp.contracts * days_out
        proj_iv_gain_usd = md.vega * inp.expected_iv_gain * inp.contracts * 100
        if proj_iv_gain_usd > 0:
            theta_ratio = (total_theta_cost / proj_iv_gain_usd) * 100
            money = f"${total_theta_cost:,.0f} theta vs ${proj_iv_gain_usd:,.0f} projected IV gain"
            if theta_ratio > THETA_RATIO_LIMIT:
                add(13, f"Theta drag is {theta_ratio:.0f}% of projected IV gain — too high", "warn",
                    money + ". Reduce contracts or pass.")
            else:
                add(13, f"Theta drag is {theta_ratio:.0f}% of projected IV gain — acceptable",
                    "pass", money)
                iv_score += 1
        else:
            add(13, "Cannot compute theta ratio — verify inputs manually", "warn")
    else:
        add(13, "Theta/vega unavailable for chosen contract", "warn")

    # ── Gate 14 — BMO Mon/Tue weekend gap ─────────────────────────────
    if md.earnings_date is not None:
        if inp.bmo_amc == "bmo":
            dow = md.earnings_date.weekday()
            if dow in (0, 1):
                day_name = ["Monday", "Tuesday"][dow]
                add(14, f"BMO {day_name} — weekend gap risk", "warn",
                    "Must hold through a weekend you cannot trade. Size down >=1 contract.",
                    auto=False)
                weekend_flag = True
                sizing_notes.append(
                    f"BMO {day_name}: reduce contracts by 1 for unmanageable weekend gap risk")
            else:
                add(14, f"BMO {md.earnings_date.strftime('%A')} — no weekend gap risk",
                    "pass", auto=False)
                iv_score += 1
        else:
            add(14, "AMC report — no weekend gap risk", "pass", auto=False)
            iv_score += 1
    else:
        add(14, "Cannot assess weekend gap — earnings date unknown", "warn")

    # ── Gates 09-11 — direction signals ───────────────────────────────
    analyst = inp.analyst_override if inp.analyst_override is not None else md.analyst_aligned
    if analyst is True:
        add(9, "Analyst consensus aligned with thesis", "pass",
            auto=inp.analyst_override is None)
        dir_score += 1
    elif analyst is False:
        add(9, "Analyst consensus not aligned", "warn",
            "Lack of institutional conviction is a headwind pre-earnings.",
            auto=inp.analyst_override is None)
    else:
        add(9, "Analyst consensus unavailable — confirm manually", "manual",
            "FMP consensus data not available on this plan; use the override toggle.")

    if md.price_drift_ok is True:
        add(10, "Price action trending in your direction", "pass")
        dir_score += 1
    elif md.price_drift_ok is False:
        add(10, "Price fighting your direction", "warn",
            "A stock fighting you before entry will fight you during the hold.")
    else:
        add(10, "Price drift unknown", "warn", "Insufficient recent price data.")

    etf_txt = f" ({md.sector_etf})" if md.sector_etf else ""
    if md.sector_trend_ok is True:
        add(11, f"Sector tailwind confirmed{etf_txt}", "pass")
        dir_score += 1
    elif md.sector_trend_ok is False:
        add(11, f"Sector headwind{etf_txt}", "warn",
            f"A {inp.direction} play in a sector moving against you faces an uphill battle.")
    else:
        add(11, "Sector trend unknown", "warn", "No sector ETF mapping or price data.")

    # ── Sizing adjustments ────────────────────────────────────────────
    final_contracts = inp.contracts
    if (md.option_price is not None and md.option_price < CHEAP_OPTION_PRICE
            and days_out is not None and days_out < 10
            and final_contracts > CHEAP_OPTION_MAX_CONTRACTS):
        final_contracts = CHEAP_OPTION_MAX_CONTRACTS
        sizing_notes.append(
            "Cheap option (<$5) with <10 days out: capped at 2 contracts — "
            "theta on 4+ contracts becomes catastrophic")
    if weekend_flag and final_contracts > 1:
        final_contracts -= 1

    # ── Verdict ───────────────────────────────────────────────────────
    if hard_fails:
        verdict = "NO_TRADE"
        verdict_detail = f"Hard gate fail: {', '.join(f'Gate {n:02d}' for n in sorted(hard_fails))}. Any hard fail = no trade."
    elif iv_score >= 4 and dir_score >= 2:
        verdict = "TRADE"
        verdict_detail = "Gates cleared. IV thesis intact — execute with conviction."
    elif iv_score >= 3 and dir_score >= 1:
        verdict = "CAUTION"
        verdict_detail = (f"Marginal setup. Only {iv_score}/6 IV gates and "
                          f"{dir_score}/3 signals passed — review flags above.")
    else:
        verdict = "WEAK"
        verdict_detail = (f"Only {iv_score}/6 IV gates and {dir_score}/3 direction signals. "
                          "Risk outweighs opportunity.")

    # ── Exit timing ───────────────────────────────────────────────────
    exit_by: Optional[date] = None
    exit_text = ""
    if md.earnings_date is not None:
        exit_by, exit_text = _exit_timing(md.earnings_date, inp.bmo_amc)

    return TedReport(
        symbol=inp.symbol.upper(),
        direction=inp.direction,
        option_type=option_type,
        days_out=days_out,
        gates=sorted(gates, key=lambda g: g.num),
        iv_score=iv_score,
        dir_score=dir_score,
        hard_fails=sorted(hard_fails),
        verdict=verdict,
        verdict_detail=verdict_detail,
        sizing_notes=sizing_notes,
        recommended_contracts=final_contracts,
        total_cost=round(total_cost, 2) if total_cost is not None else None,
        pct_of_account=round(pct_account, 1) if pct_account is not None else None,
        exit_by=exit_by,
        exit_window_text=exit_text,
    )
