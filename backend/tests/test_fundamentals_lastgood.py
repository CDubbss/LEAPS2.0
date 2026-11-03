"""Tests for the fundamentals last-good fallback (HANDOFF §4.9).

FMP's free tier 402s on the metrics/income/balance endpoints, blanking
pe_ratio / revenue_growth / gross_margin / debt_to_equity to NaN even when the
/profile call succeeds. The scanner keeps a durable "last known good" snapshot
and reuses it instead of logging NaN into the training feature vector.
"""

import asyncio
from types import SimpleNamespace

from backend.models.fundamentals import FundamentalData
from backend.scanner.fundamentals_scorer import FundamentalsScorer
from backend.scanner.scanner import OptionsScanner, _has_core_fundamentals


# --------------------------------------------------------------------------- #
# _has_core_fundamentals — the predicate that distinguishes real data from a
# 402-blanked / profile-only result.
# --------------------------------------------------------------------------- #

def test_core_true_when_any_core_field_present():
    assert _has_core_fundamentals(FundamentalData(symbol="X", pe_ratio=20.0))
    assert _has_core_fundamentals(FundamentalData(symbol="X", revenue_growth_yoy=0.1))
    assert _has_core_fundamentals(FundamentalData(symbol="X", gross_margin=0.4))
    assert _has_core_fundamentals(FundamentalData(symbol="X", debt_to_equity=0.5))


def test_core_false_when_blank():
    assert not _has_core_fundamentals(FundamentalData(symbol="X"))


def test_core_false_when_profile_only():
    """A /profile-only hit (402 on the rest) has a company name but no core fields."""
    fund = FundamentalData(symbol="X", company_name="X Corp", sector="Tech", market_cap=1e9)
    assert not _has_core_fundamentals(fund)


# --------------------------------------------------------------------------- #
# Overlay behavior in _fetch_fundamentals.
# --------------------------------------------------------------------------- #

class _FakeCache:
    """Mimics RedisCache: set() serializes a model to a JSON-safe dict, get()
    returns that dict (as the real cache round-trips through JSON)."""

    def __init__(self):
        self.store: dict[str, dict] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl):
        self.store[key] = value.model_dump(mode="json")

    async def delete(self, key):
        self.store.pop(key, None)


class _FakeFMP:
    """Returns queued fundamentals responses, one per call."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def get_full_fundamentals(self, symbol):
        return self._responses.pop(0)


def _make_scanner(fmp, cache, *, fallback=True):
    s = OptionsScanner.__new__(OptionsScanner)  # bypass heavy __init__
    s.fmp = fmp
    s.cache = cache
    s.fundamentals_scorer = FundamentalsScorer()
    s.settings = SimpleNamespace(
        CACHE_TTL_FUNDAMENTALS=1_209_600,
        CACHE_TTL_FUNDAMENTALS_LASTGOOD=7_776_000,
        FUNDAMENTALS_LASTGOOD_FALLBACK=fallback,
    )
    return s


def test_lastgood_reused_when_fresh_fetch_blanks():
    good = FundamentalData(symbol="AAPL", company_name="Apple", pe_ratio=25.0,
                           revenue_growth_yoy=0.1, gross_margin=0.45, debt_to_equity=1.2)
    blank = FundamentalData(symbol="AAPL")  # 402 / budget exhausted
    cache = _FakeCache()
    scanner = _make_scanner(_FakeFMP([good, blank]), cache)

    # Scan 1: real data flows through and seeds the last-good snapshot.
    out1 = asyncio.run(scanner._fetch_fundamentals(["AAPL"]))
    assert out1["AAPL"].pe_ratio == 25.0
    assert "fundamentals_lastgood:AAPL" in cache.store

    # Simulate the main cache's TTL expiring; the longer-lived last-good remains.
    cache.store.pop("fundamentals:AAPL", None)

    # Scan 2: FMP blanks. The feature vector must carry the last-good values,
    # not NaN.
    out2 = asyncio.run(scanner._fetch_fundamentals(["AAPL"]))
    assert out2["AAPL"].pe_ratio == 25.0
    assert out2["AAPL"].gross_margin == 0.45


def test_no_fallback_when_disabled():
    good = FundamentalData(symbol="AAPL", company_name="Apple", pe_ratio=25.0)
    blank = FundamentalData(symbol="AAPL")
    cache = _FakeCache()
    scanner = _make_scanner(_FakeFMP([good, blank]), cache, fallback=False)

    asyncio.run(scanner._fetch_fundamentals(["AAPL"]))
    cache.store.pop("fundamentals:AAPL", None)
    out2 = asyncio.run(scanner._fetch_fundamentals(["AAPL"]))
    # Flag off → no overlay, blank stays blank (current/legacy behavior).
    assert out2["AAPL"].pe_ratio is None
