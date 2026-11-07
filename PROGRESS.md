# Progress

## Done
- [x] 1. `.gitignore` committed first; tools checked (Python, Node, git and ffmpeg are installed; Vercel runs through `npx vercel`)
- [x] 2. `/server` set up from the demo; the key is in `server/.env` only; the API responds
- [x] 3. `/lookup` matching and price
- [x] 4. Daily life, flags, street rank, ask the agent, full report link
- [x] 5. `tools/dev_addresses.txt` and `tools/check_matches.py`: 10 of 10 behave as expected

- [x] 6. Live at https://noir-microburbs.vercel.app (10 of 10 there too); the key is a Vercel secret
- [x] 7. Chrome extension built in `/extension`; tested on a local copy of a listing page

## Next
- [ ] 8. Load it in Chrome and fix problems reported from real listings
- [ ] Docs, videos, final check and push (when you say the word for each)

## Things the data taught us
- The geocoder returns at most 10 results, so the suburb property list is used to see a whole building or street.
- The suburb property list still holds retired address IDs (403). `534D/810 Elizabeth St` was re-issued as `534/810`.
- `214/219-231 Botany Rd`: the building is in the data, but unit 214 isn't, so it asks the user to pick.
- `23-47 Flinders St`: its only record is the whole building, and its $14.8M sale isn't a flat's price, so no price is shown.
- Record types are unreliable (flats marked "house"), so matching relies on the address, not the type.
- `/amenities/nearby` returns only the 80 nearest places of any kind (all within about 370 m at 2 Sam Sing St, where its own count shows 46 supermarkets within 2 km). Supermarkets and parks therefore also come from the suburb's full place list (`/lifestyle/pois`).
- `school_level_type` says "Combined" for many primaries, so school type is also read from the name.

## How common each flag is (for the report)
200 random homes from the API's list of about 206,750 home addresses across the 29 suburbs. Seed 20261107, run with `tools/flag_rates.py`. 27 retired address IDs were skipped and replaced. No API responses were saved.

| Flag | On the property | Within 200 m (includes on the property) |
|---|---|---|
| Flood | 1.0% | 3.5% |
| Past flooding | 0.0% | 0.0% |
| Heritage | 38.5% | 99.5% |
| High-voltage power lines | 0.0% | 42.5% |
| Public housing (estimated) | 12.0% | 56.0% |
| Flood, heritage or power lines | 39.5% | 99.5% |

- Because heritage is within 200 m of 99.5% of homes, the panel now shows it only when it's on the property. That takes the all-clear line from 0.5% of homes to 30.0% of this sample. Flood and power lines still count within 200 m.
- With 200 homes, each percentage could be off by up to about 7 points.
- Two earlier runs used a shuffle, which changed with the list (the list size varied by 1 or 2 between runs). They gave similar results: heritage on the property 35–36.5% and within 200 m 99%, power lines within 200 m 46–47%, public housing within 200 m 59–61.5%.
- This run ranks homes by a hash of the seed and address ID, so a small change in the list can't reshuffle the sample. It hasn't been run a second time to confirm it repeats exactly.

## Metro check (for the report)
- Waterloo, Barangaroo and Gadigal Metro stations are not in the transport data. From an address beside each one, the nearest "train" was Green Square at 856 m, a light rail point at 449 m, and Town Hall at 137 m.
- Martin Place and Central appear only as their existing stations. Waterloo's place list has no "metro" entry at all.
- The `train` list also holds light rail (for example "CBD and South East Light Rail Station"), and `tram` was empty at every address checked. Some rail stops have no name, and one is named after a tunnel.
- So the panel's row reads "Rail", with the grey note "New Metro stations (e.g. Waterloo) aren't in the data yet".

## For "What remains uncertain" in the report
- New Metro stations aren't in the data, and light rail is mixed in with trains (see above).
- Walking times are straight lines, so they can cross water (Pyrmont to Balmain, Dawes Point to Crows Nest).
- Public housing is an estimate for the small area around a home, not a fact about the home.
- Price changes are at suburb level, not for one building.
- Valuations are missing for most flats.
- Selective schools are a fixed list in our code: the four requested, plus North Sydney Boys and Girls, which also appear in the data.
