"""Tests for the Schwab-backed NYSE-expansion builder (build_nyse_expansion.py).

Network-free: the pure gate logic (normalize/screen/LEAPS) is tested directly,
and the two Schwab passes are driven with a fake async client. The retry path is
exercised with asyncio.sleep patched to a no-op so backoff is instant.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from backend.scripts import build_nyse_expansion as bne

TODAY = date(2026, 11, 3)


# --------------------------------------------------------------------------- #
# Fixtures / fakes
# --------------------------------------------------------------------------- #

def _entry(price=None, mark=None, avg1y=None, avg10d=None, shares=None):
    """Build a raw Schwab quote entry with only the fields the builder reads."""
    quote = {}
    if price is not None:
        quote["lastPrice"] = price
    if mark is not None:
        quote["mark"] = mark
    fundamental = {}
    if avg1y is not None:
        fundamental["avg1YearVolume"] = avg1y
    if avg10d is not None:
        fundamental["avg10DaysVolume"] = avg10d
    if shares is not None:
        fundamental["sharesOutstanding"] = shares
    return {"quote": quote, "fundamental": fundamental}


class _FakeClient:
    def __init__(self, quotes=None, expiries=None, quote_error=False, expiry_errors=None):
        self._quotes = quotes or {}
        self._expiries = expiries or {}
        self._quote_error = quote_error
        self._expiry_errors = set(expiry_errors or [])

    async def get_quotes_raw(self, symbols):
        if self._quote_error:
            raise RuntimeError("boom")
        # Mirror the real client: symbols Schwab can't resolve are simply absent.
        return {s: self._quotes[s] for s in symbols if s in self._quotes}

    async def get_expirations(self, symbol):
        if symbol in self._expiry_errors:
            raise RuntimeError("chain boom")
        return self._expiries.get(symbol, [])


@pytest.fixture
def _instant_backoff(monkeypatch):
    async def _no_sleep(*_a, **_k):
        return None
    monkeypatch.setattr(bne.asyncio, "sleep", _no_sleep)


# --------------------------------------------------------------------------- #
# normalize_quote
# --------------------------------------------------------------------------- #

def test_normalize_full():
    n = bne.normalize_quote(_entry(price=50.0, avg1y=1_000_000, shares=100_000_000))
    assert n == {"price": 50.0, "avg_volume": 1_000_000.0,
                 "shares": 100_000_000.0, "market_cap": 5_000_000_000.0}


def test_normalize_price_falls_back_to_mark():
    n = bne.normalize_quote(_entry(mark=12.5, avg1y=600_000, shares=1_000_000))
    assert n["price"] == 12.5


def test_normalize_volume_falls_back_to_10day():
    n = bne.normalize_quote(_entry(price=20.0, avg10d=750_000, shares=1_000_000))
    assert n["avg_volume"] == 750_000.0


def test_normalize_missing_shares_gives_none_mcap():
    # VALE-like ADR: Schwab reports no sharesOutstanding → market cap underivable.
    n = bne.normalize_quote(_entry(price=11.47, avg1y=32_000_000))
    assert n["shares"] is None
    assert n["market_cap"] is None


def test_normalize_empty_entry_is_all_none():
    n = bne.normalize_quote({})
    assert n == {"price": None, "avg_volume": None, "shares": None, "market_cap": None}


# --------------------------------------------------------------------------- #
# screen_quote
# --------------------------------------------------------------------------- #

GATES = dict(min_price=10.0, min_vol=500_000, min_mcap=2_000_000_000.0)


def test_screen_ok():
    n = bne.normalize_quote(_entry(price=50.0, avg1y=1_000_000, shares=100_000_000))
    assert bne.screen_quote(n, **GATES) == (True, "ok")


def test_screen_low_price():
    n = bne.normalize_quote(_entry(price=3.2, avg1y=47_000_000, shares=2_500_000_000))
    assert bne.screen_quote(n, **GATES) == (False, "low-price")


def test_screen_low_volume():
    n = bne.normalize_quote(_entry(price=50.0, avg1y=100_000, shares=100_000_000))
    assert bne.screen_quote(n, **GATES) == (False, "low-volume")


def test_screen_low_mcap():
    n = bne.normalize_quote(_entry(price=50.0, avg1y=1_000_000, shares=10_000_000))
    assert bne.screen_quote(n, **GATES) == (False, "low-mcap")


def test_screen_missing_data():
    assert bne.screen_quote(bne.normalize_quote({}), **GATES) == (False, "missing-data")


def test_screen_mcap_unknown_passes_best_effort():
    # Shares missing → mcap None → best-effort PASS so the other gates decide it.
    n = bne.normalize_quote(_entry(price=11.47, avg1y=32_000_000))
    assert bne.screen_quote(n, **GATES) == (True, "ok-mcap-unknown")


# --------------------------------------------------------------------------- #
# has_leaps_expiry
# --------------------------------------------------------------------------- #

def test_leaps_true_when_far_expiry_present():
    assert bne.has_leaps_expiry(["2028-01-21"], TODAY) is True


def test_leaps_false_when_only_near_expiries():
    assert bne.has_leaps_expiry(["2026-11-20", "2027-02-01"], TODAY) is False


def test_leaps_false_on_empty():
    assert bne.has_leaps_expiry([], TODAY) is False


def test_leaps_ignores_malformed_dates():
    assert bne.has_leaps_expiry(["not-a-date", "2029-01-01"], TODAY) is True


# --------------------------------------------------------------------------- #
# quote_screen (async pass 1)
# --------------------------------------------------------------------------- #

async def test_quote_screen_buckets_and_survivors():
    quotes = {
        "GOOD": _entry(price=50.0, avg1y=1_000_000, shares=100_000_000),   # ok
        "ADR": _entry(price=11.47, avg1y=32_000_000),                      # ok-mcap-unknown
        "CHEAP": _entry(price=3.2, avg1y=47_000_000, shares=2_500_000_000),  # low-price
        "THIN": _entry(price=50.0, avg1y=100, shares=100_000_000),         # low-volume
        "SMALL": _entry(price=50.0, avg1y=1_000_000, shares=10_000_000),   # low-mcap
        "NODATA": {},                                                      # missing-data
        # "GHOST" intentionally absent → unknown-symbol
    }
    batch = ["GOOD", "ADR", "CHEAP", "THIN", "SMALL", "NODATA", "GHOST"]
    client = _FakeClient(quotes=quotes)

    survivors, reasons, mcap_unknown, unresolved = await bne.quote_screen(
        client, batch, **GATES)

    assert survivors == ["ADR", "GOOD"]
    assert mcap_unknown == 1
    assert unresolved == []
    assert reasons["ok"] == 1
    assert reasons["ok-mcap-unknown"] == 1
    assert reasons["low-price"] == 1
    assert reasons["low-volume"] == 1
    assert reasons["low-mcap"] == 1
    assert reasons["missing-data"] == 1
    assert reasons["unknown-symbol"] == 1


async def test_quote_screen_batch_failure_is_unresolved_not_a_clean_drop(_instant_backoff):
    client = _FakeClient(quote_error=True)
    batch = ["AAA", "BBB", "CCC"]

    survivors, reasons, mcap_unknown, unresolved = await bne.quote_screen(
        client, batch, **GATES)

    assert survivors == []
    assert unresolved == batch
    assert reasons.get("error") == 3
    # The failure must NOT masquerade as a real gate result.
    assert "no-options" not in reasons and "missing-data" not in reasons


# --------------------------------------------------------------------------- #
# leaps_screen (async pass 2)
# --------------------------------------------------------------------------- #

async def test_leaps_screen_buckets(_instant_backoff):
    expiries = {
        "LEAP": ["2026-12-19", "2028-01-21"],   # has a far expiry → ok
        "NEAR": ["2026-11-20", "2027-02-01"],   # only near → no-leaps
        "NOOPT": [],                            # no chain → no-options
        # "ERR" raises → error / unresolved
    }
    client = _FakeClient(expiries=expiries, expiry_errors=["ERR"])
    survivors = ["LEAP", "NEAR", "NOOPT", "ERR"]

    kept, reasons, unresolved = await bne.leaps_screen(
        client, survivors, TODAY, target_rate_per_min=0)

    assert kept == ["LEAP"]
    assert unresolved == ["ERR"]
    assert reasons["ok"] == 1
    assert reasons["no-leaps"] == 1
    assert reasons["no-options"] == 1
    assert reasons["error"] == 1


# --------------------------------------------------------------------------- #
# _render — the truncation warning
# --------------------------------------------------------------------------- #

def test_render_flags_unresolved():
    args = SimpleNamespace(min_price=10.0, min_volume=500_000, min_market_cap=2e9)
    body = bne._render(["AAA", "BBB"], ["ZZZ"], args, ("N",), mcap_unknown=1)
    assert "WARNING" in body
    assert "UNRESOLVED" in body
    assert "ZZZ" in body
    # survivors still listed, one per line
    assert "\nAAA\n" in body and "\nBBB\n" in body


def test_render_clean_has_no_warning():
    args = SimpleNamespace(min_price=10.0, min_volume=500_000, min_market_cap=2e9)
    body = bne._render(["AAA"], [], args, ("N",), mcap_unknown=0)
    assert "WARNING" not in body
