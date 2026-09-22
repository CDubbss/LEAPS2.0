"""Scanner API routes."""

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from backend.api.dependencies import get_scanner
from backend.api.limiter import limiter
from backend.config.settings import get_settings
from backend.models.scanner import ScannerFilters, ScannerResult
from backend.scanner.scanner import OptionsScanner
from backend.scanner.universe import DEFAULT_UNIVERSE

router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory scan job store — keyed by scan_id
# None = still running, ScannerResult = complete, str = error message
# ---------------------------------------------------------------------------
_MAX_JOBS = 50  # cap memory usage
_scan_jobs: dict[str, ScannerResult | str | None] = {}


def _evict_old_jobs() -> None:
    """Remove oldest entries when store exceeds _MAX_JOBS."""
    if len(_scan_jobs) >= _MAX_JOBS:
        oldest = list(_scan_jobs.keys())[0]
        del _scan_jobs[oldest]


class ScanJob(BaseModel):
    scan_id: str
    status: Literal["running", "complete", "failed"]
    result: Optional[ScannerResult] = None
    error: Optional[str] = None


async def _run_scan_background(
    scan_id: str, filters: ScannerFilters, scanner: OptionsScanner
) -> None:
    try:
        result = await scanner.scan(filters)
        _scan_jobs[scan_id] = result
        if not result.results:
            logger.warning(
                "Scan %s returned 0 results. filters=%s",
                scan_id,
                json.dumps(filters.model_dump(mode="json"), default=str),
            )
    except Exception as e:
        _scan_jobs[scan_id] = str(e)


@router.post("/scan", response_model=ScanJob)
@limiter.limit(get_settings().RATE_LIMIT_SCAN)
async def start_scan(
    request: Request,
    filters: ScannerFilters,
    scanner: OptionsScanner = Depends(get_scanner),
) -> ScanJob:
    """
    Start a scan in the background. Returns immediately with a scan_id.
    Poll GET /scan/{scan_id} for results.
    Rate limited: 5 requests/minute per IP.
    """
    _evict_old_jobs()
    scan_id = str(uuid.uuid4())
    _scan_jobs[scan_id] = None  # sentinel: running
    asyncio.create_task(_run_scan_background(scan_id, filters, scanner))
    return ScanJob(scan_id=scan_id, status="running")


@router.get("/scan/{scan_id}", response_model=ScanJob)
async def get_scan_result(scan_id: str) -> ScanJob:
    """Poll for scan results. Status: running | complete | failed."""
    if scan_id not in _scan_jobs:
        raise HTTPException(status_code=404, detail="Scan not found")
    job = _scan_jobs[scan_id]
    if job is None:
        return ScanJob(scan_id=scan_id, status="running")
    if isinstance(job, str):
        return ScanJob(scan_id=scan_id, status="failed", error=job)
    return ScanJob(scan_id=scan_id, status="complete", result=job)


@router.get("/universe", response_model=list[str])
async def get_default_universe() -> list[str]:
    """Return the default symbol universe used when no symbols are specified."""
    return list(DEFAULT_UNIVERSE)


@router.get("/filters/defaults", response_model=ScannerFilters)
async def get_default_filters() -> ScannerFilters:
    """Return default filter configuration."""
    return ScannerFilters()


# ---------------------------------------------------------------------------
# Filter presets — stored server-side in SQLite so they survive browser data
# clearing and are shared across origins (dev 5173, built app on 8001).
# ---------------------------------------------------------------------------

# Dedicated tiny DB — the ML outcomes DB takes long write locks during
# labeling runs, which would stall (or 500) these lightweight UI reads.
_PRESETS_DB = "backend/data/ui_presets.db"
_PRESET_NAME_MAX = 60


def _presets_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_PRESETS_DB), exist_ok=True)
    conn = sqlite3.connect(_PRESETS_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ui_presets (
            name         TEXT PRIMARY KEY,
            filters_json TEXT NOT NULL,
            updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return conn


def _presets_read() -> dict[str, dict]:
    with _presets_conn() as conn:
        rows = conn.execute("SELECT name, filters_json FROM ui_presets ORDER BY name").fetchall()
    out = {}
    for name, fj in rows:
        try:
            out[name] = json.loads(fj)
        except json.JSONDecodeError:
            logger.warning("Corrupt preset %r skipped", name)
    return out


@router.get("/presets")
async def list_presets() -> dict[str, dict]:
    """All saved filter presets, keyed by name."""
    return await asyncio.to_thread(_presets_read)


@router.put("/presets/{name}")
async def save_preset(name: str, filters: ScannerFilters) -> dict:
    """Create or overwrite a named preset."""
    name = name.strip()
    if not name or len(name) > _PRESET_NAME_MAX:
        raise HTTPException(422, f"Preset name must be 1-{_PRESET_NAME_MAX} characters")

    def _write() -> None:
        with _presets_conn() as conn:
            conn.execute(
                "INSERT INTO ui_presets (name, filters_json, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(name) DO UPDATE SET "
                "  filters_json = excluded.filters_json, "
                "  updated_at = CURRENT_TIMESTAMP",
                (name, json.dumps(filters.model_dump(mode="json"))),
            )

    await asyncio.to_thread(_write)
    return {"saved": name}


@router.delete("/presets/{name}", status_code=204)
async def delete_preset(name: str) -> None:
    """Delete a named preset."""
    def _delete() -> int:
        with _presets_conn() as conn:
            return conn.execute("DELETE FROM ui_presets WHERE name = ?", (name,)).rowcount

    if await asyncio.to_thread(_delete) == 0:
        raise HTTPException(404, f"Preset '{name}' not found")
