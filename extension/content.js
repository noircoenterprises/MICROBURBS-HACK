// Microburbs facts, shown beside a listing on realestate.com.au and domain.com.au.
//
// It reads only the property's address from the page (or what the user types) and sends only
// that to our server. It never collects any other listing text or photos.
(() => {
  "use strict";
  if (window.top !== window) return;

  // ---------------------------------------------------------------- finding the address

  const STREET_WORD = /\b(street|st|road|rd|avenue|ave|drive|dr|lane|ln|place|pl|parade|pde|circuit|cct|crescent|cres|court|ct|close|cl|terrace|tce|highway|hwy|boulevarde?|bvd|blvd|way|walk|square|sq|quay|esplanade|esp|grove|gr|row|mews|arcade|promenade|broadway)\b/i;
  const STARTS_LIKE_ADDRESS = /^(?:(?:unit|apartment|apt|flat|villa|studio|townhouse|penthouse|level|lvl)\s*[a-z0-9-]+\s*[,/]?\s*)*[a-z]{0,3}\d+[a-z]{0,2}(?:\s*[/-]\s*[a-z]{0,2}\d+[a-z]{0,2})*[,\s]/i;
  const NOT_AN_ADDRESS = /\b(bed|beds|bedroom|bedrooms|bath|baths|properties|homes|results|for sale in|for rent in)\b/i;

  function looksLikeAddress(text) {
    return STARTS_LIKE_ADDRESS.test(text) && !NOT_AN_ADDRESS.test(text) && (STREET_WORD.test(text) || /\bNSW\b/i.test(text));
  }

  // "1001/2 Sam Sing Street, Waterloo NSW 2017 | Domain" -> "1001/2 Sam Sing Street, Waterloo NSW 2017"
  function addressIn(text) {
    const parts = (text || "").replace(/\s+/g, " ").trim().split(/\s+[|–—-]\s+/);
    return parts.find(looksLikeAddress) || "";
  }

  // Domain's link holds the address too: /1001-2-sam-sing-street-waterloo-nsw-2017-2021186571
  function addressFromDomainLink() {
    if (location.hostname !== "www.domain.com.au") return "";
    const m = location.pathname.match(/^\/(?:property-profile\/)?([a-z0-9-]+?)-nsw-\d{4}(?:-\d{6,})?\/?$/);
    if (!m) return "";
    const parts = m[1].split("-");
    const numbers = [];
    while (parts.length && /\d/.test(parts[0])) numbers.push(parts.shift().toUpperCase());
    if (!numbers.length || !parts.length) return "";
    const words = parts.map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
    if (numbers.length === 1) return `${numbers[0]} ${words}`;
    if (numbers.length === 2) {
      const isRange = /^\d+$/.test(numbers[0]) && parseInt(numbers[1], 10) > parseInt(numbers[0], 10);
      return `${numbers[0]}${isRange ? "-" : "/"}${numbers[1]} ${words}`;
    }
    return `${numbers[0]}/${numbers[1]}-${numbers[2]} ${words}`;
  }

  function addressOnPage() {
    for (const h1 of document.querySelectorAll("h1")) {
      const found = addressIn(h1.textContent);
      if (found) return found;
    }
    return addressIn(document.title) || addressFromDomainLink();
  }

  function isListingLink() {
    const path = location.pathname.toLowerCase();
    if (location.hostname === "www.domain.com.au") {
      return /^\/[a-z0-9-]+-\d{7,}\/?$/.test(path) || /^\/property-profile\/[a-z0-9-]+\/?$/.test(path);
    }
    return /^\/(?:(?:sold|rent|buy)\/)?property-[a-z0-9+-]+-\d{5,}\/?$/.test(path) || /^\/property\/[a-z0-9-]+\/?$/.test(path);
  }

  // After moving between listings without a page load, the old heading can stay up for a moment.
  // Facts for the wrong home are the worst failure, so check the address belongs to this link.
  function addressFitsLink(address) {
    const path = location.pathname.toLowerCase();
    const realestate = path.match(/-(?:nsw|vic|qld|sa|wa|tas|act|nt)-([a-z+-]+?)-\d{5,}\/?$/);
    if (realestate && location.hostname !== "www.domain.com.au") {
      return address.toLowerCase().includes(realestate[1].replace(/[+-]/g, " "));
    }
    const m = address.toLowerCase().match(/(\d+[a-z]?)[\s,]+([a-z]+)/);
    return !m || (path.split(/[^a-z0-9]+/).includes(m[1]) && path.includes(m[2]));
  }

  // ---------------------------------------------------------------- small helpers

  const NO_DATA = "No data";
  const isNumber = (v) => typeof v === "number" && !Number.isNaN(v);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => "$" + Math.round(n).toLocaleString("en-AU");
  const shortMoney = (n) => (n >= 1e6 ? `$${(n / 1e6).toFixed(2)}M` : `$${Math.round(n / 1e3)}k`);
  const asDate = (iso) => new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const monthYear = (iso) => `${MONTHS[asDate(iso).getMonth()]} ${asDate(iso).getFullYear()}`;
  const fullDate = (iso) => `${asDate(iso).getDate()} ${monthYear(iso)}`;
  const metres = (m) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m`);

  const LOGO = `<svg viewBox="64 117 470 470" aria-hidden="true"><path d="M145 557C125.6 556.5 125.5 556.4 119 553.3C104.6 546.3 95.3 533.7 93 518.5C92.3 513.9 92 477.3 92.2 411C92.5 311.1 92.5 310.5 94.6 304.9C95.8 301.8 97.6 297.8 98.5 295.9C101.2 290.8 110.5 281.5 120.5 273.9C128.9 267.6 137.3 261.1 151.6 249.9C171.1 234.7 180 227.9 186.1 223.5C189.9 220.8 195.6 216.5 198.8 214C222.8 195.2 266.7 161.5 273.8 156.5C284.9 148.6 301.3 145.8 315.3 149.5C325.2 152.1 328.2 154.1 358.4 178C364.3 182.7 372.5 189.1 376.6 192.2C380.7 195.3 385.8 199.4 387.8 201.2C395.7 208.4 399.1 210.5 400.1 208.9C400.6 208.1 401 201 401 193C401 180.4 401.3 178.1 403 175.3C406.6 169.3 408.3 169 435.3 169C459.1 169 459.8 169.1 463.1 171.3C469.5 175.6 469.4 175 470 223.3L470.5 267.1L474.6 270.3C492.6 284.2 497.4 289.1 501.5 297.5C507.2 309.2 507.1 305.6 506.8 418.7L506.5 522.6L502.8 530.1C498 539.8 494.4 543.9 486.1 549.4C473.4 557.8 486.6 557.2 316 557.4C232.7 557.4 155.7 557.3 145 557Z" fill="#0065f6" fill-rule="evenodd"/><path d="M368.2 517.8C364.6 514 362.6 509.5 360.6 501.1C358.7 492.8 359.6 492.1 368.9 495.1C375.6 497.3 376.1 497.3 381.4 495.8C388.9 493.7 389.7 494.7 387.5 503.2C383.5 518.9 375.4 525.1 368.2 517.8ZM373 480.5C369.7 477 367.3 476.5 362.9 478.6C359.5 480.1 358.3 480.2 353.7 479.1C342.8 476.6 335 470.4 335 464.3C335 463.1 333.6 460.5 331.9 458.5C329.3 455.6 328.1 455 324.9 455L321 455L323.2 450.5C325.5 445.8 325.1 443.8 322.2 445.7C317.2 449.2 311.5 452 310.4 451.6C309.7 451.3 307.9 448.8 306.5 445.9C302.7 438.6 295.9 431.6 289.8 429C281.7 425.5 275 425.4 263.9 428.3C251.3 431.7 244.1 435 238.8 439.8C232.2 445.9 230.6 446.4 219 446.5C208.6 446.6 208.4 446.7 200.5 450.9C193.5 454.7 191.9 455.2 188 454.7C182.3 454 178.8 452.4 177.2 449.9C176.2 448.3 176.3 447.3 178 444C182 436.2 180.3 428.3 170.4 406.9C166.4 398.1 165.9 396.2 164.9 385.5C163.7 372.5 164.3 368.4 168.2 363.5C171.8 358.9 181.9 353.1 190.9 350.4C208.3 345.1 213.4 341.4 217.5 331.4C219.1 327.3 221 324.6 223.7 322.5C225.8 320.9 230.2 316.4 233.5 312.7C244.6 300.1 251.2 297.5 259.7 302.6C268.3 307.8 268.7 307.7 270.9 300.8C273.7 292.1 281.5 285 288.1 285C292.3 285 294.2 283.3 293.3 280.2C292.4 276.7 295.2 276.6 303.1 280C309.3 282.7 311.9 283.2 319 283.4C331.9 283.6 332.4 284.7 325.5 295.4C320.9 302.4 320 306.3 322.2 309.2C322.9 310.1 328.6 314 334.9 317.9C343.9 323.5 347.1 325 350.2 325C357.2 325 359.9 320.4 362.4 304C366 281 370.2 268.9 373 273C373.6 273.8 375.7 279.8 377.8 286.3C381.3 297.6 381.7 298.3 385.2 300.1C387.3 301.2 389.7 303.1 390.5 304.4C391.4 305.7 393.4 312.8 394.9 320.2C396.4 327.5 398.3 334.7 399.1 336.3C399.9 337.8 402.8 340.5 405.5 342.3C409.5 344.9 411.5 347.4 416.5 356.1C419.9 361.9 424.3 368.8 426.3 371.4C435.6 383.6 437.9 396.8 433.8 414C432.2 420.4 429.7 425.2 422.1 436C414.2 447.1 409.6 454.7 404.5 465C402.4 469.1 400 473 399.1 473.7C398.2 474.4 395 475.4 392 476.1C389 476.7 384.4 478.5 381.9 480.1C376.3 483.6 376 483.6 373 480.5Z" fill="#fff" fill-rule="evenodd" stroke="#fff" stroke-width="10" stroke-linejoin="round"/></svg>`;

  // ---------------------------------------------------------------- what the panel looks like

  const STYLES = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .wrap {
      --blue: #0065f6; --deep: #0047d8; --sky: #00b4fd; --navy: #0b2559; --ink: #1a2b4a; --grey: #6b7a90;
      --line: #e6ebf3; --soft: #f3f7fe; --red: #c8372d; --amber: #c27803; --green: #0b8f5a;
      --serif: "Iowan Old Style", "Palatino Linotype", Palatino, "Book Antiqua", Georgia, serif;
      --sans: "Avenir Next", Avenir, "Segoe UI Variable Text", "Segoe UI", -apple-system, system-ui, sans-serif;
      position: fixed; top: 84px; right: 16px; z-index: 2147483646;
      font: 400 13.5px/1.4 var(--sans); color: var(--ink); -webkit-font-smoothing: antialiased;
    }
    .panel {
      width: 360px; max-height: calc(100vh - 104px); display: flex; flex-direction: column; overflow: hidden;
      background: #fff; border-radius: 16px; box-shadow: 0 18px 50px rgba(8, 30, 80, .24), 0 2px 6px rgba(8, 30, 80, .12);
    }
    .top {
      display: flex; align-items: center; gap: 8px; flex: none; padding: 9px 8px 9px 14px; color: #fff;
      background: linear-gradient(100deg, var(--deep) 0%, var(--blue) 62%, var(--sky) 130%);
    }
    .badge { display: grid; place-items: center; width: 24px; height: 24px; flex: none; border-radius: 7px; background: #fff; }
    .badge svg { width: 18px; height: 18px; display: block; }
    .brand { font-weight: 700; font-size: 14.5px; letter-spacing: .1px; }
    .strap { font-size: 12px; opacity: .85; flex: 1; }
    button { font: inherit; color: inherit; cursor: pointer; border: 0; background: none; }
    .fold { width: 28px; height: 28px; border-radius: 8px; color: #fff; font-size: 18px; line-height: 1; }
    .fold:hover { background: rgba(255, 255, 255, .18); }
    .scroll { overflow-y: auto; overscroll-behavior: contain; }

    .pill {
      display: flex; align-items: center; gap: 7px; padding: 8px 13px 8px 10px; border-radius: 999px; color: #fff; font-weight: 700;
      background: linear-gradient(100deg, var(--deep), var(--blue)); box-shadow: 0 8px 24px rgba(8, 30, 80, .3);
    }
    

    .match { padding: 14px 16px 13px; }
    .addr { font: 600 20px/1.2 var(--serif); color: var(--navy); }
    .tags { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 9px; margin-top: 8px; }
    .chip { padding: 3px 9px; border-radius: 999px; background: #e3f6ee; color: var(--green); font-weight: 700; font-size: 12.5px; }
    .chip.plain { background: #e7f0ff; color: var(--deep); }
    .specs { color: var(--grey); font-size: 12.5px; }
    .note { margin-top: 7px; font-size: 12px; color: var(--grey); }
    .change { padding: 0; margin-top: 6px; display: block; font-size: 12px; color: var(--grey); text-decoration: underline; }

    .price { padding: 13px 16px 14px; background: linear-gradient(180deg, var(--soft), #fff); border-top: 1px solid var(--line); }
    .sold { font-size: 13.5px; }
    .sold b { font-weight: 700; }
    .today { margin: 3px 0 4px; font: 600 33px/1.1 var(--serif); color: var(--navy); letter-spacing: -.5px; font-variant-numeric: lining-nums; }
    .today small { font: 500 14px var(--sans); color: var(--grey); letter-spacing: 0; }
    .how, .date { font-size: 11.5px; color: var(--grey); }
    .rough { display: inline-block; margin-top: 6px; padding: 2px 8px; border-radius: 6px; background: #fff4e0; color: #8a5a00; font-size: 11.5px; font-weight: 600; }
    .value { display: grid; grid-template-columns: 1fr auto; gap: 0 10px; margin-top: 10px; padding-top: 9px; border-top: 1px dashed var(--line); }
    .value b { font: 600 17px/1.2 var(--serif); color: var(--navy); font-variant-numeric: lining-nums; text-align: right; }
    .nosale { font: 600 18px/1.25 var(--serif); color: var(--navy); }
    .sale { display: grid; grid-template-columns: 1fr auto; gap: 0 10px; padding: 6px 0; border-top: 1px dashed var(--line); }
    .sale:first-of-type { border-top: 0; }
    .sale strong { font: 600 15px/1.2 var(--serif); color: var(--navy); font-variant-numeric: lining-nums; text-align: right; }
    .similar { margin: 6px 0 3px; font-weight: 600; font-size: 13px; line-height: 1.3; color: var(--navy); }
    .eyebrow { font-weight: 600; font-size: 12.5px; }
    .then { margin-top: 10px; padding-top: 9px; border-top: 1px dashed var(--line); }
    .then .nosale { font-size: 15px; }

    .sec { padding: 12px 16px; border-top: 1px solid var(--line); }
    .head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 5px; }
    .title { font-weight: 700; font-size: 13.5px; color: var(--navy); }
    .row { display: grid; grid-template-columns: 74px 1fr auto; gap: 0 8px; align-items: baseline; padding: 3.5px 0; }
    .label { font-size: 11.5px; color: var(--grey); }
    .name { display: block; font-weight: 600; line-height: 1.25; }
    .nodata { color: var(--grey); font-weight: 400; }
    .walk { font-size: 11px; color: var(--grey); white-space: nowrap; text-align: right; }
    .walk b { font-size: 15px; color: var(--blue); font-weight: 700; }
    .naplan { display: block; font-size: 11.5px; color: var(--grey); }
    .selective { display: block; font-size: 11.5px; font-weight: 700; color: var(--deep); white-space: nowrap; }
    .metro { padding-bottom: 3px; font-size: 11px; color: var(--grey); }
    .quick { margin-top: 5px; padding-top: 7px; border-top: 1px dashed var(--line); font-size: 12.5px; }
    .quick b { color: var(--blue); font-weight: 700; }

    .flag { display: grid; grid-template-columns: 10px 1fr auto; gap: 0 8px; align-items: center; padding: 3.5px 0; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #c6d0de; }
    .dot.high { background: var(--red); } .dot.medium { background: var(--amber); }
    .flag .what { font-weight: 600; }
    .flag .said { font-size: 12.5px; color: var(--grey); text-align: right; }
    .flag .said.high { color: var(--red); font-weight: 700; } .flag .said.medium { color: var(--amber); font-weight: 600; }

    .clear { padding: 2px 0; font-weight: 600; color: var(--green); }
    .rank { font-size: 13.5px; }
    .rank b { font: 600 22px/1 var(--serif); color: var(--navy); font-variant-numeric: lining-nums; }

    ul { margin: 0; padding: 0; list-style: none; }
    li { position: relative; padding: 3px 0 3px 17px; }
    li::before { content: "?"; position: absolute; left: 0; top: 3px; color: var(--blue); font-weight: 800; }

    .foot { display: flex; justify-content: space-between; align-items: center; padding: 11px 16px; background: #f7f9fc; border-top: 1px solid var(--line); }
    .report { padding: 7px 13px; border-radius: 9px; background: var(--blue); color: #fff; font-weight: 700; text-decoration: none; }
    .report:hover { background: var(--deep); }
    .credit { font-size: 12px; color: var(--grey); text-decoration: none; }
    .credit:hover { text-decoration: underline; }

    .ask { padding: 14px 16px 15px; }
    .big { font: 600 19px/1.25 var(--serif); color: var(--navy); }
    .said-more { margin-top: 5px; font-size: 13px; color: var(--ink); }
    .picks { margin-top: 10px; display: grid; gap: 6px; }
    .picks button { display: block; width: 100%; padding: 8px 11px; text-align: left; border: 1px solid var(--line); border-radius: 10px; background: #fff; font-weight: 600; }
    .picks button:hover { border-color: var(--blue); background: var(--soft); }
    .picks small { display: block; font-weight: 400; font-size: 11.5px; color: var(--grey); }
    form { margin-top: 12px; }
    label { display: block; margin-bottom: 4px; font-size: 12px; font-weight: 600; color: var(--navy); }
    .line { display: flex; gap: 6px; }
    input { flex: 1; min-width: 0; padding: 8px 10px; font: inherit; color: var(--ink); background: #fff; border: 1px solid #cfd8e6; border-radius: 9px; outline: 0; }
    input:focus { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(0, 101, 246, .15); }
    .go { padding: 8px 12px; border-radius: 9px; background: var(--blue); color: #fff; font-weight: 700; }
    .go:hover { background: var(--deep); }

    .bone { background: linear-gradient(90deg, #edf1f7 25%, #f8fafc 37%, #edf1f7 63%); background-size: 400% 100%; border-radius: 6px; animation: shine 1.3s linear infinite; }
    @keyframes shine { from { background-position: 100% 0; } to { background-position: 0 0; } }
    @media (prefers-reduced-motion: reduce) { .bone { animation: none; } }
  `;

  // ---------------------------------------------------------------- what the panel says

  function matchHtml(data, level) {
    let chip;
    if (data.match === "exact") {
      chip = `<span class="chip">✓ Exact ${data.has_unit ? "flat" : "home"}</span>`;
    } else {
      chip = `<span class="chip plain">${level === "building" ? "Whole building" : "Your pick"}</span>`;
    }
    const home = data.home || {};
    const specs = [
      isNumber(home.bedrooms) && `${home.bedrooms} bed`,
      isNumber(home.bathrooms) && `${home.bathrooms} bath`,
      isNumber(home.parking) && `${home.parking} car`,
    ].filter(Boolean).join(" · ");
    return `<div class="match">
      <div class="addr">${esc(data.address)}</div>
      <div class="tags">${chip}${specs ? `<span class="specs">${specs}</span>` : ""}</div>
      ${data.note ? `<div class="note">${esc(data.note)}</div>` : ""}
      <button class="change" data-do="change">Not this home?</button>
    </div>`;
  }

  function valuationHtml(valuation) {
    if (!valuation || valuation === NO_DATA) {
      return `<div class="value"><span>Microburbs valuation</span><span class="nodata">${NO_DATA}</span></div>`;
    }
    const range = isNumber(valuation.low) && isNumber(valuation.high) ? `${shortMoney(valuation.low)} to ${shortMoney(valuation.high)}` : "";
    const when = valuation.date !== NO_DATA ? monthYear(valuation.date) : "";
    return `<div class="value">
      <span>Microburbs valuation</span><b>${money(valuation.value)}</b>
      <span class="date">${[range, when].filter(Boolean).join(" · ")}</span>
    </div>`;
  }

  function leadValuationHtml(valuation) {
    const range = isNumber(valuation.low) && isNumber(valuation.high) ? `${shortMoney(valuation.low)} to ${shortMoney(valuation.high)}` : "";
    const when = valuation.date !== NO_DATA ? monthYear(valuation.date) : "";
    return `<div class="eyebrow">Microburbs valuation</div>
      <div class="today">${money(valuation.value)}</div>
      <div class="how">${[range, when].filter(Boolean).join(" · ")}</div>`;
  }

  function salesHtml(price) {
    const sales = price.nearby_sales || [];
    if (!sales.length) return `<div class="similar nodata">Recent sales nearby: ${NO_DATA}</div>`;
    return `<div class="similar">${esc(price.similar_line)}</div>` + sales.map((s) => `<div class="sale">
        <span class="name">${esc(s.address)}</span><strong>${money(s.price)}</strong>
        <span class="date">${isNumber(s.bedrooms) ? `${s.bedrooms} bed · ` : ""}${metres(s.distance_m)} away</span>
        <span class="date">${monthYear(s.date_sold)}</span>
      </div>`).join("");
  }

  // "Last sold $X (Mon YYYY) → about $Y today", with $Y big when it's the lead and in the text when it isn't.
  function updatedHtml(price, isLead) {
    const sold = `Last sold <b>${money(price.sale_price)}</b> <span class="date">(${monthYear(price.sale_date)})</span>`;
    if (!isNumber(price.updated_value)) return `<div class="sold">${sold}</div><div class="how">Updated price: ${NO_DATA}</div>`;
    const kind = price.basis === "house" ? "House" : "Unit";
    const sign = price.change_pct > 0 ? "+" : "";
    const how = `<div class="how">${kind} prices in this suburb moved ${sign}${price.change_pct}% since that sale. Median as at ${monthYear(price.updated_as_of)}.</div>`;
    const rough = price.rough ? `<div class="rough">Rough guide: this sale is over 10 years old</div>` : "";
    return isLead
      ? `<div class="sold">${sold} →</div><div class="today"><small>about</small> ${money(price.updated_value)} <small>today</small></div>${how}${rough}`
      : `<div class="sold">${sold} → about <b>${money(price.updated_value)}</b> today</div>${how}${rough}`;
  }

  function priceHtml(price) {
    const valuation = price.valuation;
    const valuationLeads = price.lead === "valuation" && valuation && valuation !== NO_DATA;
    let body;
    if (price.status === "sold") {
      body = valuationLeads
        ? `${leadValuationHtml(valuation)}<div class="then">${updatedHtml(price, false)}</div>`
        : updatedHtml(price, true) + valuationHtml(valuation);
    } else if (price.status === "never_sold") {
      const noSale = `<div class="nosale">No sale on record</div>${salesHtml(price)}`;
      body = valuationLeads ? `${leadValuationHtml(valuation)}<div class="then">${noSale}</div>` : noSale + valuationHtml(valuation);
    } else if (price.status === "building") {
      body = `<div class="nosale">No price for one flat</div>
        <div class="how">This record covers the whole building, so any sale on it may not be for one home.</div>${salesHtml(price)}`;
    } else {
      body = `<div class="nosale">Price: ${NO_DATA}</div>${valuationHtml(valuation)}`;
    }
    return `<div class="price">${body}</div>`;
  }

  function placeHtml(label, place) {
    if (!place || typeof place === "string") {
      return `<div class="row"><span class="label">${label}</span><span class="name nodata">${esc(place || NO_DATA)}</span></div>`;
    }
    const selective = place.selective ? `<span class="selective">${esc(place.selective)}</span>` : "";
    const naplan = place.naplan ? `<span class="naplan">NAPLAN: ${esc(place.naplan)}</span>` : "";
    return `<div class="row">
      <span class="label">${label}</span>
      <span><span class="name">${esc(place.name)}</span>${selective}${naplan}</span>
      <span class="walk">about <b>${place.walk_min}</b> min walk</span>
    </div>`;
  }

  function quickItem(label, place) {
    if (!place || typeof place === "string") return `${esc(label)}: ${esc(place || NO_DATA)}`;
    return `${esc(label)} <b>${place.walk_min}</b> min`;
  }

  function dailyLifeHtml(life, checked) {
    const shop = life.supermarket;
    const park = life.park;
    const quick = [
      quickItem("Bus", life.bus),
      quickItem(shop && shop.name ? shop.name : "Grocery", shop),
      quickItem(park && park.short ? park.short : "Park", park),
    ].join(" · ");
    return `<div class="sec">
      <div class="head"><span class="title">Daily life</span><span class="date">Checked ${fullDate(checked)}</span></div>
      ${placeHtml("Rail", life.train)}
      <div class="metro">New Metro stations (e.g. Waterloo) aren't in the data yet</div>
      ${placeHtml("Primary", life.primary_school)}
      ${placeHtml("High school", life.high_school)}
      ${life.non_selective_high_school ? placeHtml("Non-selective", life.non_selective_high_school) : ""}
      <div class="quick" title="Estimated walking times">${quick}</div>
    </div>`;
  }

  function flagsHtml(flags, checked) {
    let body;
    if (flags.every((f) => f.level === "unknown")) {
      body = `<span class="nodata">${NO_DATA}</span>`; // the check itself failed, so we can't say it's all clear
    } else {
      const shown = flags.filter((f) => f.applies);
      const hazards = shown.filter((f) => f.key !== "public_housing");
      body = (hazards.length ? "" : `<div class="clear">No flood, heritage or power-line issues nearby ✓</div>`)
        + shown.map((f) => `<div class="flag">
            <span class="dot ${esc(f.level)}"></span><span class="what">${esc(f.label)}</span><span class="said ${esc(f.level)}">${esc(f.text)}</span>
          </div>`).join("");
    }
    return `<div class="sec">
      <div class="head"><span class="title">Things to check before you buy</span><span class="date">Checked ${fullDate(checked)}</span></div>
      ${body}
    </div>`;
  }

  function streetHtml(street) {
    if (!street || street === NO_DATA) return "";
    const forecast = isNumber(street.annual_4y)
      ? `Forecast ${street.annual_4y}% a year${isNumber(street.suburb_annual_4y) ? `, against ${street.suburb_annual_4y}% for the suburb` : ""}`
      : "";
    const asOf = street.as_of !== NO_DATA ? `Forecast from ${street.as_of}` : "";
    return `<div class="sec">
      <div class="head"><span class="title">This street</span></div>
      <div class="rank">${esc(street.street)} ranks <b>${street.rank}</b> of ${street.total} streets in ${esc(street.suburb)} on 4-year forecast growth.</div>
      <div class="how">${[forecast, street.band !== NO_DATA ? esc(street.band) : "", asOf].filter(Boolean).join(" · ")}</div>
    </div>`;
  }

  function reportHtml(data, level) {
    const questions = data.ask_agent || [];
    return matchHtml(data, level)
      + priceHtml(data.price)
      + dailyLifeHtml(data.daily_life, data.checked_on)
      + flagsHtml(data.flags, data.checked_on)
      + streetHtml(data.street)
      + (questions.length ? `<div class="sec"><div class="head"><span class="title">Ask the agent</span></div><ul>${questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul></div>` : "")
      + `<div class="foot">
          <a class="report" href="${esc(data.full_report_url)}" target="_blank" rel="noopener">Full report</a>
          <a class="credit" href="https://www.microburbs.com.au" target="_blank" rel="noopener">Data: Microburbs</a>
        </div>`;
  }

  function typeBoxHtml(value) {
    return `<form data-do="type">
      <label for="mb-type">Type the full address, with the unit</label>
      <div class="line">
        <input id="mb-type" autocomplete="off" spellcheck="false" placeholder="1001/2 Sam Sing Street, Waterloo" value="${esc(value)}">
        <button class="go" type="submit">Check</button>
      </div>
    </form>`;
  }

  function creditHtml() {
    return `<div class="foot"><span></span><a class="credit" href="https://www.microburbs.com.au" target="_blank" rel="noopener">Data: Microburbs</a></div>`;
  }

  function pickHtml(data, typed) {
    state.candidates = data.candidates || [];
    const heading = /doesn't show a unit/.test(data.message || "") ? "Pick your unit" : "Which home is it?";
    return `<div class="ask">
      <div class="big">${heading}</div>
      <div class="said-more">${esc(data.message)}</div>
      <div class="picks">${state.candidates.map((c, i) => `<button data-do="pick" data-i="${i}">${esc(c.address)}${c.level === "building" ? "<small>Whole building</small>" : ""}</button>`).join("")}</div>
      ${typeBoxHtml(data.address || typed || "")}
    </div>` + creditHtml();
  }

  function outsideHtml(data, typed) {
    return `<div class="ask">
      <div class="big">Outside our map, for now</div>
      <div class="said-more">${esc(data.message)}</div>
      ${typeBoxHtml(typed || "")}
    </div>` + creditHtml();
  }

  function askTypeHtml(heading, message, value) {
    return `<div class="ask">
      <div class="big">${esc(heading)}</div>
      <div class="said-more">${esc(message)}</div>
      ${typeBoxHtml(value || "")}
    </div>` + creditHtml();
  }

  function loadingHtml(address) {
    const bar = (w, h, m = 8) => `<div class="bone" style="width:${w}%;height:${h}px;margin-top:${m}px"></div>`;
    const lines = (n) => Array.from({ length: n }, () => bar(70 + Math.round(Math.random() * 25), 13, 10)).join("");
    return `<div class="match">
        ${address ? `<div class="addr">${esc(address)}</div>` : bar(80, 22, 0)}
        ${bar(34, 22, 9)}
      </div>
      <div class="price">${bar(70, 13, 0)}${bar(88, 34, 9)}${bar(92, 11, 9)}</div>
      <div class="sec">${bar(35, 13, 0)}${lines(5)}</div>
      <div class="sec">${bar(60, 13, 0)}${lines(4)}</div>`;
  }

  // ---------------------------------------------------------------- the panel on the page

  const state = { host: null, shadow: null, collapsed: false, runId: 0, candidates: [], lastParams: null, seenAddress: "" };

  function ensurePanel() {
    if (state.host && state.host.isConnected) return;
    state.host = document.createElement("div");
    state.host.id = "microburbs-facts";
    state.shadow = state.host.attachShadow({ mode: "open" });
    state.shadow.innerHTML = `<style>${STYLES}</style>
      <div class="wrap">
        <div class="panel">
          <div class="top"><span class="badge">${LOGO}</span><span class="brand">Microburbs</span><span class="strap">facts for this home</span>
            <button class="fold" data-do="fold" aria-label="Hide the panel" title="Hide">›</button></div>
          <div class="scroll"></div>
        </div>
        <button class="pill" data-do="fold" aria-label="Show Microburbs facts"><span class="badge">${LOGO}</span>Microburbs</button>
      </div>`;
    // Typing in our box mustn't set off the site's own keyboard shortcuts.
    for (const type of ["keydown", "keyup", "keypress"]) state.host.addEventListener(type, (e) => e.stopPropagation());
    state.shadow.addEventListener("click", onClick);
    state.shadow.addEventListener("submit", onSubmit);
    document.documentElement.appendChild(state.host);
    applyCollapsed();
  }

  function applyCollapsed() {
    state.shadow.querySelector(".panel").style.display = state.collapsed ? "none" : "";
    state.shadow.querySelector(".pill").style.display = state.collapsed ? "flex" : "none";
  }

  function show(html) {
    ensurePanel();
    const scroll = state.shadow.querySelector(".scroll");
    scroll.innerHTML = html;
    scroll.scrollTop = 0;
  }

  function removePanel() {
    state.runId += 1;
    if (state.host) state.host.remove();
    state.host = null;
    state.shadow = null;
  }

  function onClick(event) {
    const button = event.target.closest("[data-do]");
    if (!button || button.tagName === "FORM") return;
    const action = button.dataset.do;
    if (action === "fold") {
      state.collapsed = !state.collapsed;
      applyCollapsed();
    } else if (action === "pick") {
      const c = state.candidates[Number(button.dataset.i)];
      if (c) lookup({ gnaf_id: c.gnaf_id, address: c.address, level: c.level }, c.level, c.address);
    } else if (action === "change") {
      show(askTypeHtml("Which home is it?", "Type the address, and we'll check it again.", state.seenAddress));
      focusBox();
    } else if (action === "retry" && state.lastParams) {
      lookup(state.lastParams.params, state.lastParams.level, state.lastParams.address);
    }
  }

  function onSubmit(event) {
    event.preventDefault();
    const typed = event.target.querySelector("input").value.trim();
    if (typed) lookup({ address: typed }, "", typed);
  }

  function focusBox() {
    const input = state.shadow.querySelector("input");
    if (input) {
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
  }

  function lookup(params, level, address) {
    const id = ++state.runId;
    state.lastParams = { params, level, address };
    if (address) state.seenAddress = address;
    show(loadingHtml(address));
    const failed = () => show(`<div class="ask">
        <div class="big">We couldn't reach the data</div>
        <div class="said-more">Please try again in a moment.</div>
        <div class="picks"><button data-do="retry">Try again</button></div>
      </div>` + creditHtml());
    try {
      chrome.runtime.sendMessage({ type: "lookup", params }, (reply) => {
        if (id !== state.runId) return; // the user has moved on to another listing
        if (chrome.runtime.lastError || !reply || !reply.ok) return failed();
        render(reply.data, level, address);
      });
    } catch (e) {
      failed(); // the extension was reloaded while this page stayed open
    }
  }

  function render(data, level, typed) {
    if (data.match === "exact" || data.match === "picked") {
      show(reportHtml(data, level));
    } else if (data.match === "pick") {
      show(pickHtml(data, typed));
    } else if (data.match === "outside") {
      show(outsideHtml(data, typed));
    } else {
      show(askTypeHtml("Let's find this home", data.message || "We couldn't find that address.", typed));
      focusBox();
    }
  }

  // ---------------------------------------------------------------- starting up, and following the site

  // These sites change pages without a full reload, so the address can appear late or change later.
  function start(afterMove) {
    const id = ++state.runId;
    const began = Date.now();
    const tryNow = () => {
      if (id !== state.runId) return;
      const address = addressOnPage();
      const fits = address && (!afterMove || addressFitsLink(address));
      if (fits) return lookup({ address }, "", address);

      const waited = Date.now() - began;
      if (waited < (isListingLink() ? 6000 : 3000)) return void setTimeout(tryNow, 300);
      if (!isListingLink() && !address) return removePanel(); // a search page or an article, so stay away

      state.seenAddress = address;
      show(askTypeHtml("This listing hides its address",
        address ? "Please check this is the right address." : "Type it below to see the facts.", address));
    };
    if (isListingLink()) show(loadingHtml(""));
    tryNow();
  }

  let lastUrl = location.href;
  setInterval(() => {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    removePanel();
    start(true);
  }, 500);

  start(false);
})();
