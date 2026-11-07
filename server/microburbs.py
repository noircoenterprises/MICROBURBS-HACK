"""A tiny client for the Microburbs Hackathon API.

Every response comes back in one envelope:

    {"data": {...}}                                  -> success
    {"data": null, "available": false, "message": ...} -> nothing to show (still HTTP 200)

and anything outside the City of Sydney returns HTTP 403. This module turns
those three cases into something easy to branch on:

    result = client.get("/v1/properties/GANSW705970502/basics/all")
    result.data      # the payload, or None
    result.message   # a human-readable reason when data is None

Successful responses are cached in memory for an hour, so a page that is
viewed twice doesn't pay for its calls twice. The client has no web-framework
dependency, so you can reuse it in a script or notebook.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

DEFAULT_BASE = "https://api-ht.microburbs.com.au"
CACHE_TTL_SECONDS = 60 * 60  # the data changes daily at most


class OutsideAreaError(Exception):
    """HTTP 403: the property or suburb is outside the hackathon area."""


class ApiError(Exception):
    """Any other non-2xx response (bad key, rate limit, server error)."""


@dataclass
class Result:
    data: Any
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None


class Microburbs:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 20):
        self.api_key = api_key or os.environ.get("MICROBURBS_API_KEY")
        if not self.api_key:
            raise ValueError("Set MICROBURBS_API_KEY (see README).")
        self.base_url = (base_url or os.environ.get("MICROBURBS_API_BASE") or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {self.api_key}"
        self._cache: dict[tuple, tuple[float, Result]] = {}
        self._lock = threading.Lock()

    def get(self, path: str, **params: Any) -> Result:
        key = (path, tuple(sorted(params.items())))
        with self._lock:
            hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]

        result = self.fetch(path, **params)
        with self._lock:
            if len(self._cache) > 5000:  # crude bound on memory; fine for a demo
                self._cache.clear()
            self._cache[key] = (time.monotonic(), result)
        return result

    def fetch(self, path: str, **params: Any) -> Result:
        """One API call with no cache. Waits and retries when rate limited (HTTP 429)."""
        for attempt in range(4):
            try:
                resp = self.session.get(f"{self.base_url}{path}", params=params or None, timeout=self.timeout)
            except requests.RequestException as e:
                raise ApiError(f"network problem: {type(e).__name__}") from e
            if resp.status_code != 429:
                break
            try:
                wait = float(resp.headers.get("Retry-After", ""))
            except ValueError:
                wait = 0.5 * (attempt + 1)
            time.sleep(min(wait, 3))
        if resp.status_code == 403:
            raise OutsideAreaError(_detail(resp))
        if not resp.ok:
            raise ApiError(f"{resp.status_code}: {_detail(resp)}")
        try:
            body = resp.json()
        except ValueError as e:
            raise ApiError("the API sent something that wasn't JSON") from e
        return Result(data=body.get("data"), message=body.get("message"))

    # --- Lookups -----------------------------------------------------------

    def suburbs(self) -> Result:
        return self.get("/v1/suburbs/list")

    def geocode_address(self, address: str) -> Result:
        return self.get("/v1/geocode/address", address=address)

    def geocode_suburb(self, q: str) -> Result:
        """Typo-tolerant suburb autocomplete: 'surey' -> 'Surry Hills'."""
        return self.get("/v1/geocode/suburb", q=q)

    # --- Property endpoints (keyed by GNAF id) ------------------------------

    def property(self, gnaf_id: str, endpoint: str, **params: Any) -> Result:
        """GET /v1/properties/{gnaf_id}/{endpoint}, e.g. endpoint='basics/all'."""
        return self.get(f"/v1/properties/{quote(gnaf_id)}/{endpoint}", **params)

    # --- Suburb endpoints (keyed by exact ABS suburb name) ------------------

    def suburb(self, name: str, endpoint: str, **params: Any) -> Result:
        """GET /v1/suburbs/{name}/{endpoint}. Names are exact, e.g. 'Glebe (NSW)'."""
        return self.get(f"/v1/suburbs/{quote(name)}/{endpoint}", **params)


def _detail(resp: requests.Response) -> str:
    try:
        return str(resp.json().get("detail", resp.text))
    except ValueError:
        return resp.text
