"""Property Report: a one-page property report built on the Microburbs Hackathon API.

FastAPI renders every page on the server with Jinja2 templates; htmx adds the
live search and the lazily loaded suburb panel; Tailwind CSS (prebuilt into
static/app.css) styles it. The API key never leaves the server.

Run locally:   uvicorn main:app --reload
On Vercel:     zero config; Vercel finds `app` in main.py.

Routes
  GET /                              home page: one search box for any address or suburb
  GET /search?q=...                  htmx partial: suburb and address suggestions as you type
  GET /go?q=...                      Enter in the search box: redirect to the best match
  GET /suburb/{name}                 suburb page: market, people, price trend, recent sales
  GET /suburb/{name}/sales?offset=   htmx partial: the next page of recent sales
  GET /property/{gnaf_id}            the report (a plain, shareable URL)
  GET /property/{gnaf_id}/suburb     htmx partial: the suburb panel under the report
  GET /suburb-trend?suburb=&kind=    htmx partial: suburb median price chart (stands in for
                                     the value chart on apartments, which have no series)
  GET /lookup?address=               the Chrome extension's call: match an address, return the panel's facts
  GET /lookup?gnaf_id=               the same facts for a home the user picked from a list
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from address import Address, clean_key, full_street, parse_address, pretty, same_number, swapped_unit, tidy, unit_key
from microburbs import ApiError, Microburbs, OutsideAreaError

load_dotenv()  # local development: read MICROBURBS_API_KEY from .env (on Vercel, set it in the dashboard)

HERE = Path(__file__).parent
app = FastAPI(title="Property Report", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origin_regex=r"^chrome-extension://[a-z]+$", allow_methods=["GET"])
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

# --------------------------------------------------------------------------
# Password gate. DEMO_GATE=on turns it on, with the password in DEMO_PASSWORD;
# off or unset leaves the site open, so a local copy runs as before. On with no
# password lets nobody in.
# --------------------------------------------------------------------------

GATE_ON = os.environ.get("DEMO_GATE", "off").strip().lower() == "on"
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "")
GATE_COOKIE = "demo_gate"
GATE_OPEN = {"/login", "/favicon.ico"}


def gate_token(password: str) -> str:
    return hashlib.sha256(f"demo-gate:{password}".encode()).hexdigest()


def safe_next(target: str) -> str:
    """Only send people back to a page on this site."""
    return target if target.startswith("/") and not target.startswith("//") else "/"


@app.middleware("http")
async def password_gate(request: Request, call_next):
    path = request.url.path
    if not GATE_ON or path in GATE_OPEN or path.startswith("/static/"):
        return await call_next(request)
    if DEMO_PASSWORD and hmac.compare_digest(request.cookies.get(GATE_COOKIE, ""), gate_token(DEMO_PASSWORD)):
        return await call_next(request)
    if request.headers.get("HX-Request"):  # an htmx partial: send the whole page to the login
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    target = path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(target)}", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"next": safe_next(next), "error": bool(error)})


@app.post("/login")
async def login(request: Request):
    form = parse_qs((await request.body()).decode())
    password = form.get("password", [""])[0]
    target = safe_next(form.get("next", ["/"])[0])
    if not DEMO_PASSWORD or not hmac.compare_digest(password.encode(), DEMO_PASSWORD.encode()):
        return RedirectResponse(f"/login?error=1&next={quote(target)}", status_code=303)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(GATE_COOKIE, gate_token(DEMO_PASSWORD), max_age=30 * 24 * 3600,
                        httponly=True, secure=True, samesite="lax")
    return response

# The property endpoints that make up one report. Each is one API call.
PROPERTY_ENDPOINTS = [
    "basics/all",                       # beds, baths, parking, dwelling type, land area
    "profile",                          # which suburb, postcode, SA2 ...
    "valuation/all",                    # estimated value and its 80% range
    "valuation/value-series",           # estimated value over time (houses only)
    "history/all",                      # sale and rental history
    "risks/all",                        # flood, heritage, bushfire, power lines ...
    "schools/all",                      # nearby schools with NAPLAN ranking
    "transport/nearby",                 # nearest train / bus, plus the property's coordinates
    "amenities/nearby",                 # supermarkets, parks, restaurants within 1 km
    "comparables/recent-sales-nearby",  # recent sales around it, with coordinates
]

# The suburb endpoints for the suburb page and the "About <suburb>" panel.
SUBURB_ENDPOINTS = [
    "market/all",           # median price and rent (with history), growth, yield, days on market
    "hero/summary",         # population and dwellings
    "demographics/income",  # household income brackets and the median
    "demographics/tenure",  # owners vs renters
]

SALES_PAGE = 25  # recent sales per page on the suburb page

RISK_LABELS = {
    "flood": "Flood",
    "historical_flood": "Historical flood",
    "bushfire": "Bushfire",
    "heritage": "Heritage",
    "landslide": "Landslide",
    "erosion": "Erosion",
    "environment": "Environmental",
    "hv_power_line": "High-voltage power line",
    "public_housing": "Public housing",
    "mobile_black_spot": "Mobile black spot",
}

OUTSIDE_AREA = ("That's outside the hackathon area. This demo covers the 29 suburbs of the City of Sydney "
                "(Surry Hills, Glebe, Pyrmont, Redfern, Zetland …).")

# A sale can be recorded against an address ID (GNAF) that the current address file no longer has:
# addresses get retired and re-issued, for example when a building's numbering changes. The API answers
# 403 for those IDs, the same as for an address outside the area, so a link from a sales list says so.
RETIRED_ADDRESS = ("This sale was recorded against an address ID ({gnaf_id}) that is no longer in the current "
                   "address file. Addresses get retired and re-issued, for example when a building's numbering "
                   "changes, so there is no report under this ID.")

EXAMPLES = [
    ("GANSW705970502", "26 Tudor Street, Surry Hills", "House"),
    ("GANSW708007997", "28/96-98 Elizabeth Bay Road, Elizabeth Bay", "Apartment"),
    ("GANSW704799290", "224 Glebe Point Road, Glebe", "House"),
]


# --------------------------------------------------------------------------
# API access
# --------------------------------------------------------------------------


@lru_cache
def client() -> Microburbs:
    return Microburbs()  # reads MICROBURBS_API_KEY / MICROBURBS_API_BASE from the environment


def call(fn, *args, **kwargs) -> dict:
    """Run one API call and flatten the three possible outcomes into a dict.

    {"data": ...}                       success (data may be None: nothing to show)
    {"data": None, "outside": True}     403, outside the hackathon area
    {"data": None, "error": True}       anything else went wrong
    """
    try:
        res = fn(*args, **kwargs)
        return {"data": res.data, "message": res.message}
    except OutsideAreaError as e:
        return {"data": None, "message": str(e), "outside": True}
    except ApiError as e:
        return {"data": None, "message": str(e), "error": True}


# One shared thread pool runs independent API calls at the same time (the API allows ~10 calls a second).
POOL = ThreadPoolExecutor(max_workers=8)


def fetch_all(fn, key: str, endpoints: list[str]) -> dict[str, dict]:
    """Call fn(key, endpoint) for every endpoint concurrently and wait for them all."""
    return dict(zip(endpoints, POOL.map(lambda ep: call(fn, key, ep), endpoints)))


def suburb_names() -> list[str]:
    """The 29 suburbs in the hackathon area, as exact ABS names (e.g. 'Glebe (NSW)'). Cached by the client."""
    return [s["suburb"] for s in call(client().suburbs)["data"] or []]


def search_everything(q: str) -> tuple[list[str], list[dict]]:
    """Suburbs and addresses matching what has been typed so far, looked up concurrently.

    Suburbs: a substring match on the 29 names, plus the API's typo-tolerant
    /v1/geocode/suburb ("surey" finds Surry Hills). Addresses: /v1/geocode/address.
    """
    suburbs_future = POOL.submit(call, client().geocode_suburb, q)
    addresses = (call(client().geocode_address, q)["data"] or []) if len(q) >= 3 else []

    needle = q.lower()
    suburbs = [n for n in suburb_names() if needle in suburb_label(n).lower()]
    for s in suburbs_future.result()["data"] or []:
        if s["area_name"] not in suburbs:
            suburbs.append(s["area_name"])
    return suburbs[:5], addresses[:8]


# --------------------------------------------------------------------------
# Template helpers
# --------------------------------------------------------------------------


def money(x: float | None, short: bool = False) -> str:
    if x is None:
        return "–"
    if short and x >= 1_000_000:
        return f"${x / 1_000_000:.2f}M"
    if short and x >= 1_000:
        return f"${x / 1_000:.0f}k"
    return f"${x:,.0f}"


def pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "–"
    return f"{x:+.1%}" if signed else f"{x:.1%}"


def metres(m: float | None) -> str:
    if m is None:
        return "–"
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{m:.0f} m"


def nice_date(iso: str | None, fmt: str = "%-d %b %Y") -> str:
    return date.fromisoformat(iso[:10]).strftime(fmt) if iso else "–"


def suburb_label(name: str) -> str:
    """'Glebe (NSW)' -> 'Glebe'. The API needs the exact name; people don't."""
    return re.sub(r"\s*\(.*\)$", "", name)


