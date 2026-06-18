"""
Schwab Market Data API client.

Provides real-time options chains with broker-calculated greeks (delta, gamma,
theta, vega, rho).  Replaces yfinance for chain fetching; yfinance is retained
only for historical IV rank computation.

Usage:
  - Run backend/scripts/schwab_auth.py ONCE to complete the OAuth flow and save
    the token file.  If SCHWAB_TOKEN_KEY is set in .env the token is stored
    encrypted at backend/.schwab_token.enc; otherwise plaintext at
    SCHWAB_TOKEN_PATH.
  - On subsequent starts the scanner auto-loads (and decrypts) the token; no
    user interaction needed.
  - If the token file is missing, is_available returns False and the scanner
    falls back to yfinance automatically.

Token encryption (at rest):
  - Set SCHWAB_TOKEN_KEY in backend/.env (generate with the command in settings.py).
  - On startup: .schwab_token.enc is decrypted to a temp file; schwab-py uses
    the temp file normally (including auto-refresh writes).
  - On shutdown (atexit): temp file is re-encrypted back to .schwab_token.enc
    and the temp file is deleted.
  - The plaintext token exists only in memory / a temp file during the app's
    runtime.
"""

import asyncio
import atexit
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Optional

from backend.models.options import OptionQuote, OptionType

logger = logging.getLogger(__name__)

# Keep Schwab calls modest — their market data tier allows ~120 req/min.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="schwab")
_SCHWAB_SEMAPHORE = asyncio.Semaphore(8)


