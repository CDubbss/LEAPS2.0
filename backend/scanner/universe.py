"""
Manages the universe of symbols to scan.
Covers three index mandates: Nasdaq 100, S&P 500, and MSCI (via ADRs + ETFs).
Only symbols with sufficiently liquid options markets are included — illiquid names
produce empty chains and waste scan time.

Users can override with an explicit symbol list via ScannerFilters.symbols.
"""

import logging

from backend.models.scanner import ScannerFilters

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Nasdaq 100 — full constituent list
# ---------------------------------------------------------------------------
_NASDAQ_100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO",
    "COST", "NFLX", "ASML", "AMD", "QCOM", "ORCL", "ADBE", "CSCO", "TMUS",
    "TXN", "INTU", "AMAT", "PEP", "HON", "AMGN", "BKNG", "ISRG", "VRTX",
    "PANW", "ADP", "LRCX", "MU", "MELI", "REGN", "KLAC", "SBUX", "GILD",
    "MDLZ", "ADI", "SNPS", "CDNS", "INTC", "CME", "PYPL", "MRVL", "CRWD",
    "ABNB", "CTAS", "MAR", "WDAY", "FTNT", "TEAM", "DXCM", "PCAR", "KDP",
    "CHTR", "MNST", "PAYX", "LULU", "FAST", "BIIB", "VRSK", "CPRT", "ON",
    "CTSH", "ILMN", "DDOG", "ZS", "ANSS", "SPLK", "MCHP", "ENPH",
    "IDXX", "EXC", "XEL", "AEP", "FANG", "ZM", "ODFL", "NXPI", "ROST",
    "DLTR", "GEHC", "WBD", "SIRI", "GFS", "CEG",
]

# ---------------------------------------------------------------------------
# Nasdaq Composite extended — major Nasdaq-listed names beyond the top 100
# with active options markets (high-beta / high-growth / crypto adjacent)
# ---------------------------------------------------------------------------
_NASDAQ_EXTENDED = [
    # Semiconductors / AI hardware
    "SMCI", "ARM", "WOLF", "ACLS", "ONTO", "MKSI",
    # Software / cloud (high-beta)
    "SNOW", "OKTA", "MDB", "NET", "TTD", "DOCU", "TWLO", "VEEV", "HUBS",
    "BILL", "PCTY", "PAYC", "ZI", "GTLB", "PATH", "CFLT", "DKNG",
    # Consumer internet / social
    "SNAP", "PINS", "SPOT", "RBLX", "DASH", "SHOP",
    # EV / transportation
    "RIVN", "LCID", "CHPT",
    # Fintech / crypto
    "COIN", "HOOD", "SOFI", "AFRM", "UPST",
    # AI / software
    "PLTR", "APP", "AI", "BBAI",
    # Bitcoin proxy
    "MSTR",
    # Biotech (high-options activity)
    "MRNA", "BNTX", "NVAX", "SAVA", "LABU",
    # Other high-liquidity Nasdaq names
    "CELH", "UBER", "LYFT", "U",
]

# ---------------------------------------------------------------------------
# S&P 500 — comprehensive list of names with liquid options markets,
# organized by GICS sector. Nasdaq 100 overlaps intentionally deduped.
# ---------------------------------------------------------------------------

# --- Financials ---
_SP500_FINANCIALS = [
    # Megacap banks / diversified
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "AXP", "COF",
    # Payment networks (most liquid options in S&P 500)
    "V", "MA",
    # Alternative asset managers
    "BX", "KKR", "APO", "ARES",
    # Regional banks
    "USB", "PNC", "TFC", "MTB", "CFG", "KEY", "RF", "HBAN", "FITB", "CMA", "ZION",
    # Custody / trust banks
    "STT", "BK",
    # Insurance
    "AIG", "MET", "PRU", "AFL", "ALL", "TRV", "HIG", "CB", "PGR", "CINF",
    "RE", "WRB", "ACGL", "L",
    # Exchanges & data
    "ICE", "SPGI", "MCO", "NDAQ", "CBOE", "CME", "MSCI", "FDS",
    # Brokers / wealth
    "RJF", "SF",
    # Insurance brokerage
    "AON", "MMC", "AJG", "WTW",
    # Berkshire
    "BRK-B",
    # Fintech / payments
    "FIS", "FISV", "DFS", "SYF",
]