def report_url(gnaf_id: str, address: str, sale: bool = False) -> str:
    """Link to a property report, carrying the display address (and whether it came from a sales list)."""
    return f"/property/{gnaf_id}?" + urlencode({"address": address, **({"sale": 1} if sale else {})})


templates.env.filters.update(money=money, pct=pct, metres=metres, nice_date=nice_date, suburb_label=suburb_label)
templates.env.globals.update(report_url=report_url)


def property_kind(basics: dict) -> str:
    """Map a dwelling type onto the suburb market's two buckets: 'house' or 'unit'."""
    return "house" if (basics.get("dwelling_type") or "").lower() in ("house", "townhouse", "semi") else "unit"


def line_chart(lines: list[list[tuple[str, float]]], points: list[tuple[str, float]] = (),
               width: int = 720, height: int = 280) -> dict | None:
    """Scale one or more time series (and optional highlighted points) into SVG coordinates.

    Returns the geometry the `chart` macro in templates/_macros.html draws, so the
    page needs no charting library. Dates are ISO strings; values are dollars.
    """
    all_pts = [(date.fromisoformat(d[:7] + "-01"), v) for d, v in [*(p for s in lines for p in s), *points] if v]
    if len(all_pts) < 2:
        return None
    pad_l, pad_r, pad_t, pad_b = 60, 16, 16, 28
    x0, x1 = min(d for d, _ in all_pts).toordinal(), max(d for d, _ in all_pts).toordinal()
    y1 = max(v for _, v in all_pts) * 1.08
    sx = lambda d: pad_l + (date.fromisoformat(d[:7] + "-01").toordinal() - x0) / max(x1 - x0, 1) * (width - pad_l - pad_r)
    sy = lambda v: pad_t + (1 - v / y1) * (height - pad_t - pad_b)
    baseline = height - pad_b

    def polyline(series):
        pts = [(sx(d), sy(v)) for d, v in series if v]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        # The same line closed down to the baseline: the shaded area under it.
        area = f"{pts[0][0]:.1f},{baseline} {line} {pts[-1][0]:.1f},{baseline}" if pts else ""
        return {"line": line, "area": area}

    step = _nice_step(y1 / 4)
    first_year, last_year = date.fromordinal(x0).year, date.fromordinal(x1).year
    year_step = max(1, round((last_year - first_year) / 6))
    return {
        "width": width,
        "height": height,
        "lines": [polyline(s) for s in lines],
        "dots": [{"x": sx(d), "y": sy(v), "label": f"{nice_date(d)}: {money(v)}"} for d, v in points if v],
        "yticks": [{"y": sy(v), "label": money(v, short=True)} for v in range(0, int(y1), int(step))],
        "xticks": [{"x": sx(f"{y}-01"), "label": y} for y in range(first_year + 1, last_year + 1, year_step)],
        "plot_left": pad_l,
        "plot_right": width - pad_r,
        "baseline": baseline,
    }


def _nice_step(raw: float) -> float:
    magnitude = 10 ** (len(str(int(raw))) - 1)
    return next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)


