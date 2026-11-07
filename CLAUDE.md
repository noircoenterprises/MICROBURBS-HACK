# Microburbs Hackathon: build instructions for Claude Code

You are a senior full-stack engineer helping a beginner win the Microburbs hackathon today. Build everything end to end inside this repo and keep me informed in plain words. When I say "start", begin at build step 1. I will give you our team API key in the chat.

<context>
- Event: Microburbs hackathon, Sydney, Saturday 7 November 2026. Team "Noir & Co Enterprises", entered in Task 3: Chrome extension.
- Task: "Show Microburbs facts beside the listing a buyer is viewing on a property site" (realestate.com.au and domain.com.au). The founder of a property-search extension with about 52-54k downloads wants Microburbs data and branding in front of buyers.
- How judges decide: they install our extension, open several real listings, check each matched address and check the displayed facts against the correct home. They also judge whether the facts add value for buyers. First prize is chosen from task results, pitches and demos. Their advice: "A clever, non-obvious step beats polish."
- Our clever step: Microburbs' valuation exists for only about 13% of City of Sydney flats. In Microburbs' own test on 227 flat sales, a flat's last sale updated for price changes since came within 10% of the real price 109 times, versus 34 for their valuation. So we show the last sale updated to today's prices, plus their valuation when it exists.
- Timing (Sydney time): server live as soon as possible, feature freeze at 1:30 pm, docs by 2:15 pm, videos by 2:50 pm, push by 2:55 pm. Uploads close at 3:00 pm.
- I'm a beginner on a Mac with Chrome. I can click, copy and paste, but I can't debug code.
- This repo: https://github.com/noircoenterprises/MICROBURBS-HACK (private until the final check).
</context>

<success_criteria>
1. On a real City of Sydney listing on realestate.com.au or domain.com.au, the panel appears within about 3 seconds and shows the exact home, unit included, with "✓ Exact flat".
2. It never shows facts for the wrong home. When unsure, it asks the user to pick.
3. Every fact shown is correct for that home and carries its date. Missing data reads "No data", never an error.
4. It handles flats with unit numbers (including letter units like D534 or 18E), houses, listings that hide the address or unit (a box to type it), and addresses outside the City (a friendly message).
5. The repo is safe to make public: no key, no supplied CSV files, no saved API responses. README.md, report.html, pitch.mp4 and demo.mp4 are at the top level.
</success_criteria>

<rules>
- Keep the API key secret, because the repo will be public and the judges and the public will see it. Store it only in server/.env and in Vercel's environment variables, read it from MICROBURBS_API_KEY, and never print it in any output, because I will be screen-recording. Never write it into this file or any other tracked file.
- Read only the property address from listing pages, or let the user type it, because the task forbids collecting or copying listing text or photos. Send only the address to our server.
- Use the Microburbs API as the only data source. The two supplied CSV files aren't needed, so keep them out of the project folder.
- Keep caches in memory only. Never write API responses into the repo, because the competition rules forbid it.
- Write a general solution. Don't hardcode fixes for particular addresses or test cases. If something can't be done, tell me.
- Before writing code that uses an endpoint, open the demo code and the API spec to confirm the field names instead of guessing.
- Commit locally at each checkpoint. Ask me before pushing to GitHub or doing anything hard to undo.
</rules>

