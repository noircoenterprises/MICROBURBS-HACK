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
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from microburbs import ApiError, Microburbs, OutsideAreaError

load_dotenv()  # local development: read MICROBURBS_API_KEY from .env (on Vercel, set it in the dashboard)

HERE = Path(__file__).parent
app = FastAPI(title="Property Report", docs_url=None, redoc_url=None)
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
