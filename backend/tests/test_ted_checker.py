"""Verdict-tier sanity tests for the Ted gate checker (ports app.py v1.3 logic)."""

from datetime import date, timedelta

from backend.scanner.ted_checker import TedInputs, TedMarketData, evaluate_gates

TODAY = date(2026, 7, 6)  # Monday


def _good_inputs(**kw) -> TedInputs:
    base = dict(
        symbol="NVDA", direction="bull", account_balance=10_000,
        contracts=10, expected_iv_gain=10.0, bmo_amc="amc", no_contra=True,
    )
    base.update(kw)
    return TedInputs(**base)


def _good_market(**kw) -> TedMarketData:
    earnings = TODAY + timedelta(days=11)          # ideal window (Fri Jul 17)
    base = dict(
        earnings_date=earnings,
        expiration=earnings + timedelta(days=1),   # 1 day past — correct
        option_price=6.00,                          # 10 contracts = $6,000 = 60% of account
        # theta ratio: 8.50*10*11 = $935 vs 0.35*10*10*100 = $3,500 → 27% (< 30%)
        theta_per_day=8.50,
        vega=0.35,
        market_cap=50e9,
        chain_total_oi=50_000,
        strike_oi=1_500,
        strike_bid=5.90, strike_ask=6.10,
        current_iv=45.0, avg_iv_90=40.0,           # +5pts — room to run
        past_moves=[9.1, -8.5, 12.0, 3.2, -2.1, 8.8, 1.0, -4.0],  # 4 big moves
        price_drift_ok=True, sector_trend_ok=True, sector_etf="XLK",
        analyst_aligned=True,
    )
    base.update(kw)
    return TedMarketData(**base)


def test_full_pass_is_trade():
    r = evaluate_gates(_good_inputs(), _good_market(), today=TODAY)
    assert r.hard_fails == []
    assert r.iv_score == 6
    assert r.dir_score == 3
    assert r.verdict == "TRADE"
    assert r.days_out == 11
    # AMC → exit on earnings day
    assert r.exit_by == TODAY + timedelta(days=11)


def test_hard_fail_timing_too_close():
    md = _good_market(earnings_date=TODAY + timedelta(days=3))
    r = evaluate_gates(_good_inputs(), md, today=TODAY)
    assert 1 in r.hard_fails
    assert r.verdict == "NO_TRADE"


def test_hard_fail_expiry_too_far():
    e = TODAY + timedelta(days=11)
    md = _good_market(earnings_date=e, expiration=e + timedelta(days=7))
    r = evaluate_gates(_good_inputs(), md, today=TODAY)
    assert 2 in r.hard_fails
    assert r.verdict == "NO_TRADE"


def test_hard_fail_undersized_position():
    r = evaluate_gates(_good_inputs(contracts=1), _good_market(), today=TODAY)
    # 1 contract × $6.00 × 100 = $600 = 6% of $10k — below the 50% conviction floor
    assert 3 in r.hard_fails
    assert r.verdict == "NO_TRADE"


def test_hard_fail_contra_catalyst_unconfirmed():
    r = evaluate_gates(_good_inputs(no_contra=False), _good_market(), today=TODAY)
    assert 5 in r.hard_fails
    assert r.verdict == "NO_TRADE"


def test_caution_tier():
    # Knock IV gates down to exactly 3 and direction to 1:
    md = _good_market(
        current_iv=70.0, avg_iv_90=40.0,        # gate 12 warn (+30 pts)
        past_moves=[1.0, 2.0, -3.0, 1.5],       # gate 7 warn (0 big moves)
        strike_oi=50,                            # gate 8 warn
        price_drift_ok=False, sector_trend_ok=False,  # gates 10/11 warn
        analyst_aligned=True,                    # gate 9 pass → dir_score 1
    )
    r = evaluate_gates(_good_inputs(), md, today=TODAY)
    assert r.hard_fails == []
    assert r.iv_score == 3       # gates 6, 13, 14 pass
    assert r.dir_score == 1
    assert r.verdict == "CAUTION"


def test_weak_tier():
    md = _good_market(
        market_cap=1e9, chain_total_oi=500,      # gate 6 warn
        current_iv=70.0, avg_iv_90=40.0,         # gate 12 warn
        past_moves=[1.0],                        # gate 7 warn
        strike_oi=50,                            # gate 8 warn
        theta_per_day=50.0, vega=0.05,           # gate 13 warn (ratio >> 30%)
        price_drift_ok=False, sector_trend_ok=False, analyst_aligned=False,
    )
    r = evaluate_gates(_good_inputs(), md, today=TODAY)
    assert r.hard_fails == []
    assert r.iv_score == 1       # only gate 14 (AMC) passes
    assert r.dir_score == 0
    assert r.verdict == "WEAK"


def test_bmo_monday_weekend_flag_and_sizing():
    # Earnings Mon Jul 20, 2026 BMO → weekend gap warn + contract reduction
    earnings = date(2026, 7, 20)
    assert earnings.weekday() == 0
    md = _good_market(earnings_date=earnings, expiration=earnings + timedelta(days=1))
    inp = _good_inputs(bmo_amc="bmo")
    r = evaluate_gates(inp, md, today=TODAY)
    g14 = next(g for g in r.gates if g.num == 14)
    assert g14.status == "warn"
    assert r.recommended_contracts == inp.contracts - 1
    # BMO → exit prior business day (Friday Jul 17)
    assert r.exit_by == date(2026, 7, 17)
    assert any("weekend gap" in n for n in r.sizing_notes)


def test_cheap_option_contract_cap():
    # <$5 premium and <10 days out → cap at 2 contracts
    earnings = TODAY + timedelta(days=8)
    md = _good_market(
        earnings_date=earnings,
        expiration=earnings + timedelta(days=1),
        option_price=3.00,                       # 10 × $3 × 100 = $3,000... need >=50%
    )
    inp = _good_inputs(contracts=17, account_balance=10_000)  # $5,100 = 51%
    r = evaluate_gates(inp, md, today=TODAY)
    assert r.hard_fails == []
    assert r.recommended_contracts == 2
    assert any("capped at 2 contracts" in n for n in r.sizing_notes)
