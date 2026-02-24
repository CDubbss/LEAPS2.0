"""
Hard filters applied to raw option quotes before spread construction.
Pure computation — no API calls.
"""

from datetime import date

from backend.models.options import OptionQuote, OptionType, SpreadType
from backend.models.scanner import ScannerFilters


class OptionsFilter:
    """
    Stage 1 filtering: eliminates illiquid/unsuitable options early
    before the more expensive spread construction step.
    """

    def filter_legs(
        self,
        quotes: list[OptionQuote],
        filters: ScannerFilters,
        strategy: SpreadType,
    ) -> list[OptionQuote]:
        """
        Filter a flat list of option quotes for a given strategy.
        Returns only quotes that pass all liquidity and DTE requirements.
        """
        today = date.today()
        result = []

        is_leaps = strategy in (SpreadType.LEAP_CALL, SpreadType.LEAP_PUT)
        min_dte = filters.leaps_min_dte if is_leaps else filters.min_dte
        max_dte = filters.leaps_max_dte if is_leaps else filters.max_dte

        for quote in quotes:
            dte = (quote.expiration - today).days
            if dte < min_dte or dte > max_dte:
                continue
            if quote.volume < filters.min_volume:
                continue
            if quote.open_interest < filters.min_open_interest:
                continue
            if quote.bid <= 0 or quote.ask <= 0:
                continue
            mid = (quote.bid + quote.ask) / 2
            if mid > 0:
                spread_pct = (quote.ask - quote.bid) / mid
                if spread_pct > filters.max_bid_ask_spread_pct:
                    continue
            result.append(quote)

        return result

    def filter_for_strategy(
        self,
        calls: list[OptionQuote],
        puts: list[OptionQuote],
        filters: ScannerFilters,
        strategy: SpreadType,
    ) -> list[OptionQuote]:
        """Return filtered legs appropriate for the given strategy."""
        if strategy in (SpreadType.BULL_CALL, SpreadType.LEAP_CALL):
            return self.filter_legs(calls, filters, strategy)
        elif strategy in (SpreadType.BEAR_PUT, SpreadType.LEAP_PUT):
            return self.filter_legs(puts, filters, strategy)
        return []
