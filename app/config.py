"""
Config loader for the Immich Drop Uploader (Python).
Reads ONLY from .env; there is NO runtime mutation from the UI.
"""

from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass
class Settings:
    """App settings loaded from environment variables (.env)."""
    immich_base_url: str
    immich_api_key: str
    max_concurrent: int = 3

    @property
    def normalized_base_url(self) -> str:
        """Return the base URL without a trailing slash for clean joining and display."""
        return self.immich_base_url.rstrip("/")

def load_settings() -> Settings:
    """Load settings from .env, applying defaults when absent."""
    base = os.getenv("IMMICH_BASE_URL", "http://127.0.0.1:2283/api")
    api_key = os.getenv("IMMICH_API_KEY", "")
    try:
        maxc = int(os.getenv("MAX_CONCURRENT", "3"))
    except ValueError:
        maxc = 3
    return Settings(immich_base_url=base, immich_api_key=api_key, max_concurrent=maxc)