def summarise_risks(layers: dict) -> list[dict]:
    """One row per risk layer, worst first: on the property, nearby (<200 m), or clear."""
    rows = []
    for key, label in RISK_LABELS.items():
        items = layers.get(key) or []
        if not items:
            rows.append({"label": label, "text": "None within 1 km", "level": "ok"})
            continue
        nearest = min(i["nearest_distance_m"] for i in items)
        if any(i.get("on_property") for i in items):
            rows.append({"label": label, "text": "On this property", "level": "high"})
        elif nearest < 200:
            rows.append({"label": label, "text": f"Nearby, {metres(nearest)} away", "level": "medium"})
        else:
            rows.append({"label": label, "text": f"Nearest {metres(nearest)} away", "level": "ok"})
    order = {"high": 0, "medium": 1, "ok": 2}
    return sorted(rows, key=lambda r: order[r["level"]])


def map_points(r: dict) -> dict | None:
    """Everything the Leaflet map draws, as plain JSON."""
    transport = r["transport/nearby"]["data"]
    if not transport:
        return None
    nearest = [
        {"lat": s["lat"], "lng": s["lng"], "name": f"{s.get('name') or s['label']} ({metres(s['distance_m'])})"}
        for s in (transport.get("nearest") or {}).values() if s
    ]
    amenities = [
        {"lat": a["lat"], "lng": a["lng"], "name": " · ".join(filter(None, [a.get("name"), a.get("category")]))}
        for a in ((r["amenities/nearby"]["data"] or {}).get("results") or [])[:60]
    ]
    sales = [
        {"lat": s["latitude"], "lng": s["longitude"],
         "name": f"{s['address'].title()} · sold {money(s['price'])}, {nice_date(s['date_sold'], '%b %Y')}"}
        for s in (r["comparables/recent-sales-nearby"]["data"] or [])[:30]
    ]
    return {"centre": [transport["center_lat"], transport["center_lng"]],
            "transport": nearest, "amenities": amenities, "sales": sales}


def suburb_context(suburb: str, s: dict[str, dict]) -> dict:
    """Shape the SUBURB_ENDPOINTS responses for the suburb templates."""
    income = s["demographics/income"]["data"] or []
    return {
        "suburb": suburb,
        "market": s["market/all"]["data"] or {},
        "hero": s["hero/summary"]["data"] or {},
        "median_income": income[0].get("median_income") if income else None,
        "tenure": s["demographics/tenure"]["data"] or {},
    }


def trend(market: dict, kind: str) -> list[tuple[str, float]]:
    """The suburb's monthly median sale price for 'house' or 'unit', as (date, value) pairs."""
    return [(p["date"], p["value"]) for p in ((market.get("median_sale_price_series") or {}).get(kind) or [])]


