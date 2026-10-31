"""Tests for the automated Ted candidate scanner (backend/scanner/ted_scanner.py).

Network-free: the pure pre-screen logic is tested directly, and discover_candidates
is driven with fake yfinance/cache objects.
"""

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from backend.scanner import ted_scanner as ts

TODAY = date(2026, 10, 30)


def _exp(*offsets_from_earnings, earnings):
    return [earnings + timedelta(days=o) for o in offsets_from_earnings]


# --------------------------------------------------------------------------- #
# qualifying_expiry (Gate 2)
# --------------------------------------------------------------------------- #

def test_qualifying_expiry_picks_earliest_in_window():
    e = date(2026, 11, 10)
    # offsets 0 (too soon), +1 (ok), +2 (ok), +3 (too late) → earliest ok = +1
    assert ts.qualifying_expiry(e, _exp(0, 1, 2, 3, earnings=e)) == e + timedelta(days=1)


def test_qualifying_expiry_none_when_no_1_or_2_day():
    e = date(2026, 11, 10)
    assert ts.qualifying_expiry(e, _exp(0, 3, 7, earnings=e)) is None
    assert ts.qualifying_expiry(e, []) is None


# --------------------------------------------------------------------------- #
# prescreen
# --------------------------------------------------------------------------- #

def test_prescreen_full_qualifier():
    e = TODAY + timedelta(days=11)  # in window, ideal (10-12)
    ps = ts.prescreen(e, _exp(1, earnings=e), [12, -9, 10, 4, 8], None, 20_000, today=TODAY)
    assert ps["qualifies"] and ps["ideal"] and ps["in_window"]
    assert ps["big_mover"] and ps["big_mover_count"] == 4   # |12|,|-9|,|10|,|8| >= 8
    assert ps["attention"]                                  # chain OI 20k >= 10k
    assert ps["prescreen_score"] == 4


def test_prescreen_out_of_window():
    e = TODAY + timedelta(days=20)
    ps = ts.prescreen(e, _exp(1, earnings=e), [], None, None, today=TODAY)
    assert not ps["in_window"] and not ps["qualifies"]


def test_prescreen_in_window_but_no_qualifying_expiry():
    e = TODAY + timedelta(days=8)   # in window, not ideal
    ps = ts.prescreen(e, _exp(3, earnings=e), [], None, None, today=TODAY)
    assert ps["in_window"] and not ps["qualifies"] and not ps["ideal"]
    assert ps["qualifying_expiry"] is None


def test_prescreen_attention_via_market_cap():
    e = TODAY + timedelta(days=11)
    ps = ts.prescreen(e, _exp(2, earnings=e), [], 50e9, 10, today=TODAY)
    assert ps["attention"]  # mcap 50B >= 10B even with tiny chain OI


def test_prescreen_not_big_mover_below_three():
    e = TODAY + timedelta(days=11)
    ps = ts.prescreen(e, _exp(1, earnings=e), [12, 9, 2, 1], None, None, today=TODAY)
    assert not ps["big_mover"] and ps["big_mover_count"] == 2


def test_iv_room():
    assert ts.iv_room(40.0, 30.0) is True    # +10 within the 20pt limit → room to run
    assert ts.iv_room(60.0, 30.0) is False   # +30 over the limit → likely priced in
    assert ts.iv_room(None, 30.0) is None
    assert ts.iv_room(40.0, None) is None


# --------------------------------------------------------------------------- #
# full_gate_eval tiering (pure — assembles TedMarketData and runs evaluate_gates)
# --------------------------------------------------------------------------- #

def _atm(iv=40.0, chain_oi=20000, oi=500, bid=1.05, ask=1.10, theta_per_day=1.0, vega=0.5):
    return {"price": round((bid + ask) / 2, 2), "iv": iv, "chain_oi": chain_oi,
            "oi": oi, "bid": bid, "ask": ask, "theta_per_day": theta_per_day, "vega": vega}


def _eval(direction="bull", atm=None, hv90=30.0, moves=(12, -10, 9, 8),
          sector_ok=True, sector_etf="XLK"):
    e = TODAY + timedelta(days=11)
    return ts.full_gate_eval(
        symbol="AAPL", earnings_date=e, expiry=e + timedelta(days=1),
        direction=direction, atm=atm if atm is not None else _atm(), hv90=hv90,
        past_moves=list(moves), market_cap=None, sector_etf=sector_etf,
        sector_trend_ok=sector_ok, today=TODAY,
    )


def test_full_gate_eval_pass_all():
    r = _eval()  # strong IV structure + bull drift + aligned sector
    assert r["verdict"] == "TRADE" and r["tier"] == "pass_all"
    assert r["iv_score"] >= 4 and r["dir_score"] >= 2 and not r["hard_fails"]


def test_full_gate_eval_pass_most_when_sector_not_aligned():
    r = _eval(sector_ok=False)  # loses the Gate-11 directional signal → dir_score 1
    assert r["verdict"] == "CAUTION" and r["tier"] == "pass_most"