<resources>
- Official demo repo (MIT licence): https://github.com/Microburbs/microburbs-hackathon-demos. Use its fastapi-property-report folder as our server base. Its microburbs.py already handles auth, the {"data": ...} envelope (data can be null, with a "message"), 403 (OutsideAreaError) and a one-hour in-memory cache. Its main.py has a thread pool (at most 8 calls in flight; the API limit is about 10 requests a second; on 429 wait and retry), summarise_risks(), property_kind(), and a vercel.json pinned to Sydney (syd1).
- API base: https://api-ht.microburbs.com.au with header "Authorization: Bearer <key>". Spec: https://api-ht.microburbs.com.au/openapi.json. Docs: https://api-ht.microburbs.com.au/docs. GET /v1/me shows our team.
- Coverage: the City of Sydney's 29 suburbs. Get the exact names from GET /v1/suburbs/list (for example "Glebe (NSW)"). A 403 means outside the area, or a retired address ID.
- Known response shapes (confirm them in the spec):
  - /v1/geocode/address?address= returns up to 10 candidates nationwide, each with id, display_name and property_type. The geocoder matches "1001/2 Sam Sing Street, Waterloo" much better than "Unit 1001, 2 Sam Sing Street".
  - /v1/properties/{id}/history/all: sale_history (date, price, type), sale_history_latest, rent_history_latest
  - /valuation/all: avm with predicted_price, predicted_price_low, predicted_price_high, prediction_date and confidence_score (often null for flats)
  - /risks/all: layers flood, historical_flood, heritage, hv_power_line, public_housing and others, each with on_property and nearest_distance_m
  - /transport/nearby: nearest per mode (train, tram, bus, ferry) with label or name and distance_m
  - /amenities/nearby: results with category, name and distance_m
  - /schools/all: ranking and nearby, with name, distance_m, school_level_type, sector and naplan_label
  - /comparables/recent-sales-nearby: address, bedrooms, price, date_sold, dist_km
  - /street/profile: the street compared with its suburb, including its rank on 4-year forecast growth (no data for some streets)
  - /v1/suburbs/{name}/market/median-sale-price-series: house and unit lists of {date, value}
- Homer, an existing extension, for the comparison in the report: https://chromewebstore.google.com/detail/hlmlbjneliokncgbophonbofnikfimja
- Microburbs' example report, whose format report.html should copy: https://www.microburbs.com.au/p/hackathon-example-rent-report
</resources>

<server_spec>
Copy fastapi-property-report into /server. Keep its LICENSE notice and leave DEMO_GATE off. Add CORS for the extension, and add:

GET /lookup?address=... (or ?gnaf_id=... when the user picks from a list)
1. Match: tidy the address and rewrite units to the slash form, e.g. "Unit 1001, 2 Sam Sing St, Waterloo NSW 2017" becomes "1001/2 Sam Sing Street, Waterloo". Handle letter units (D534, C1109, 18E, 901B) and number ranges (219-231). Call geocode. Accept a candidate only if unit, street number, street name and suburb all match: match="exact". If only the building matches (for example the listing shows no unit): match="pick", with up to 5 candidates. If the suburb is not one of the 29: match="outside". No candidate: match="none".
2. For the gnaf_id, fetch at the same time: basics/all, profile, valuation/all, history/all, risks/all, schools/all, transport/nearby, amenities/nearby and street/profile; comparables/recent-sales-nearby only when needed; and the suburb's median-sale-price-series, cached per suburb.
3. Price: take the latest sale with type "Sold" and a price. updated_value = price x (latest median / median nearest the sale date), using the "unit" series for flats and "house" for houses (see property_kind). Return sale_price, sale_date, change_pct and updated_value, and mark sales older than 10 years as "rough". Add the valuation and its range when present. If the home has never sold, return the 3 nearest same-bedroom recent sales.
4. Daily life: the nearest train or metro, light rail (tram) and bus; the nearest supermarket and park (green space); the nearest primary and high school with its NAPLAN label. Walking minutes = ceil(distance_m / 80), shown as "about N min walk".
5. Flags, reusing summarise_risks: flood, historical_flood, heritage, hv_power_line and public_housing, each shown as "On this property", "Nearby, X m" or "None within 1 km". Label public housing "estimated" and keep its wording neutral.
6. Street rank from street/profile when it's available.
7. Ask the agent: 2-3 questions based on the flags (heritage: "Are there limits on renovating?"; flood: "Has the building ever flooded?"; power lines: "How close are the power lines?"), plus always "What are the strata levies?".
8. A date with every number, "No data" for nulls, and full_report_url = /property/{gnaf_id} on our server.
Aim to respond in under about 3 seconds, using parallel calls and cached repeat views.
</server_spec>

