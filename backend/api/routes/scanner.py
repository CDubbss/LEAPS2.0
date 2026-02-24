"""Scanner API routes."""

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_scanner
from backend.models.scanner import ScannerFilters, ScannerResult
from backend.scanner.scanner import OptionsScanner
from backend.scanner.universe import DEFAULT_UNIVERSE

router = APIRouter()


@router.post("/scan", response_model=ScannerResult)
async def run_scan(
    filters: ScannerFilters,
    scanner: OptionsScanner = Depends(get_scanner),
) -> ScannerResult:
    """
    Run the full options scanning pipeline.
    Returns ranked spread candidates meeting the specified filter criteria.
    Typical response time: 20-60 seconds depending on universe size.
    """
    return await scanner.scan(filters)


@router.get("/universe", response_model=list[str])
async def get_default_universe() -> list[str]:
    """Return the default symbol universe used when no symbols are specified."""
    return list(DEFAULT_UNIVERSE)


@router.get("/filters/defaults", response_model=ScannerFilters)
async def get_default_filters() -> ScannerFilters:
    """Return default filter configuration."""
    return ScannerFilters()