# --------------------------------------------------------------------------
# Routes: home and search
# --------------------------------------------------------------------------


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers ask for /favicon.ico at the root whatever the page says, so serve it there too."""
    return FileResponse(HERE / "static" / "favicon.ico", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
def home(request: Request, missed: str = ""):
    return templates.TemplateResponse(request, "index.html", {
        "suburbs": suburb_names(), "examples": EXAMPLES, "missed": missed,
    })


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    """htmx partial: suggestions for what has been typed so far."""
    q = q.strip()
    if len(q) < 2:
        return HTMLResponse("")
    suburbs, addresses = search_everything(q)
    return templates.TemplateResponse(request, "_search_results.html", {
        "q": q, "suburbs": suburbs, "addresses": addresses,
    })


@app.get("/go")
def go(q: str = ""):
    """Enter in the search box: a suburb whose name matches exactly, else the best address, else a suburb."""
    q = q.strip()
    if len(q) < 2:
        return RedirectResponse("/", status_code=303)
    suburbs, addresses = search_everything(q)
    exact = [s for s in suburbs if suburb_label(s).lower() == q.lower()]
    if exact:
        return RedirectResponse(app.url_path_for("suburb_page", name=exact[0]), status_code=303)
    if addresses:
        return RedirectResponse(report_url(addresses[0]["id"], addresses[0]["display_name"]), status_code=303)
    if suburbs:
        return RedirectResponse(app.url_path_for("suburb_page", name=suburbs[0]), status_code=303)
    return RedirectResponse("/?" + urlencode({"missed": q}), status_code=303)


# --------------------------------------------------------------------------
# Routes: suburb
# --------------------------------------------------------------------------


@app.get("/suburb/{name}", response_class=HTMLResponse)
def suburb_page(request: Request, name: str):
    sales_future = POOL.submit(call, client().suburb, name, "sales/recent", limit=SALES_PAGE)
    s = fetch_all(client().suburb, name, SUBURB_ENDPOINTS)
    sales = sales_future.result()["data"] or {}
    if s["market/all"].get("outside"):
        return templates.TemplateResponse(request, "error.html", {"message": OUTSIDE_AREA}, status_code=403)
    ctx = suburb_context(name, s)
    return templates.TemplateResponse(request, "suburb.html", {
        **ctx,
        "chart": line_chart([trend(ctx["market"], "house"), trend(ctx["market"], "unit")], width=1100, height=300),
        "sales": sales.get("results") or [],
        "total": sales.get("total") or 0,
        "next_offset": SALES_PAGE,
    })


@app.get("/suburb/{name}/sales", response_class=HTMLResponse)
def suburb_sales(request: Request, name: str, offset: int = 0):
    """htmx partial: the next page of recent sales (table rows, ending in a new "Show more" row)."""
    found = call(client().suburb, name, "sales/recent", limit=SALES_PAGE, offset=offset)["data"] or {}
    return templates.TemplateResponse(request, "_sales_rows.html", {
        "suburb": name, "sales": found.get("results") or [], "total": found.get("total") or 0,
        "next_offset": offset + SALES_PAGE,
    })


# --------------------------------------------------------------------------
# Routes: property
# --------------------------------------------------------------------------


@app.get("/property/{gnaf_id}", response_class=HTMLResponse)
def property_report(request: Request, gnaf_id: str, address: str = "", sale: bool = False):
    """The report. `address` is the display name (saves a lookup); `sale=1` marks a link from a sales list."""
    r = fetch_all(client().property, gnaf_id, PROPERTY_ENDPOINTS)

    if r["basics/all"].get("outside"):
        if sale and address:
            # The sale is in the area, so its address ID has been retired. Offer the address's current record.
            current = current_record(address)
            return templates.TemplateResponse(request, "error.html", {
                "title": "No report under this sale's address ID",
                "message": RETIRED_ADDRESS.format(gnaf_id=gnaf_id), "suggestions": current,
            }, status_code=404)
        return templates.TemplateResponse(request, "error.html", {"message": OUTSIDE_AREA}, status_code=403)
    if r["basics/all"].get("error"):
        return templates.TemplateResponse(request, "error.html",
                                          {"message": f"The API returned an error: {r['basics/all']['message']}"},
                                          status_code=502)

    basics = r["basics/all"]["data"] or {}
    profile = r["profile"]["data"] or {}
    history = r["history/all"]["data"] or {}
    sales = [s for s in history.get("sale_history") or [] if s.get("price")]
    series = r["valuation/value-series"]["data"] or []
    schools = r["schools/all"]["data"] or {}
    transport = r["transport/nearby"]["data"] or {}

    # Each sale with the change since the one before it.
    sales_table = sorted(sales, key=lambda s: s["date"], reverse=True)
    for newer, older in zip(sales_table, sales_table[1:]):
        newer["change"] = newer["price"] / older["price"] - 1

    return templates.TemplateResponse(request, "report.html", {
        "gnaf_id": gnaf_id,
        "address": address or _address_from(sales, profile, gnaf_id),
        "basics": basics,
        "kind": property_kind(basics),
        "profile": profile,
        "avm": (r["valuation/all"]["data"] or {}).get("avm"),
        "latest_sale": history.get("sale_history_latest"),
        "latest_rent": history.get("rent_history_latest"),
        "sales": sales_table,
        "chart": line_chart([[(p["month"], p["value"]) for p in series]], [(s["date"], s["price"]) for s in sales]),
        "risks": summarise_risks(r["risks/all"]["data"] or {}),
        "schools": (schools.get("ranking") or schools.get("nearby") or [])[:10],
        "transport": transport,
        "amenity_counts": (r["amenities/nearby"]["data"] or {}).get("counts") or {},
        "map": map_points(r),
        "raw": r,
    })


@app.get("/property/{gnaf_id}/suburb", response_class=HTMLResponse)
def suburb_panel(request: Request, gnaf_id: str, suburb: str, kind: str = "house", show_chart: bool = True):
    """htmx partial, loaded after the report renders: the suburb at a glance.

    show_chart=0 when the value card above already shows the suburb trend.
    """
    s = fetch_all(client().suburb, suburb, SUBURB_ENDPOINTS)
    if s["market/all"].get("outside"):
        return HTMLResponse(f"<p class='muted'>{OUTSIDE_AREA}</p>")
    ctx = suburb_context(suburb, s)
    return templates.TemplateResponse(request, "_suburb_panel.html", {
        **ctx,
        "kind": kind,
        "chart": line_chart([trend(ctx["market"], kind)], width=1100, height=240) if show_chart else None,
    })


@app.get("/suburb-trend", response_class=HTMLResponse)
def suburb_trend(request: Request, suburb: str, kind: str = "unit"):
    """htmx partial: the suburb's median price history for houses or units."""
    found = call(client().suburb, suburb, "market/median-sale-price-series")
    market = {"median_sale_price_series": found["data"] or {}}
    return templates.TemplateResponse(request, "_suburb_trend.html", {
        "suburb": suburb, "kind": kind, "chart": line_chart([trend(market, kind)]),
    })


def current_record(address: str) -> list[dict]:
    """Look a sale's address up again, keeping a candidate only if it is on the same street in the same suburb.

    Sales lists write units as 'Unit 903, 174-182 Goulburn Street, Surry Hills'; the geocoder matches the
    '903/174-182 Goulburn Street' form far better.
    """
    query = re.sub(r"^Unit (\w+), ", r"\1/", address)
    m = re.search(r"\d[\w-]*\s+([^,\d]+),\s*(.+)$", query)  # street name, then suburb
    if not m:
        return []
    street, suburb = m.group(1).strip().lower(), m.group(2).strip().lower()
    found = call(client().geocode_address, query)["data"] or []
    same = [a for a in found if street in a["display_name"].lower() and suburb in a["display_name"].lower()]
    return same[:1]


def _address_from(sales: list[dict], profile: dict, gnaf_id: str) -> str:
    """Best-effort address when the page was opened without ?address=..."""
    street = next((s["address"] for s in sales if s.get("address")), None)
    if street and profile.get("suburb"):
        return f"{street}, {suburb_label(profile['suburb'])}"
    return street or gnaf_id


# --------------------------------------------------------------------------
# GET /lookup, step 1: match the address to one home
#
# Showing facts for the wrong home is the worst thing this can do, so "exact"
# needs the unit, street number, street and suburb all to agree. Anything less
# becomes a list for the user to pick from. The types on the records are often
# wrong (flats marked "house"), so the matching relies on the address itself.
# --------------------------------------------------------------------------

NO_DATA = "No data"
MAX_CANDIDATES = 5
OUTSIDE_MESSAGE = "This home is outside the City of Sydney, the only area our Microburbs data covers."
NO_MATCH_MESSAGE = "We couldn't find that address. Check it and try again."
NO_UNIT_MESSAGE = "This listing doesn't show a unit number. Pick your unit, or type it below."
TRY_AGAIN_MESSAGE = "We couldn't reach the data just now. Please try again in a moment."


@dataclass
class Record:
    gnaf_id: str
    addr: Address
    kind: str  # "house", "unit" ...


def suburb_labels() -> list[str]:
    """The 29 suburbs as people write them: 'Waterloo', not 'Waterloo (NSW)'."""
    return [suburb_label(name) for name in suburb_names()]


def geocode_records(query: str, labels: list[str]) -> list[Record]:
    found = call(client().geocode_address, query)["data"] or []
    return [Record(c["id"], parse_address(c["display_name"], labels), (c.get("property_type") or "").lower())
            for c in found]