<extension_spec>
A Manifest V3 extension in /extension for realestate.com.au and domain.com.au listing pages.
- content.js: find the address from the page title, the main heading, or (on Domain) the URL slug. These sites change pages without full reloads, so watch for URL changes. If no address or unit is found, show a small box to type it.
- background.js: call SERVER_URL/lookup, with the live Vercel URL kept in one config constant. The final build never points at localhost.
- Panel: fixed on the right, collapsible, and inside a Shadow DOM so the site's CSS can't break it. Order:
  1. Matched address with "✓ Exact flat", or a "Pick your unit" list
  2. Price: "Last sold $X (Mon YYYY) → about $Y today", plus the valuation and range when present
  3. Daily life: station, light rail, bus, supermarket, park and schools, in walking minutes
  4. What the listing won't tell you: the flags
  5. Street rank
  6. Ask the agent
  7. A "Full report" link, then "Data: Microburbs" linking to microburbs.com.au
- Design: readable in 3 seconds, with a clear hierarchy and big numbers. Use a Microburbs-style blue accent, a distinctive font and small grey dates. Show a loading skeleton while it waits, and friendly messages for outside-the-area and no-data cases. It should not look like a generic template.
</extension_spec>

<dev_addresses>
Create tools/dev_addresses.txt with these lines, one per line. The address is before the "|" and the listing link is after it.
1001/2 Sam Sing Street, Waterloo NSW 2017 | https://www.domain.com.au/1001-2-sam-sing-street-waterloo-nsw-2017-2021186571
214/219-231 Botany Road, Waterloo NSW 2017 | https://www.domain.com.au/214-219-231-botany-road-waterloo-nsw-2017-2019756607
D534/810-822 Elizabeth Street, Waterloo NSW 2017 | https://www.domain.com.au/d534-810-822-elizabeth-street-waterloo-nsw-2017-2021265082
911 Bourke Street, Waterloo NSW 2017 | https://www.domain.com.au/911-bourke-street-waterloo-nsw-2017-2019635161
33 Griffin Street, Surry Hills NSW 2010 | https://www.domain.com.au/33-griffin-street-surry-hills-nsw-2010-2021223115
403/417-419 Bourke Street, Surry Hills NSW 2010 | https://www.domain.com.au/403-417-419-bourke-street-surry-hills-nsw-2010-2021223621
23-47 Flinders Street, Surry Hills NSW 2010 | https://www.domain.com.au/23-47-flinders-street-surry-hills-nsw-2010-2020408767
18E/4 Distillery Drive, Pyrmont NSW 2009 | https://www.domain.com.au/18e-4-distillery-drive-pyrmont-nsw-2009-2021231541
164 Baptist Street, Redfern NSW 2016 | https://www.domain.com.au/164-baptist-street-redfern-nsw-2016-2021267122
306/10 Jaques Avenue, Bondi Beach NSW 2026 | https://www.domain.com.au/306-10-jaques-avenue-bondi-beach-nsw-2026-2021226608
Expected behaviour: 911 Bourke Street shows no unit, so "pick". 23-47 Flinders Street hides the unit, so "pick" or the type box. Bondi Beach is outside the City, so "outside". All the others should be "exact".
</dev_addresses>

