"""
Shared rate-limiter instance.

Kept in a separate module to avoid circular imports between main.py and route modules.
Import this in routes instead of importing from backend.main.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
