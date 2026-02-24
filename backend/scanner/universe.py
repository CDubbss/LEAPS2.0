"""
Manages the universe of symbols to scan.
Default universe: S&P 500 top symbols by options volume.
Users can override with explicit symbol list via ScannerFilters.
"""

import logging

from backend.models.scanner import ScannerFilters

logger = logging.getLogger(__name__)

# Curated default universe: high options liquidity, diverse sectors
DEFAULT_UNIVERSE = [
    # Mega-cap tech / growth
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "AMD",
    # Financials
    "JPM", "BAC", "GS", "MS", "V", "MA",
    # Healthcare / biotech
    "UNH", "JNJ", "ABBV", "LLY", "PFE",
    # Energy
    "XOM", "CVX", "OXY",
    # Consumer / retail
    "COST", "WMT", "HD", "NKE", "SBUX",
    # Industrials / defense
    "CAT", "DE", "LMT", "RTX",
    # ETFs (high liquidity, great for spreads)
    "SPY", "QQQ", "IWM", "XLF", "XLE", "XLV",
    # Semiconductors
    "INTC", "QCOM", "MU", "AVGO",
    # Other high-volume options names
    "DIS", "NFLX", "CRM", "BABA", "BA",
]


class UniverseBuilder:
    """
    Determines which symbols to scan based on user filters.
    Falls back to DEFAULT_UNIVERSE if no symbols specified.
    """

    async def build(self, filters: ScannerFilters) -> list[str]:
        if filters.symbols:
            return [s.upper().strip() for s in filters.symbols if s.strip()]
        return DEFAULT_UNIVERSE

    def get_default_universe(self) -> list[str]:
        return list(DEFAULT_UNIVERSE)