<build_order>
Work in small checkpoints. After each one: test it, commit locally, update PROGRESS.md (a checklist of what's done and what's next), and tell me in 2-3 plain sentences what works and anything I must click. If your context is compacted, re-read this file and PROGRESS.md and carry on.
1. Before anything else, create .gitignore with: .env, .env.*, !.env.example, *.csv, *.mov, __pycache__/, .venv/, *.pyc, node_modules/, .vercel/, .DS_Store. Commit it. Then check the tools (Python 3.10+, Node, git, the Vercel CLI, ffmpeg). If something is missing, give me the single simplest Mac step to install it.
2. Set up /server from the demo, put the key in server/.env, and confirm GET /v1/me works.
3. Build /lookup steps 1-3 (match and price). Test it on: "26 Tudor Street, Surry Hills"; "28/96-98 Elizabeth Bay Road, Elizabeth Bay"; "Unit 28, 96-98 Elizabeth Bay Road, Elizabeth Bay" (the same flat written differently); and "1 Campbell Parade, Bondi Beach" (outside). Show me a short table of the results.
4. Add steps 4-8 and test again.
5. Create tools/dev_addresses.txt (see dev_addresses) and add tools/check_matches.py, which runs /lookup on the addresses in a given file and prints a table of address, match type, expected result and timing. Run it on tools/dev_addresses.txt and fix the matching until it behaves as expected. Make each fix general.
6. Deploy to Vercel (I'll log in when you ask), set the environment variable, give me the live URL, and test /lookup there.
7. Build the extension, then tell me exactly how to load it: chrome://extensions, then Developer mode, then Load unpacked.
8. Fix the problems I report from real listings, including screenshots I drag in. Make each fix general, not specific to one address.
If time runs short, finish in this order of priority: match, price, flags, daily life, ask the agent, street rank. Check the current Sydney time at each checkpoint. At 1:30 pm, stop adding features and switch to fixing and writing.
</build_order>

<commands_for_later>
When I say "final score" and paste 10 holdout addresses: save them to tools/holdout_addresses.txt and run check_matches.py on them once, without changing any code first. Give me the score (correct out of 10, where "outside" or "pick" counts as correct when that's the right behaviour), and list 3 of them for me to check end to end in Chrome.

When I say "write the docs":
- README.md, at the top level: what it is, who it helps, the data used, our clever step, and how to install and run it (the server, then Load unpacked). Credits: "Data © Microburbs"; addresses from Open G-NAF, © Geoscape Australia; server based on microburbs-hackathon-demos (MIT licence).
- report.html, self-contained, at the top level, in the format of Microburbs' example report: findings first, short sections, headings as questions, key numbers big and bold, plain words, and one simple flow diagram. Sections:
  1. Title: our main finding as a question, answered in the first line
  2. What we found along the way, including a table of what realestate.com.au, Domain, Homer and our panel each show (ask me what the listing pages show if you can't load them)
  3. What our separate check showed: the holdout score
  4. What data supported the result?
  5. How did we build it?
  6. How did we check it?
  7. What remains uncertain? (straight-line walking times, estimated public housing, suburb-level price changes, valuation coverage)
  Include no raw API responses.

When I say "make the demo video" and give you my screen recording (.mov): turn it into demo.mp4 at the top level (H.264, 3 minutes max, under 95 MB). Add a 3-second title card; a 15-second card showing which Microburbs data feeds each part of the panel; short captions at the key moments; and an end card with "Data: Microburbs" and our holdout score. Keep all the real footage visible, because the judges want to see it working on real listings.

When I say "make the pitch video": make pitch.mp4 at the top level (1920x1080, 45 seconds max, under 95 MB) as a motion-graphics video, using the simplest method that works here (for example HTML/CSS animations recorded to video, then ffmpeg). Put every line on screen as large text, and include a 5-10 second clip from my recording. Script:
  0-5 s: "Every Sydney listing hides things. Our Chrome extension shows them."
  5-15 s: the real clip: a listing opens, the panel appears, "✓ Exact flat"
  15-30 s: "True price: the last sale updated to today, the method that beat Microburbs' own valuation in their test." / "Daily life, in walking minutes." / "What the listing won't tell you."
  30-40 s: "Matched [SCORE] of 10 untested listings."
  40-45 s: "Built for buyers. Ready for an extension with 52,000 downloads. Data: Microburbs." / "Noir & Co Enterprises"
Never show the key or any settings screen in either video.

When I say "final check and push": confirm there's no key anywhere in the files or the git history, no .env, no CSV files and no saved API output; the extension points at the live URL; and README.md, report.html, pitch.mp4 and demo.mp4 are at the top level and each video is under 95 MB. Then, after asking me, push to https://github.com/noircoenterprises/MICROBURBS-HACK and remind me to switch the repo to Public (Settings, then Change visibility) before I submit.
</commands_for_later>

<working_style>
- Act by default. Implement rather than suggest. Find things out with your tools instead of asking me, and only ask when you need a login, a click, or a decision only I can make.
- Keep it simple. Build only what's listed here, with no extra frameworks, abstractions or files.
- Talk to me like a beginner: short plain sentences, and numbered steps for anything I must do.
- Delete any temporary scratch files when you're done.
</working_style>