def same_place(p: Address, a: Address) -> bool:
    return a.street_key == p.street_key and same_number(p, a) and (not p.suburb_key or a.suburb_key == p.suburb_key)


def classify(p: Address, records: list[Record]) -> tuple[str | None, list[Record]]:
    """Compare the address with some records: ('exact', [home]), ('pick', [homes]) or (None, [])."""
    unique: dict[str, Record] = {}
    for r in records:
        unique.setdefault(r.gnaf_id, r)  # the geocoder comes first and writes ranges in full, so keep its version
    # A shop or office record only counts if the address asked for one.
    homes = [r for r in unique.values() if same_place(p, r.addr) and (r.addr.is_home or r.addr.unit_word == p.unit_word)]

    if p.unit:
        same_unit = ([r for r in homes if r.addr.unit == p.unit]
                     or [r for r in homes if unit_key(r.addr.unit) == unit_key(p.unit)])  # D534 is 534D, not 534
        closest = [r for r in same_unit if r.addr.lo == p.lo] or same_unit
        if len(closest) == 1:
            return ("exact", closest) if p.suburb_key else ("pick", closest)
        return ("pick", closest or homes) if homes else (None, [])

    units = [r for r in homes if r.addr.unit]
    whole = [r for r in homes if not r.addr.unit]
    if units:
        return "pick", whole + units  # several homes here and the address doesn't say which
    if len(whole) == 1:
        one = whole[0]
        is_range = p.hi is not None or one.addr.hi is not None
        if (one.kind == "unit" and is_range) or not p.suburb_key:
            return "pick", whole  # 23-47 Flinders St: a record for a whole building, not one flat
        return "exact", whole
    return ("pick", whole) if whole else (None, [])


def other_spellings(p: Address, already: str) -> list[str]:
    """Other ways to ask the geocoder: 'D534/810-822 Elizabeth St' is stored as '534D/810 Elizabeth St'."""
    where = f"{full_street(p.street)}, {p.suburb}" if p.suburb else full_street(p.street)
    first = re.match(r"\d+[A-Z]?", p.number).group()
    spellings = [f"{first} {where}", f"{p.number} {where}"]
    if p.unit:
        spellings.append(f"{p.unit}/{first} {where}")
        swapped = swapped_unit(p.unit)
        if swapped:
            spellings += [f"{swapped}/{p.number} {where}", f"{swapped}/{first} {where}"]
    return [q for q in dict.fromkeys(spellings) if q != already]


SUBURB_ROWS: dict[str, list[tuple[str, str, str]]] = {}  # in memory only, gone when the server restarts
SUBURB_ROWS_LOCK = threading.Lock()


def suburb_rows(name: str) -> list[tuple[str, str, str]]:
    """Every address in a suburb, as (address, id, type). Loaded once, the first time it's needed.

    The geocoder never returns more than 10 results, so this is how we see all of a building or a
    street. It takes a few seconds, so it only runs when the geocoder hasn't settled the match.
    """
    with SUBURB_ROWS_LOCK:
        if name in SUBURB_ROWS:
            return SUBURB_ROWS[name]
        path = f"/v1/suburbs/{quote(name)}/properties"
        first = call(client().fetch, path, limit=1000, offset=0)["data"]
        if not first:
            return []
        offsets = range(1000, first["meta"]["total"], 1000)
        pages = [first, *POOL.map(lambda o: call(client().fetch, path, limit=1000, offset=o)["data"], offsets)]
        rows = [(r["address"], r["gnaf_pid"], (r.get("property_type") or "").lower())
                for page in pages if page for r in page["results"]]
        if all(pages):  # keep it only if every page arrived
            SUBURB_ROWS[name] = rows
        return rows


def street_records(p: Address, suburb_name: str, labels: list[str]) -> list[Record]:
    """Every record on the address's street, from the suburb's full property list."""
    word = max(re.findall(r"[A-Z]+", p.street.upper()), key=len, default="")  # quick filter before parsing
    found = []
    for address, gnaf_id, kind in suburb_rows(suburb_name):
        if word in address:
            a = parse_address(address, labels)
            if a.street_key == p.street_key:
                a.suburb, a.suburb_key = p.suburb, p.suburb_key
                found.append(Record(gnaf_id, a, kind))
    return found


def records_covering(p: Address, on_street: list[Record], labels: list[str]) -> list[Record]:
    """Is the number inside a range? The property list keeps only a range's first number, so 911 can't be
    seen inside 903-921 there. The geocoder shows whole ranges, so ask it about the nearest lower numbers."""
    lower = sorted({r.addr.lo for r in on_street if r.addr.lo is not None and r.addr.lo < p.lo}, reverse=True)[:3]
    queries = [f"{n} {full_street(p.street)}, {p.suburb}" for n in lower]
    found = POOL.map(lambda q: geocode_records(q, labels), queries)
    return [r for records in found for r in records if same_place(p, r.addr)]


def nearest_on_street(p: Address, on_street: list[Record]) -> list[Record]:
    """The closest street numbers, one record each, for when this number isn't in the data at all."""
    best: dict[int, Record] = {}
    for r in on_street:
        if r.addr.lo is not None and r.addr.is_home and (r.addr.lo not in best or best[r.addr.lo].addr.unit):
            best[r.addr.lo] = r
    return sorted(best.values(), key=lambda r: abs(r.addr.lo - p.lo))[:MAX_CANDIDATES]


def is_live(r: Record) -> bool:
    """The suburb list still holds retired address IDs, and the API answers 403 for those."""
    return not call(client().property, r.gnaf_id, "profile").get("outside")


def live_only(p: Address, records: list[Record]) -> list[Record]:
    ordered = sorted(records, key=lambda r: unit_order(p, r))[:MAX_CANDIDATES * 2]
    return [r for r, live in zip(ordered, POOL.map(is_live, ordered)) if live]


def reissued_unit(retired: Record, records: list[Record]) -> Record | None:
    """The record that replaced a retired one, when the address was re-issued without its letter:
    534D/810 Elizabeth St became 534/810. Taken as the same flat only if nothing else has those digits."""
    digits = re.sub(r"\D", "", retired.addr.unit or "")
    if not digits or digits == retired.addr.unit:
        return None
    others = {r.gnaf_id: r for r in records
              if r.gnaf_id != retired.gnaf_id and r.addr.is_home and r.addr.street_key == retired.addr.street_key
              and same_number(retired.addr, r.addr) and re.sub(r"\D", "", r.addr.unit or "") == digits}
    if len(others) != 1:
        return None
    other = next(iter(others.values()))
    return other if other.addr.unit == digits and is_live(other) else None