# --- Health Care ---
_SP500_HEALTHCARE = [
    # Pharma / biotech
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "BMY", "MRNA", "BNTX",
    # Medtech / devices
    "ABT", "TMO", "DHR", "MDT", "SYK", "BSX", "EW", "ZBH", "BAX", "HOLX",
    "ALGN", "PODD", "RMD",
    # Life science tools
    "A", "IQV", "MTD", "WAT", "BIO", "TECH",
    # Managed care / PBMs
    "ELV", "HUM", "CI", "CVS", "MOH", "CNC",
    # Other
    "ZTS", "INCY", "EXAS", "RARE",
]

# --- Information Technology (beyond Nasdaq 100) ---
_SP500_TECH = [
    # IT services / consulting
    "ACN", "IBM", "EPAM", "DXC",
    # Hardware / storage
    "HPQ", "HPE", "NTAP", "STX", "WDC", "GLW", "ZBRA",
    # Enterprise software
    "NOW", "CRM", "PAYC", "PCTY",
    # Networking
    "ANET", "JNPR", "FFIV",
    # Payments / fintech
    "SQ", "WEX",
    # Semiconductors (beyond Nasdaq 100)
    "TER", "MTSI", "COHU",
    # IT consulting / other
    "LDOS", "SAIC",
]

# --- Consumer Discretionary ---
_SP500_CONSUMER_DISC = [
    # Retail
    "HD", "LOW", "TGT", "WMT", "TJX", "ROST", "DLTR", "DG", "BBY",
    "ORLY", "AZO", "KMX",
    # Restaurants
    "MCD", "CMG", "YUM", "DRI", "DPZ",
    # Apparel
    "NKE", "RL", "TPR", "PVH", "VFC", "HBI",
    # Auto OEMs / parts
    "F", "GM", "APTV", "TSCO",
    # E-commerce / marketplace
    "ETSY", "EBAY",
    # Travel / leisure
    "EXPE", "RCL", "CCL", "NCLH", "HLT", "MAR", "H", "LVS", "MGM", "WYNN",
    "LYV",
    # Homebuilders
    "DHI", "LEN", "PHM", "TOL", "NVR",
    # Consumer durables / other
    "POOL", "SWK", "WHR", "GNRC", "MHK",
]

# --- Consumer Staples ---
_SP500_CONSUMER_STAPLES = [
    "PG", "KO", "PEP", "MDLZ", "MO", "PM", "STZ", "CL", "GIS", "K", "HSY",
    "MNST", "KDP", "KR", "SYY", "KHC", "CHD", "CLX", "CAG", "SJM", "MKC",
    "HRL", "TAP", "BG", "ADM",
]

# --- Energy ---
_SP500_ENERGY = [
    "XOM", "CVX", "COP", "MPC", "VLO", "PSX", "OXY", "HAL", "SLB", "EOG",
    "PXD", "DVN", "FANG", "BKR", "CTRA", "MRO", "APA", "EQT",
    "WMB", "KMI", "OKE", "NOV",
]

# --- Industrials ---
_SP500_INDUSTRIALS = [
    # Defense
    "BA", "LMT", "RTX", "NOC", "GD", "HII", "L3H",
    # Industrial conglomerates / machinery
    "CAT", "DE", "EMR", "ETN", "GE", "MMM", "HON", "PH", "ITW", "IR",
    "AME", "GWW", "OTIS", "CARR", "XYL", "ROP", "DOV", "IEX", "FTV",
    "ROK", "CMI", "PCAR", "HUBB",
    # Aerospace components
    "HWM", "TDG", "SPR", "KTOS",
    # Transportation
    "FDX", "UPS", "UNP", "NSC", "CSX", "DAL", "UAL", "LUV", "AAL",
    "JBHT", "ODFL", "CHRW", "EXPD", "SAIA", "WAB",
    # Waste / facilities
    "WM", "RSG",
    # CTAS, FAST, VRSK, CPRT are in Nasdaq 100
]

