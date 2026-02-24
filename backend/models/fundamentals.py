from datetime import date
from typing import Optional

from pydantic import BaseModel


class FundamentalData(BaseModel):
    symbol: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    market_cap: float = 0.0
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None   # decimal, e.g. 0.12 = 12%
    earnings_growth_yoy: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    gross_margin: Optional[float] = None         # decimal
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    return_on_equity: Optional[float] = None
    return_on_assets: Optional[float] = None
    free_cash_flow_yield: Optional[float] = None
    next_earnings_date: Optional[date] = None
    days_to_earnings: Optional[int] = None       # computed from next_earnings_date
    fundamental_score: Optional[float] = None    # computed 0-100
