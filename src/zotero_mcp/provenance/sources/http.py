"""Shared HTTP for adapters: the package's one User-Agent, a timeout,
per-adapter spacing between requests, and a bounded retry on 429/5xx."""

from __future__ import annotations

import threading
import time

import requests

from zotero_mcp.provenance.sources.base import SourceUnavailable
from zotero_mcp.utils import USER_AGENT

TIMEOUT = 30
_last: dict[str, float] = {}
_lock = threading.Lock()


def _space(key: str, min_interval: float) -> None:
    with _lock:
        wait = _last.get(key, 0.0) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[key] = time.monotonic()


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None,
             key: str = "default", min_interval: float = 0.2, retries: int = 2) -> dict | list:
    """GET a JSON document. Raises SourceUnavailable on network or HTTP failure,
    so a failed lookup is never mistaken for an empty result."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    last_err = ""
    for attempt in range(retries + 1):
        _space(key, min_interval)
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=TIMEOUT)
        except requests.RequestException as e:
            last_err = f"network error: {e}"
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as e:
                raise SourceUnavailable(f"{key}: response was not JSON ({e})") from e
        last_err = f"HTTP {resp.status_code}"
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(min(8, 2 ** attempt))
            continue
        break
    raise SourceUnavailable(f"{key}: {last_err}")