def unit_order(p: Address, r: Record) -> tuple:
    """Whole-building records first, then the units closest to the one asked for, then in number order."""
    digits = [int(d) for d in re.findall(r"\d+", r.addr.unit or "")[:1]]
    wanted = [int(d) for d in re.findall(r"\d+", p.unit or "")[:1]]
    distance = abs(digits[0] - wanted[0]) if digits and wanted else 0
    return (bool(r.addr.unit), distance, digits, r.addr.unit or "")


def answer(p: Address, kind: str, found: list[Record], message: str = "") -> dict:
    if kind == "exact":
        return {"match": "exact", "address": pretty(found[0].addr), "gnaf_id": found[0].gnaf_id,
                "has_unit": bool(found[0].addr.unit), **({"note": message} if message else {})}
    multiple_homes = any(r.addr.unit for r in found)
    candidates = [{
        "gnaf_id": r.gnaf_id,
        "address": pretty(r.addr),
        "level": "building" if not r.addr.unit and (r.kind == "unit" or multiple_homes) else "home",
    } for r in sorted(found, key=lambda r: unit_order(p, r))[:MAX_CANDIDATES]]
    if not message:
        message = (f"We can't find unit {p.unit} at this address. It may be too new for our data. "
                   "Pick the closest match, or check the number." if p.unit else NO_UNIT_MESSAGE)
    return {"match": "pick", "address": pretty(p), "candidates": candidates, "message": message}


def match_address(text: str) -> dict:
    labels = suburb_labels()
    if not labels:
        return {"match": "none", "message": TRY_AGAIN_MESSAGE, "candidates": []}
    p = parse_address(text, labels)
    if p.suburb and p.suburb_key not in {clean_key(s) for s in labels}:
        return {"match": "outside", "address": pretty(p), "message": OUTSIDE_MESSAGE, "candidates": []}
    if not p.number:
        return {"match": "none", "message": NO_MATCH_MESSAGE, "candidates": []}

    # 1. Ask the geocoder in the form it matches best: "1001/2 Sam Sing Street, Waterloo".
    place = f"{p.number} {full_street(p.street)}" + (f", {p.suburb}" if p.suburb else "")
    query = f"{p.unit}/{place}" if p.unit else place
    records = geocode_records(query, labels)
    kind, found = classify(p, records)
    if kind == "exact" or (kind and not p.unit):
        return answer(p, kind, found)

    # 2. Ask again in other spellings.
    for more in POOL.map(lambda q: geocode_records(q, labels), other_spellings(p, query)):
        records += more
    kind, found = classify(p, records)
    if kind == "exact" or (kind and not p.unit):
        return answer(p, kind, found)
    if not p.suburb:
        return answer(p, kind, found) if kind else {"match": "none", "message": NO_MATCH_MESSAGE, "candidates": []}

    # 3. Check the suburb's complete property list, which the geocoder's 10 results can't show.
    suburb_name = dict(zip((clean_key(s) for s in labels), suburb_names()))[p.suburb_key]
    on_street = street_records(p, suburb_name, labels)
    records += on_street
    while True:
        kind, found = classify(p, records)
        if kind != "exact" or is_live(found[0]):
            break
        successor = reissued_unit(found[0], records)
        if successor:
            return answer(p, "exact", [successor],
                          f"Listed as {p.unit}. The address data now calls it {successor.addr.unit}.")
        records = [r for r in records if r.gnaf_id != found[0].gnaf_id]
    if kind == "exact":
        return answer(p, kind, found)
    found = live_only(p, found)
    if found:
        return answer(p, "pick", found)

    # 4. Nothing at this number. It may sit inside a range, or we can offer its neighbours on the street.
    if on_street:
        kind, found = classify(p, records_covering(p, on_street, labels))
        if kind:
            return answer(p, "pick", found)
        found = live_only(p, nearest_on_street(p, on_street))
        if found:
            return answer(p, "pick", found, f"We can't find number {p.number} on {full_street(p.street)}. Is it one of these?")
    return {"match": "none", "address": pretty(p), "message": NO_MATCH_MESSAGE, "candidates": []}


# --------------------------------------------------------------------------
# GET /lookup, steps 2 to 8: the facts for one home
# --------------------------------------------------------------------------

REPORT_CALLS = {
    "basics/all": {},
    "profile": {},
    "valuation/all": {},
    "history/all": {},
    "risks/all": {},
    "schools/all": {},
    "transport/nearby": {"radius_m": 5000},  # wide, so there's a nearest station
    "amenities/nearby": {"radius_m": 2000},
    "street/profile": {},
}

FLAGS = {
    "flood": "Flood",
    "historical_flood": "Past flooding",
    "heritage": "Heritage",
    "hv_power_line": "High-voltage power lines",
    "public_housing": "Public housing (estimated)",
}


def or_no_data(value):
    return NO_DATA if value in (None, "") else value


def last_sold(history: dict) -> dict | None:
    """The latest real sale. 'For Sale' rows also carry prices, but those are asking prices."""
    sold = [s for s in history.get("sale_history") or []
            if (s.get("type") or "").lower() == "sold" and (s.get("price") or 0) >= 50_000 and s.get("date")]
    return max(sold, key=lambda s: s["date"], default=None)


def update_to_today(sale: dict, series: list[dict] | None) -> dict | None:
    """The clever step: the home's own last sale, moved by how much its suburb's median has moved since.

    updated value = sale price x (latest median / median nearest the sale date)
    """
    points = [(date.fromisoformat(p["date"][:10]), p["value"]) for p in series or [] if p.get("value") and p.get("date")]
    if len(points) < 2:
        return None
    sold_on = date.fromisoformat(sale["date"][:10])
    then = min(points, key=lambda p: abs((p[0] - sold_on).days))
    if abs((then[0] - sold_on).days) > 370:
        return None  # the series doesn't reach back to this sale, so there's nothing honest to say
    latest = max(points, key=lambda p: p[0])
    return {
        "updated_value": round(sale["price"] * latest[1] / then[1] / 1000) * 1000,
        "change_pct": round((latest[1] / then[1] - 1) * 100, 1),
        "updated_as_of": latest[0].isoformat(),
    }