class SchwabClient:
    """
    Async wrapper around schwab-py (sync client in thread pool).

    On init it resolves and loads the token file (decrypting if a key is
    configured).  If neither the encrypted nor plaintext token exists,
    is_available is False and every method raises RuntimeError so callers can
    fall back to yfinance.
    """

    def __init__(self, app_key: str, app_secret: str, token_path: str):
        self.app_key = app_key
        self.app_secret = app_secret
        # Resolve relative paths from project root (CWD when uvicorn runs)
        p = Path(token_path)
        self.token_path = p if p.is_absolute() else Path.cwd() / p
        self._client = None
        self._available = False
        self._temp_token_path: Optional[Path] = None
        self._try_init()

    # ------------------------------------------------------------------
    # Token resolution (plaintext or encrypted)
    # ------------------------------------------------------------------

    def _enc_path(self) -> Path:
        """Encrypted token path derived from SCHWAB_TOKEN_PATH stem."""
        return self.token_path.parent / (self.token_path.stem + ".enc")

    def _resolve_token_path(self) -> Optional[Path]:
        """
        Return the path schwab-py should use for the token file.

        - If SCHWAB_TOKEN_KEY is set: decrypt .schwab_token.enc → temp file,
          register atexit re-encryption, return temp path.
        - Otherwise: return SCHWAB_TOKEN_PATH directly (plaintext, backward-compat).
        - Returns None if the required file is missing or decryption fails.
        """
        from backend.config.settings import get_settings
        settings = get_settings()

        if settings.SCHWAB_TOKEN_KEY:
            enc = self._enc_path()
            if not enc.exists():
                logger.warning(
                    "Encrypted Schwab token not found at %s. "
                    "Run `backend/.venv/Scripts/python.exe -m backend.scripts.schwab_auth`. "
                    "Falling back to yfinance.",
                    enc,
                )
                return None
            try:
                from cryptography.fernet import Fernet
                fernet = Fernet(settings.SCHWAB_TOKEN_KEY.encode())
                decrypted = fernet.decrypt(enc.read_bytes())

                fd, tmp = tempfile.mkstemp(
                    suffix=".json",
                    prefix=".schwab_tmp_",
                    dir=self.token_path.parent,
                )
                os.close(fd)
                tmp_path = Path(tmp)
                tmp_path.write_bytes(decrypted)
                self._temp_token_path = tmp_path

                atexit.register(self._reencrypt_and_cleanup)
                logger.info("Schwab token decrypted to temp file for runtime use.")
                return tmp_path
            except Exception as e:
                logger.warning(
                    "Failed to decrypt Schwab token: %s. Falling back to yfinance.", e
                )
                self._cleanup_temp()
                return None
        else:
            if not self.token_path.exists():
                logger.warning(
                    "Schwab token not found at %s. "
                    "Run `backend/.venv/Scripts/python.exe -m backend.scripts.schwab_auth`. "
                    "Falling back to yfinance.",
                    self.token_path,
                )
                return None
            return self.token_path

    def _reencrypt_and_cleanup(self) -> None:
        """
        atexit handler: re-encrypt the (possibly refreshed) temp token back to
        .schwab_token.enc, then delete the temp file.
        """
        if not self._temp_token_path or not self._temp_token_path.exists():
            return
        try:
            from backend.config.settings import get_settings
            from cryptography.fernet import Fernet
            settings = get_settings()
            fernet = Fernet(settings.SCHWAB_TOKEN_KEY.encode())
            encrypted = fernet.encrypt(self._temp_token_path.read_bytes())
            self._enc_path().write_bytes(encrypted)
            logger.info("Schwab token re-encrypted to %s on shutdown.", self._enc_path())
        except Exception as e:
            logger.warning("Failed to re-encrypt Schwab token on shutdown: %s", e)
        finally:
            self._cleanup_temp()

    def _cleanup_temp(self) -> None:
        if self._temp_token_path and self._temp_token_path.exists():
            try:
                self._temp_token_path.unlink()
            except Exception:
                pass
        self._temp_token_path = None

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _try_init(self) -> None:
        try:
            import schwab  # noqa: F401 — import check
        except ImportError:
            logger.warning(
                "schwab-py not installed. Run: pip install schwab-py. "
                "Falling back to yfinance for options chains."
            )
            return

        effective_path = self._resolve_token_path()
        if effective_path is None:
            return

        try:
            import schwab
            self._client = schwab.auth.client_from_token_file(
                token_path=str(effective_path),
                api_key=self.app_key,
                app_secret=self.app_secret,
            )
            self._available = True
            logger.info("SchwabClient ready (token: %s)", effective_path)
        except Exception as e:
            self._cleanup_temp()
            logger.warning("Schwab client init failed: %s. Falling back to yfinance.", e)

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    def token_days_remaining(self) -> Optional[float]:
        """
        Return estimated days until the Schwab refresh token expires.

        Schwab refresh tokens are valid for 7 days from creation_timestamp.
        Returns None if the token file can't be read (e.g. not yet authenticated).
        """
        import json
        import time

        # Prefer the live temp file (encrypted mode); fall back to plaintext path.
        path = None
        if self._temp_token_path and self._temp_token_path.exists():
            path = self._temp_token_path
        elif self.token_path.exists():
            path = self.token_path

        if path is None:
            return None

        try:
            data = json.loads(path.read_text())
            created = data.get("creation_timestamp")
            if created:
                elapsed_days = (time.time() - float(created)) / 86400.0
                return max(0.0, 7.0 - elapsed_days)
            # Fallback: use file mtime (less accurate but better than nothing)
            elapsed_days = (time.time() - path.stat().st_mtime) / 86400.0
            return max(0.0, 7.0 - elapsed_days)
        except Exception as e:
            logger.debug("Could not read token expiry: %s", e)
            return None

    async def _run(self, fn, *args):
        """Run a synchronous schwab-py call in the thread pool with a semaphore."""
        loop = asyncio.get_event_loop()
        async with _SCHWAB_SEMAPHORE:
            return await asyncio.wait_for(
                loop.run_in_executor(_executor, fn, *args),
                timeout=15.0,
            )

    # ------------------------------------------------------------------
    # Public interface (mirrors YFinanceClient)
    # ------------------------------------------------------------------

    async def get_quote(self, symbol: str) -> dict:
        """Return real-time spot price dict with key 'price'."""
        if not self.is_available:
            raise RuntimeError("SchwabClient not available")

        def _fetch():
            r = self._client.get_quote(symbol)
            r.raise_for_status()
            data = r.json()
            q = data.get(symbol, {}).get("quote", {})
            return {
                "symbol": symbol,
                "price": float(q.get("lastPrice") or q.get("mark") or 0),
                "fifty_two_week_high": float(q.get("52WeekHigh") or 0),
                "fifty_two_week_low": float(q.get("52WeekLow") or 0),
                "previous_close": float(q.get("closePrice") or 0),
            }

        return await self._run(_fetch)

    async def get_expirations(self, symbol: str) -> list[str]:
        """Return sorted list of available expiration date strings (YYYY-MM-DD)."""
        if not self.is_available:
            raise RuntimeError("SchwabClient not available")

        def _fetch():
            from schwab.client import Client
            r = self._client.get_option_chain(
                symbol,
                contract_type=Client.Options.ContractType.ALL,
            )
            r.raise_for_status()
            data = r.json()
            dates: set[str] = set()
            for key in (
                list(data.get("callExpDateMap", {}).keys())
                + list(data.get("putExpDateMap", {}).keys())
            ):
                # Key format: "YYYY-MM-DD:DTE"
                dates.add(key.split(":")[0])
            return sorted(dates)

        return await self._run(_fetch)

    async def get_options_chain(
        self, symbol: str, expiration: str, spot_price: float
    ) -> tuple[list[OptionQuote], list[OptionQuote]]:
        """
        Fetch real-time options chain for a specific expiration.
        Returns (calls, puts) as OptionQuote lists with broker greeks.
        spot_price is unused (included for interface parity with YFinanceClient).
        """
        if not self.is_available:
            raise RuntimeError("SchwabClient not available")

        exp_date = date.fromisoformat(expiration)

        def _fetch():
            from schwab.client import Client
            r = self._client.get_option_chain(
                symbol,
                contract_type=Client.Options.ContractType.ALL,
                from_date=exp_date,
                to_date=exp_date,
            )
            r.raise_for_status()
            return r.json()

        data = await self._run(_fetch)

        calls = self._parse_exp_map(
            data.get("callExpDateMap", {}), symbol, exp_date, OptionType.CALL
        )
        puts = self._parse_exp_map(
            data.get("putExpDateMap", {}), symbol, exp_date, OptionType.PUT
        )
        return calls, puts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_exp_map(
        self,
        exp_map: dict,
        underlying: str,
        expiration: date,
        option_type: OptionType,
    ) -> list[OptionQuote]:
        """
        Parse Schwab callExpDateMap / putExpDateMap into OptionQuote objects.

        Map structure:
            {"YYYY-MM-DD:DTE": {"strike": [option_dict, ...]}, ...}

        Key IV note: Schwab returns `volatility` in percentage form (25.5 = 25.5%),
        so we divide by 100 to get the decimal IV used throughout the rest of the system.
        """
        quotes: list[OptionQuote] = []
        exp_str = expiration.strftime("%Y-%m-%d")

        for key, strikes in exp_map.items():
            if not key.startswith(exp_str):
                continue  # different expiration — skip

            for strike_str, options in strikes.items():
                for opt in options:
                    try:
                        bid = float(opt.get("bid") or 0)
                        ask = float(opt.get("ask") or 0)
                        mid = round((bid + ask) / 2, 4)
                        last = float(opt.get("last") or mid)

                        # IV: Schwab reports as a percent (e.g. 25.5 → 0.255)
                        iv_raw = opt.get("volatility") or 0
                        iv = float(iv_raw) / 100.0

                        # Greeks — broker-calculated, no Black-Scholes needed
                        delta = float(opt.get("delta") or 0)
                        gamma = float(opt.get("gamma") or 0)
                        theta = float(opt.get("theta") or 0)
                        vega = float(opt.get("vega") or 0)
                        rho = float(opt.get("rho") or 0)

                        quotes.append(
                            OptionQuote(
                                symbol=str(opt.get("symbol", f"{underlying}_opt")),
                                underlying=underlying,
                                expiration=expiration,
                                strike=float(strike_str),
                                option_type=option_type,
                                bid=bid,
                                ask=ask,
                                mid=mid,
                                last=last,
                                volume=int(opt.get("totalVolume") or 0),
                                open_interest=int(opt.get("openInterest") or 0),
                                implied_volatility=iv,
                                delta=delta,
                                gamma=gamma,
                                theta=theta,
                                vega=vega,
                                rho=rho,
                            )
                        )
                    except Exception as e:
                        logger.debug("Skipping bad Schwab option row: %s", e)
                        continue

        return quotes
