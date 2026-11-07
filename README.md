# Microburbs Facts for Property Listings

A Chrome extension that shows Microburbs facts beside the listing a buyer is viewing on realestate.com.au and domain.com.au.

Built by **Noir & Co Enterprises** for Task 3 of the Microburbs hackathon in Sydney, 7 November 2026.

- **Report:** [report.html](report.html)
- **Videos:** [pitch.mp4](pitch.mp4) and [demo.mp4](demo.mp4)
- **Separate check:** 8 of 10 untested listings matched correctly, with no wrong homes

## What it is

Open a listing in the City of Sydney and a panel appears on the right. It finds the exact home, with the unit number where there is one, and then shows:

1. **The matched address**, with "✓ Exact flat", or a list to pick from when it isn't sure
2. **Price:** "Last sold $X (Mon YYYY) → about $Y today", plus Microburbs' valuation and range when one exists
3. **Daily life:** rail, the nearest public primary and high schools with their NAPLAN labels, then bus, supermarket and park, in walking minutes
4. **Things to check before you buy:** flood, heritage and power lines, plus an estimate of nearby public housing
5. **This street:** its rank on 4-year forecast growth, when there's data
6. **Ask the agent:** questions based on what was found, and strata levies for flats
7. **A link to the full report**, and "Data: Microburbs"

If a listing hides its address or unit, the panel asks the user to pick or type it. Outside the City of Sydney, it shows a friendly message. It would rather ask than show facts for the wrong home.

## Who it helps

Home buyers comparing listings. A listing is written to sell the home, so the panel adds facts it may leave out, for that exact home, without opening another site.

It also suits an existing property-search extension that wants Microburbs data and branding in front of buyers.

## Our clever step

Microburbs' valuation exists for only about 13% of City of Sydney flats. In Microburbs' own test on 227 flat sales, a flat's last sale updated for price changes since came within 10% of the real price **109** times, against **34** for their valuation.

So the panel takes the home's own last sale and moves it by how much its suburb's median has moved since:

```
updated value = sale price x (latest suburb median / suburb median nearest the sale date)
```

It uses the unit median for flats and the house median for houses. For houses, and for sales over 10 years old, the valuation goes first when one exists. A house only shows the updated price when it falls inside Microburbs' valuation range; otherwise it shows just the last sale.

## Data used

The Microburbs Hackathon API is the only data source. Caches are in memory only, and no API responses are saved in this repo.

| What the panel needs | Where it comes from |
|---|---|
| Finding the home | `/v1/geocode/address`, `/v1/suburbs/list`, `/v1/suburbs/{name}/properties` |
| Beds, baths, parking, type | `/v1/properties/{id}/basics/all`, `/profile` |
| Price | `/history/all`, `/valuation/all`, `/comparables/recent-sales-nearby`, `/v1/suburbs/{name}/market/median-sale-price-series` |
| Daily life | `/transport/nearby`, `/schools/all`, `/amenities/nearby`, `/v1/suburbs/{name}/lifestyle/pois` |
| Things to check | `/risks/all` |
| This street | `/street/profile` |

## Install and run

### 1. The server

It's already live at https://noir-microburbs.vercel.app, and the extension uses it by default, so you can **skip to step 2**.

To run your own, you need Python 3.10 or newer and a Microburbs API key:

```bash
cd server
```

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Put your key in `server/.env` as `MICROBURBS_API_KEY`, then start the server:

```bash
.venv/bin/uvicorn main:app --port 8000
```

To check it, open http://localhost:8000/lookup?address=26%20Tudor%20Street,%20Surry%20Hills

To point the extension at your server, change `SERVER_URL` in `extension/background.js` and `host_permissions` in `extension/manifest.json`.

### 2. The extension

1. In Chrome, go to `chrome://extensions`.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked**.
4. Choose the `extension` folder.
5. Open a City of Sydney listing on realestate.com.au or domain.com.au.

## Checking the matching

```bash
server/.venv/bin/python tools/check_matches.py tools/dev_addresses.txt https://noir-microburbs.vercel.app
```

`tools/flag_rates.py` measures how common each flag is across 200 random homes. It needs a key in `server/.env`.

## What's in this repo

| Path | What it is |
|---|---|
| `extension/` | The Chrome extension. It reads only the address from the page and sends only that to the server |
| `server/` | The FastAPI server, with `/lookup` in `main.py` and address matching in `address.py` |
| `tools/` | The match check, the flag sample, and the development and holdout addresses |
| `report.html` | What we found, how we checked it, and what remains uncertain |

## Credits

- Data © Microburbs
- Addresses from Open G-NAF, © Geoscape Australia
- Server based on [microburbs-hackathon-demos](https://github.com/Microburbs/microburbs-hackathon-demos) (MIT licence; see `server/LICENSE`)