def nearby_sales(rows: list[dict] | None, gnaf_id: str, bedrooms, kind: str) -> list[dict]:
    """The 3 nearest recent sales: same bedrooms when known, and the same kind of home where possible."""
    others = [s for s in rows or [] if s.get("price") and s.get("date_sold") and s.get("gnaf_pid") != gnaf_id]
    same_beds = [s for s in others if s.get("bedrooms") == bedrooms] if isinstance(bedrooms, int) else others
    same_kind = [s for s in same_beds if (s.get("property_type") or "").lower() == kind]
    nearest = sorted(same_beds, key=lambda s: s.get("dist_km") or 99)
    picked = sorted(same_kind, key=lambda s: s.get("dist_km") or 99)
    picked = picked + [s for s in nearest if s not in picked]
    # One sale can appear under two spellings of its address (59/758 and 59/758-768 Bourke St).
    picked = list({(s["price"], s["date_sold"], s.get("dist_km")): s for s in reversed(picked)}.values())[::-1][:3]
    return [{
        "address": pretty(parse_address(s.get("address") or "")),
        "bedrooms": or_no_data(s.get("bedrooms")),
        "price": s["price"],
        "date_sold": s["date_sold"][:10],
        "distance_m": round((s.get("dist_km") or 0) * 1000),
    } for s in picked]


def price_block(r: dict, comparables: list[dict] | None, series: dict | None, gnaf_id: str, kind: str,
                bedrooms, building: bool) -> dict:
    avm = (r["valuation/all"]["data"] or {}).get("avm") or {}
    valuation = NO_DATA
    if avm.get("predicted_price") and not building:
        valuation = {
            "value": avm["predicted_price"],
            "low": or_no_data(avm.get("predicted_price_low")),
            "high": or_no_data(avm.get("predicted_price_high")),
            "date": or_no_data(avm.get("prediction_date")),
            "confidence": or_no_data(avm.get("confidence_score")),
        }
    out = {"status": "no_data", "sale_price": NO_DATA, "sale_date": NO_DATA, "change_pct": NO_DATA,
           "updated_value": NO_DATA, "updated_as_of": NO_DATA, "rough": False, "basis": kind,
           "valuation": valuation, "nearby_sales": []}

    history = r["history/all"]["data"]
    if building:
        # A sale on a whole-building record can be the whole building ($14.8M at 23-47 Flinders St).
        out["status"] = "building"
        out["nearby_sales"] = nearby_sales(comparables, gnaf_id, None, kind)
        return out
    if history is None:
        return out
    sale = last_sold(history)
    if not sale:
        out["status"] = "never_sold"
        out["nearby_sales"] = nearby_sales(comparables, gnaf_id, bedrooms, kind)
        return out
    sold_on = date.fromisoformat(sale["date"][:10])
    out.update(status="sold", sale_price=sale["price"], sale_date=sale["date"][:10],
               rough=(date.today() - sold_on).days > 3652)
    updated = update_to_today(sale, (series or {}).get(kind))
    if updated:
        out.update(updated)
    return out


def place(name, distance_m, **extra) -> dict:
    minutes = math.ceil(distance_m / 80)
    return {"name": tidy(name), "distance_m": round(distance_m), "walk_min": minutes, "walk": f"about {minutes} min walk", **extra}


def school_kinds(s: dict) -> set[str]:
    """Which of primary and high a school teaches. Most are labelled 'Combined', so read the name too."""
    name = (s.get("name") or "").lower()
    level = s.get("school_level_type")
    if "distance education" in name or "hospital" in name:
        return set()
    kinds = set()
    if level == "Primary" or any(w in name for w in ("primary", "public school", "infants")):
        kinds.add("primary")
    if level == "Secondary" or any(w in name for w in ("high school", "secondary")):
        kinds.add("high")
    if "community school" in name or "central school" in name:
        kinds |= {"primary", "high"}
    if "college" in name and not kinds:
        kinds.add("college")  # could be any age group, so only a fallback for a high school
    return kinds


def nearest_school(schools: list[dict], kind: str):
    matching = [s for s in schools if kind in school_kinds(s) and s.get("distance_m") is not None]
    if not matching and kind == "high":
        matching = [s for s in schools if "college" in school_kinds(s) and s.get("distance_m") is not None]
    if not matching:
        return NO_DATA
    # The nearest with NAPLAN results, if any: that skips small special-purpose colleges with nothing to compare.
    s = min([s for s in matching if s.get("naplan_label")] or matching, key=lambda s: s["distance_m"])
    return place(s["name"], s["distance_m"], naplan=or_no_data(s.get("naplan_label")), sector=or_no_data(s.get("sector")))


def daily_life(r: dict) -> dict:
    nearest = (r["transport/nearby"]["data"] or {}).get("nearest") or {}

    def stop(mode: str, unnamed: str):
        s = nearest.get(mode)
        return place(s.get("name") or unnamed, s["distance_m"]) if s and s.get("distance_m") is not None else NO_DATA

    amenities = (r["amenities/nearby"]["data"] or {}).get("results") or []

    def closest(category: str, fallback: str):
        rows = [a for a in amenities if a.get("category") == category and a.get("distance_m") is not None]
        if not rows:
            return NO_DATA
        a = min([a for a in rows if a.get("name")] or rows, key=lambda a: a["distance_m"])  # a named one if we can
        return place(a.get("name") or fallback, a["distance_m"])

    schools = r["schools/all"]["data"] or {}
    school_rows = schools.get("ranking") or schools.get("nearby") or []
    return {
        "train": stop("train", "Rail stop (no name in the data)"),
        "light_rail": stop("tram", "Light rail stop"),
        "bus": stop("bus", "Bus stop"),
        "supermarket": closest("Supermarket", "Supermarket"),
        "park": closest("Green Spaces", "Green space"),
        "primary_school": nearest_school(school_rows, "primary"),
        "high_school": nearest_school(school_rows, "high"),
    }


