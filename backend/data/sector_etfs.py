"""GICS / FMP sector names → SPDR sector ETF (shared by Ted gates + regime features)."""

SECTOR_ETF = {
    "technology": "XLK", "information technology": "XLK",
    "financial services": "XLF", "financials": "XLF",
    "energy": "XLE",
    "healthcare": "XLV", "health care": "XLV",
    "consumer cyclical": "XLY", "consumer discretionary": "XLY",
    "consumer defensive": "XLP", "consumer staples": "XLP",
    "industrials": "XLI",
    "basic materials": "XLB", "materials": "XLB",
    "utilities": "XLU",
    "real estate": "XLRE",
    "communication services": "XLC",
}


def sector_to_etf(sector: str | None) -> str | None:
    return SECTOR_ETF.get((sector or "").strip().lower())
