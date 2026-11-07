#!/usr/bin/env python3
"""Run /lookup on a file of addresses and print a table of how each one matched.

    python3 tools/check_matches.py tools/dev_addresses.txt
    python3 tools/check_matches.py tools/holdout_addresses.txt https://your-server.vercel.app

Each line of the file is an address, optionally followed by "|" and a listing link.
"""

import json
import sys
import time
import urllib.parse
import urllib.request

# What the dev addresses should do. Any other address shows "?" until a person checks it.
EXPECTED = {
    "1001/2 Sam Sing Street, Waterloo NSW 2017": "exact",
    "214/219-231 Botany Road, Waterloo NSW 2017": "pick",  # the data has this building but no unit 214
    "D534/810-822 Elizabeth Street, Waterloo NSW 2017": "exact",
    "911 Bourke Street, Waterloo NSW 2017": "pick",
    "33 Griffin Street, Surry Hills NSW 2010": "exact",
    "403/417-419 Bourke Street, Surry Hills NSW 2010": "exact",
    "23-47 Flinders Street, Surry Hills NSW 2010": "pick",
    "18E/4 Distillery Drive, Pyrmont NSW 2009": "exact",
    "164 Baptist Street, Redfern NSW 2016": "exact",
    "306/10 Jaques Avenue, Bondi Beach NSW 2026": "outside",
}


def lookup(server, address):
    url = f"{server.rstrip('/')}/lookup?{urllib.parse.urlencode({'address': address})}"
    started = time.monotonic()
    with urllib.request.urlopen(url, timeout=60) as resp:
        body = json.load(resp)
    return body, time.monotonic() - started


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    server = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    with open(sys.argv[1]) as f:
        addresses = [line.split("|")[0].strip() for line in f if line.strip()]

    print(f"{'ADDRESS':<50} {'MATCH':<8} {'EXPECTED':<9} {'OK':<3} {'SECS':>5}  RESULT")
    right = checked = 0
    for address in addresses:
        try:
            body, secs = lookup(server, address)
        except Exception as e:
            print(f"{address:<50} {'ERROR':<8} {EXPECTED.get(address, '?'):<9} {'':<3} {'':>5}  {type(e).__name__}")
            continue
        match = body.get("match", "?")
        expected = EXPECTED.get(address, "?")
        ok = ""
        if expected != "?":
            checked += 1
            right += match == expected
            ok = "yes" if match == expected else "NO"
        if match == "exact":
            result = body.get("address", "")
        elif match == "pick":
            result = "; ".join(c["address"] for c in body.get("candidates", [])[:3])
        else:
            result = body.get("message", "")
        print(f"{address:<50} {match:<8} {expected:<9} {ok:<3} {secs:>5.1f}  {result[:90]}")
    if checked:
        print(f"\nAs expected: {right} of {checked}")


if __name__ == "__main__":
    main()