# --- Materials ---
_SP500_MATERIALS = [
    "LIN", "APD", "SHW", "PPG", "ECL", "NEM", "FCX", "AA", "ALB", "CF",
    "MOS", "FMC", "IFF", "CTVA", "CE", "VMC", "MLM", "BLL",
    "PKG", "IP", "WY", "ATI", "RS",
]

# --- Real Estate ---
_SP500_REAL_ESTATE = [
    # Data centers / towers (most liquid REIT options)
    "AMT", "CCI", "EQIX",
    # Industrial / logistics
    "PLD",
    # Retail
    "SPG", "O", "REG", "KIM",
    # Healthcare RE
    "WELL", "VTR", "ARE", "PEAK",
    # Self-storage
    "PSA", "EXR",
    # Office
    "BXP", "SLG",
    # Apartments
    "EQR", "AVB", "ESS", "MAA", "UDR",
    # Diversified
    "VICI", "IRM", "HST", "NNN", "STAG",
]

# --- Utilities ---
_SP500_UTILITIES = [
    # Large-cap electrics
    "NEE", "DUK", "SO", "AEP", "D", "PCG", "EXC", "XEL", "SRE", "ED",
    # Mid-cap electrics
    "ES", "FE", "ETR", "CMS", "DTE", "PPL", "WEC", "AEE", "CNP", "NI",
    "EVRG", "LNT",
    # Water / gas
    "AWK", "ATO",
]

# --- Communication Services ---
_SP500_COMMUNICATION = [
    # Already in Nasdaq 100: GOOGL, GOOG, META, NFLX, TMUS, WBD, CHTR, SIRI
    "T", "VZ", "DIS", "CMCSA", "PARA",
    # Interactive media / gaming
    "EA", "TTWO",
    # Publishing / news
    "OMC", "IPG", "FOXA", "NWS",
    # Internet marketplace
    "MTCH", "ZG",
]

# ---------------------------------------------------------------------------
# MSCI coverage — international via U.S.-listed ADRs + index ETFs
# ---------------------------------------------------------------------------
_MSCI_COVERAGE = [
    # MSCI index ETFs
    "EFA",   # MSCI EAFE (Europe, Australasia, Far East)
    "EEM",   # MSCI Emerging Markets
    "VEA",   # FTSE Developed Markets (MSCI proxy)
    "VWO",   # FTSE Emerging Markets (MSCI proxy)
    "ACWI",  # MSCI All Country World
    "MCHI",  # MSCI China
    "EWJ",   # MSCI Japan
    "EWZ",   # MSCI Brazil
    "EWY",   # MSCI South Korea
    "EWT",   # MSCI Taiwan
    "EWG",   # MSCI Germany
    "EWU",   # MSCI United Kingdom
    "EWC",   # MSCI Canada
    "EWA",   # MSCI Australia
    "EWH",   # MSCI Hong Kong
    "EWI",   # MSCI Italy
    "EWP",   # MSCI Spain
    "EWQ",   # MSCI France
    "EWD",   # MSCI Sweden
    "FXI",   # iShares China Large-Cap
    # High-liquidity international ADRs
    "TSM",   # Taiwan Semiconductor
    "ASML",  # ASML Holding (Netherlands)
    "NVO",   # Novo Nordisk (Denmark)
    "SAP",   # SAP SE (Germany)
    "AZN",   # AstraZeneca (UK)
    "NVS",   # Novartis (Switzerland)
    "SHEL",  # Shell (UK/Netherlands)
    "BP",    # BP (UK)
    "RIO",   # Rio Tinto (Australia/UK)
    "BHP",   # BHP Group (Australia)
    "VALE",  # Vale (Brazil)
    "BIDU",  # Baidu (China)
    "BABA",  # Alibaba (China)
    "PDD",   # PDD Holdings (China)
    "JD",    # JD.com (China)
    "NIO",   # NIO (China EV)
    "SONY",  # Sony Group (Japan)
    "TM",    # Toyota Motor (Japan)
    "HMC",   # Honda Motor (Japan)
    "ING",   # ING Group (Netherlands)
    "DB",    # Deutsche Bank (Germany)
    "HSBC",  # HSBC Holdings (UK)
    "SAN",   # Santander (Spain)
    "BTI",   # British American Tobacco (UK)
    "GSK",   # GSK plc (UK)
    "SNY",   # Sanofi (France)
    "ABBV",  # AbbVie — U.S. but major MSCI component
    "RY",    # Royal Bank of Canada
    "TD",    # Toronto-Dominion Bank
    "BNS",   # Bank of Nova Scotia
    "CNI",   # Canadian National Railway
    "CP",    # Canadian Pacific Kansas City
    "ABB",   # ABB Ltd (Switzerland)
    "UL",    # Unilever (UK/Netherlands)
    "DEO",   # Diageo (UK)
    "BUD",   # Anheuser-Busch InBev (Belgium)
    "INFY",  # Infosys (India)
    "WIT",   # Wipro (India)
    "HDB",   # HDFC Bank (India)
    "RELX",  # RELX Group (UK)
    "NGG",   # National Grid (UK)
    "LYB",   # LyondellBasell — MSCI component
]

