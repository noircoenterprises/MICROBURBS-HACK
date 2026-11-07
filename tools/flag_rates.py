#!/usr/bin/env python3
"""How common is each flag across City of Sydney homes?

    server/.venv/bin/python tools/flag_rates.py

Picks random home addresses from the API's suburb address lists, calls /risks/all for each at no more
than 8 calls a second, and prints percentages. Only the counts are kept: no API response is saved.

Homes are ranked by a hash of the seed and the address ID, not shuffled. A shuffle reorders everything
if the list changes by even one address (it does change between runs); this picks the same homes.
"""

import hashlib
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server")
sys.path.insert(0, SERVER)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(SERVER, ".env"))

from address import parse_address  # noqa: E402
from microburbs import ApiError, Microburbs, OutsideAreaError  # noqa: E402

SEED = 20261107
SAMPLE = 200
NEAR_M = 200
CALLS_PER_SECOND = 8
HOME_TYPES = {"unit", "apartment", "studio", "residential", "house", "terrace", "townhouse"}
FLAGS = {
    "flood": "Flood",
    "historical_flood": "Past flooding",
    "heritage": "Heritage",
    "hv_power_line": "High-voltage power lines",
    "public_housing": "Public housing (estimated)",
}

client = Microburbs(timeout=30)
pool = ThreadPoolExecutor(6)
lock = threading.Lock()
next_slot = [0.0]


def get(path, **params):
    """One call, spaced out to stay under the rate limit. None if the address ID has been retired."""
    with lock:
        now = time.monotonic()
        slot = max(now, next_slot[0])
        next_slot[0] = slot + 1 / CALLS_PER_SECOND
    time.sleep(max(0, slot - now))
    try:
        return client.fetch(path, **params).data
    except (OutsideAreaError, ApiError):
        return None


def is_home(row):
    """A real home: not a shop or office, and not a record for a whole building of flats."""
    if row.get("dwelling_type") not in HOME_TYPES:
        return False
    a = parse_address(row["address"])
    return a.is_home and bool(a.unit or (row.get("flats_in_building") or 1) <= 1)


def home_addresses():
    rows = []
    for name in [s["suburb"] for s in client.suburbs().data]:
        path = f"/v1/suburbs/{quote(name)}/properties"
        first = get(path, limit=1000, offset=0)
        offsets = range(1000, first["meta"]["total"], 1000)
        for page in [first, *pool.map(lambda o: get(path, limit=1000, offset=o), offsets)]:
            rows += [r for r in (page or {}).get("results", []) if is_home(r)]
    return rows


def main():
    homes = home_addresses()
    print(f"{len(homes):,} home addresses in the list")
    homes.sort(key=lambda r: hashlib.sha256(f"{SEED}:{r['gnaf_pid']}".encode()).hexdigest())

    tally = {key: {"on": 0, "near": 0} for key in FLAGS}
    any_on = any_near = strict_clear = done = retired = position = 0
    while done < SAMPLE:
        batch = homes[position:position + SAMPLE - done]
        position += len(batch)
        for layers in pool.map(lambda r: get(f"/v1/properties/{r['gnaf_pid']}/risks/all"), batch):
            if layers is None:
                retired += 1
                continue
            done += 1
            on_this_home = near_this_home = strict_this_home = False
            for key in FLAGS:
                items = [i for i in layers.get(key) or [] if i.get("nearest_distance_m") is not None]
                on = any(i.get("on_property") for i in items)
                near = on or any(i["nearest_distance_m"] < NEAR_M for i in items)
                tally[key]["on"] += on
                tally[key]["near"] += near
                if key != "public_housing":
                    on_this_home |= on
                    near_this_home |= near
                    # The stricter rule: heritage counts only when it's on the property itself.
                    strict_this_home |= on if key == "heritage" else near
            any_on += on_this_home
            any_near += near_this_home
            strict_clear += not strict_this_home

    pct = lambda n: f"{n / SAMPLE:.1%}"
    print(f"\nSeed {SEED}. {SAMPLE} homes checked, {retired} retired address IDs skipped.")
    print(f"{'FLAG':<30} {'ON PROPERTY':>12} {'WITHIN 200 M':>13}")
    for key, label in FLAGS.items():
        print(f"{label:<30} {pct(tally[key]['on']):>12} {pct(tally[key]['near']):>13}")
    print(f"{'Flood, heritage or power lines':<30} {pct(any_on):>12} {pct(any_near):>13}")
    print(f"\n'Within 200 m' includes on the property. Homes showing the all-clear line: {pct(SAMPLE - any_near)}")
    print(f"All-clear line if heritage only counted on the property itself: {pct(strict_clear)}")


if __name__ == "__main__":
    main()
