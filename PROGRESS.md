# Progress

## Done
- [x] 1. `.gitignore` committed first; tools checked (Python, Node, git and ffmpeg are installed; Vercel runs through `npx vercel`)
- [x] 2. `/server` set up from the demo; the key is in `server/.env` only; the API responds
- [x] 3. `/lookup` matching and price
- [x] 4. Daily life, flags, street rank, ask the agent, full report link
- [x] 5. `tools/dev_addresses.txt` and `tools/check_matches.py`: 10 of 10 behave as expected

## Next
- [ ] 6. Deploy to Vercel and test `/lookup` there
- [ ] 7. Build the Chrome extension
- [ ] 8. Fix problems reported from real listings

## Things the data taught us
- The geocoder returns at most 10 results, so the suburb property list is used to see a whole building or street.
- The suburb property list still holds retired address IDs (403). `534D/810 Elizabeth St` was re-issued as `534/810`.
- `214/219-231 Botany Rd`: the building is in the data, but unit 214 isn't, so it asks the user to pick.
- `23-47 Flinders St`: its only record is the whole building, and its $14.8M sale isn't a flat's price, so no price is shown.
- Record types are unreliable (flats marked "house"), so matching relies on the address, not the type.
- `tram` has been empty on every address tried so far, and some rail stops have no name.