def flag_rows(layers: dict | None) -> list[dict]:
    """The same reading of the risk layers as summarise_risks(), worded for the panel."""
    rows = []
    for key, label in FLAGS.items():
        if layers is None:
            rows.append({"key": key, "label": label, "text": NO_DATA, "level": "unknown"})
            continue
        items = [i for i in layers.get(key) or [] if i.get("nearest_distance_m") is not None]
        on_property = [i for i in items if i.get("on_property")]
        nearest = min((i["nearest_distance_m"] for i in items), default=None)
        if key == "public_housing":
            # This layer is a share of homes in the small area around the address, not a fact about the home.
            if on_property:
                text = f"About {on_property[0].get('value')} of homes in this small area"
            else:
                text = f"Nearby, {nearest:.0f} m" if nearest is not None else "None within 1 km"
            rows.append({"key": key, "label": label, "text": text, "level": "info"})
        elif on_property:
            rows.append({"key": key, "label": label, "text": "On this property", "level": "high"})
        elif nearest is not None:
            rows.append({"key": key, "label": label, "text": f"Nearby, {nearest:.0f} m", "level": "medium" if nearest < 200 else "low"})
        else:
            rows.append({"key": key, "label": label, "text": "None within 1 km", "level": "ok"})
    return rows


def agent_questions(flags: list[dict], kind: str) -> list[str]:
    close = {f["key"] for f in flags if f["level"] in ("high", "medium")}
    questions = []
    if close & {"flood", "historical_flood"}:
        questions.append("Has the building ever flooded?" if kind == "unit" else "Has the home ever flooded?")
    if "heritage" in close:
        questions.append("Are there limits on renovating?")
    if "hv_power_line" in close:
        questions.append("How close are the power lines?")
    if not questions:
        questions.append("Are any special levies or big repairs planned?" if kind == "unit"
                         else "Has any major work been done, and was it approved?")
    return [*questions, "What are the strata levies?"]


def street_rank(data: dict | None):
    rank = (data or {}).get("forecast_rank") or {}
    if not rank.get("rank"):
        return NO_DATA
    profile = data.get("profile") or {}
    history = profile.get("history") or []
    return {
        "street": or_no_data(data.get("street")),
        "suburb": or_no_data(suburb_label(data.get("suburb") or "")),
        "rank": rank["rank"],
        "total": or_no_data(rank.get("total") or data.get("streets_in_suburb")),
        "band": or_no_data(rank.get("band")),
        "annual_4y": or_no_data(profile.get("annual_4y")),
        "suburb_annual_4y": or_no_data((data.get("suburb_medians") or {}).get("annual_4y")),
        "as_of": history[-1].get("year", NO_DATA) if history else NO_DATA,
    }


def home_kind(has_unit: bool, basics: dict) -> str:
    """'unit' or 'house', for choosing the price series. A unit number settles it, whatever the type says."""
    if has_unit:
        return "unit"
    if (basics.get("dwelling_type") or "").lower() in ("terrace", "duplex", "villa"):
        return "house"
    return property_kind(basics)


def build_report(gnaf_id: str, address: str, has_unit: bool, building: bool, site: str) -> dict | None:
    """All the panel's facts for one home. None if the API doesn't know this address ID."""
    futures = {ep: POOL.submit(call, client().property, gnaf_id, ep, **params) for ep, params in REPORT_CALLS.items()}
    r = {ep: f.result() for ep, f in futures.items()}
    if r["basics/all"].get("outside") or r["profile"].get("outside"):
        return None

    basics = r["basics/all"]["data"] or {}
    suburb = (r["profile"]["data"] or {}).get("suburb")
    kind = home_kind(has_unit, basics)
    bedrooms = basics.get("bed_count") or None

    needs_comparables = building or not last_sold(r["history/all"]["data"] or {})
    series_future = POOL.submit(call, client().suburb, suburb, "market/median-sale-price-series") if suburb else None
    comparables = call(client().property, gnaf_id, "comparables/recent-sales-nearby")["data"] if needs_comparables else None
    series = series_future.result()["data"] if series_future else None

    flags = flag_rows(r["risks/all"]["data"])
    today = datetime.now(timezone(timedelta(hours=11))).date()  # Sydney, close enough for a "checked on" date
    return {
        "gnaf_id": gnaf_id,
        "address": address,
        "building_level": building,
        "home": {
            "kind": kind,
            "bedrooms": or_no_data(bedrooms),
            "bathrooms": or_no_data(basics.get("bath_count") or None),
            "parking": or_no_data(basics.get("parking_count") or None),
        },
        "price": price_block(r, comparables, series, gnaf_id, kind, bedrooms, building),
        "daily_life": daily_life(r),
        "flags": flags,
        "street": street_rank(r["street/profile"]["data"]),
        "ask_agent": agent_questions(flags, kind),
        "checked_on": today.isoformat(),
        "full_report_url": site + report_url(gnaf_id, address),
    }


@app.get("/lookup")
def lookup(request: Request, address: str = "", gnaf_id: str = "", level: str = ""):
    """Match an address (or take an ID the user picked) and return what the panel shows."""
    started = time.monotonic()
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    site = f"{scheme}://{request.headers.get('host') or request.url.netloc}"
    try:
        if gnaf_id:
            parsed = parse_address(address, suburb_labels())
            result = {"match": "picked", "has_unit": bool(parsed.unit)}
            home = {"gnaf_id": gnaf_id, "address": address or gnaf_id, "has_unit": bool(parsed.unit)}
        else:
            result = match_address(address)
            home = result if result["match"] == "exact" else None
        if home:
            report = build_report(home["gnaf_id"], home["address"], home["has_unit"], level == "building", site)
            if report is None:
                result = {"match": "none", "message": NO_MATCH_MESSAGE, "candidates": []}
            else:
                result.update(report)
    except Exception as e:  # the panel gets a friendly message, never a crash
        print(f"lookup failed: {type(e).__name__}: {e}")
        result = {"match": "none", "message": TRY_AGAIN_MESSAGE, "candidates": []}
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result