def test_full_gate_eval_weak_on_poor_setup():
    poor = _atm(iv=70.0, chain_oi=100, oi=10, bid=0.5, ask=1.5)  # no attention/liq, IV priced in
    r = _eval(atm=poor, moves=(), sector_ok=False)
    assert r["tier"] == "weak" and r["verdict"] in ("WEAK", "NO_TRADE")


# --------------------------------------------------------------------------- #
# discover_candidates (async, with fakes)
# --------------------------------------------------------------------------- #

class _FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, ttl):
        self.store[k] = v

    async def delete(self, k):
        self.store.pop(k, None)


def _opt(strike, iv=0.40):
    return SimpleNamespace(
        strike=strike, bid=1.0, ask=1.2, last=1.1, open_interest=6000, volume=100,
        implied_volatility=iv, delta=0.5, theta=-0.05, vega=0.10,
    )


class _FakeYF:
    """earnings: {sym: date|None}; expirations: {sym: [date]}."""

    def __init__(self, earnings, expirations):
        self._earnings = earnings
        self._expirations = expirations

    async def get_next_earnings_date(self, sym):
        return self._earnings.get(sym)

    async def get_expirations(self, sym):
        return [d.isoformat() for d in self._expirations.get(sym, [])]

    async def get_full_chain(self, sym, expiration):
        legs = [_opt(95), _opt(100), _opt(105)]  # spot 100 → ATM strike 100, total OI 36k
        return SimpleNamespace(spot_price=100.0, calls=legs, puts=legs)


def _stub_market_data(monkeypatch, *, moves, sign=1, hv90=30.0, sector_etf="XLK"):
    monkeypatch.setattr(ts, "past_earnings_moves", lambda sym: moves)
    monkeypatch.setattr(ts, "drift_sign", lambda sym: sign)
    monkeypatch.setattr(ts, "hv90_pct", lambda sym: hv90)
    monkeypatch.setattr(ts, "fetch_sector_etf", lambda sym: sector_etf)


def test_discover_filters_window_and_ranks(monkeypatch):
    _stub_market_data(monkeypatch, moves=[12, -10, 9, 8], sign=1)  # bull, big mover
    aapl_e = TODAY + timedelta(days=11)   # in window, ideal, qualifying expiry → qualifies
    foo_e = TODAY + timedelta(days=8)     # in window, but NO qualifying expiry
    xyz_e = TODAY + timedelta(days=40)    # out of window → dropped
    earnings = {"AAPL": aapl_e, "FOO": foo_e, "XYZ": xyz_e, "BAR": None}
    expirations = {
        "AAPL": _exp(1, 8, earnings=aapl_e),
        "FOO": _exp(5, earnings=foo_e),
        "XYZ": _exp(1, earnings=xyz_e),
    }
    out = asyncio.run(
        ts.discover_candidates(["AAPL", "FOO", "XYZ", "BAR"], _FakeYF(earnings, expirations),
                               _FakeCache(), today=TODAY)
    )
    syms = [c["symbol"] for c in out]
    assert "XYZ" not in syms and "BAR" not in syms   # out of window / no date
    assert set(syms) == {"AAPL", "FOO"}
    assert out[0]["symbol"] == "AAPL"                # qualifier ranks first
    aapl = next(c for c in out if c["symbol"] == "AAPL")
    foo = next(c for c in out if c["symbol"] == "FOO")
    assert aapl["qualifies"] and aapl["attention"] and aapl["big_mover"]
    # auto-evaluation fields populated for the qualifier
    assert aapl["inferred_direction"] == "bull" and aapl["option_side"] == "call"
    assert aapl["entry_iv"] == 40.0 and aapl["atm_strike"] == 100.0
    assert aapl["iv_room"] is True                   # 40 vs hv90 30 → +10 <= 20
    assert aapl["exit_by"] == aapl_e.isoformat()
    # full-gate tiering: strong IV structure + bull drift + aligned sector → TRADE
    assert aapl["verdict"] == "TRADE" and aapl["tier"] == "pass_all"
    assert aapl["iv_score"] >= 4 and aapl["dir_score"] >= 2
    assert not foo["qualifies"] and foo["tier"] == "weak"   # Gate 2 fails, no eval


def test_discover_uses_cached_earnings_date(monkeypatch):
    _stub_market_data(monkeypatch, moves=[], sign=1)
    e = TODAY + timedelta(days=11)
    cache = _FakeCache()
    cache.store["ted:edate:AAPL"] = e.isoformat()   # pre-seeded

    calls = {"n": 0}

    class _CountingYF(_FakeYF):
        async def get_next_earnings_date(self, sym):
            calls["n"] += 1
            return await super().get_next_earnings_date(sym)

    yf = _CountingYF({"AAPL": e}, {"AAPL": _exp(1, earnings=e)})
    out = asyncio.run(ts.discover_candidates(["AAPL"], yf, cache, today=TODAY))
    assert out and out[0]["symbol"] == "AAPL"
    assert calls["n"] == 0  # earnings date served from cache, no yfinance call