# ---------------------------------------------------------------------------
# Broad-market & sector ETFs — high OI, tight bid-ask, LEAPS always available
# ---------------------------------------------------------------------------
_ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "MDY", "IJR",   # broad market
    "XLF", "XLE", "XLV", "XLK", "XLI", "XLY",   # SPDR sectors
    "XLC", "XLB", "XLRE", "XLU", "XLP",
    "VTI", "VOO", "VGT", "VHT", "VFH",           # Vanguard
    "GLD", "SLV", "GDX", "GDXJ",                 # gold / miners
    "USO", "UNG",                                  # energy commodities
    "TLT", "IEF", "SHY", "HYG", "LQD", "JNK",   # bonds
    "ARKK", "ARKG", "ARKF", "ARKW",               # thematic
    "SOXX", "SMH",                                 # semis
    "IBB", "XBI",                                  # biotech
    "KRE", "KBE",                                  # regional banks
    "ITB", "XHB",                                  # homebuilders
    "JETS",                                        # airlines
    "OIH",                                         # oil services
    "HACK",                                        # cybersecurity
    "BOTZ",                                        # robotics / AI
]

# ---------------------------------------------------------------------------
# Final universe — deduplicated, sorted for readability
# ---------------------------------------------------------------------------
DEFAULT_UNIVERSE: list[str] = sorted(
    set(
        _NASDAQ_100
        + _NASDAQ_EXTENDED
        + _SP500_FINANCIALS
        + _SP500_HEALTHCARE
        + _SP500_TECH
        + _SP500_CONSUMER_DISC
        + _SP500_CONSUMER_STAPLES
        + _SP500_ENERGY
        + _SP500_INDUSTRIALS
        + _SP500_MATERIALS
        + _SP500_REAL_ESTATE
        + _SP500_UTILITIES
        + _SP500_COMMUNICATION
        + _MSCI_COVERAGE
        + _ETFS
    )
)


class UniverseBuilder:
    """
    Determines which symbols to scan based on user filters.
    Falls back to DEFAULT_UNIVERSE if no symbols are specified.
    """

    async def build(self, filters: ScannerFilters) -> list[str]:
        if filters.symbols:
            return [s.upper().strip() for s in filters.symbols if s.strip()]
        logger.info("Using default universe: %d symbols", len(DEFAULT_UNIVERSE))
        return DEFAULT_UNIVERSE

    def get_default_universe(self) -> list[str]:
        return list(DEFAULT_UNIVERSE)
