"""Turn a free-text address into parts we can compare.

A listing, the geocoder and the suburb property list all write one home differently:

    Unit 1001, 2 Sam Sing St, Waterloo NSW 2017
    UNIT 1001/2 Sam Sing Street, Waterloo (NSW)
    1001/2 SAM SING ST WATERLOO 2017

parse_address() reads all of them into the same Address, and the helpers below
compare two Addresses. Nothing here calls the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Every spelling of a street type, mapped to one form.
STREET_TYPES = {
    "STREET": "ST", "ST": "ST", "ROAD": "RD", "RD": "RD", "AVENUE": "AVE", "AVE": "AVE", "AV": "AVE",
    "DRIVE": "DR", "DR": "DR", "LANE": "LANE", "LN": "LANE", "PLACE": "PL", "PL": "PL",
    "PARADE": "PDE", "PDE": "PDE", "CIRCUIT": "CCT", "CCT": "CCT", "CRESCENT": "CRES", "CRES": "CRES",
    "COURT": "CT", "CT": "CT", "CLOSE": "CL", "CL": "CL", "TERRACE": "TCE", "TCE": "TCE",
    "HIGHWAY": "HWY", "HWY": "HWY", "BOULEVARD": "BVD", "BOULEVARDE": "BVD", "BLVD": "BVD", "BVD": "BVD",
    "WAY": "WAY", "WALK": "WALK", "SQUARE": "SQ", "SQ": "SQ", "QUAY": "QY", "QY": "QY",
    "ESPLANADE": "ESP", "ESP": "ESP", "GROVE": "GR", "GR": "GR", "ROW": "ROW", "MEWS": "MEWS",
    "ARCADE": "ARC", "ARC": "ARC", "PROMENADE": "PROM", "PROM": "PROM", "SAINT": "ST", "MT": "MOUNT",
}
FULL_WORDS = {
    "ST": "Street", "RD": "Road", "AVE": "Avenue", "DR": "Drive", "LANE": "Lane", "PL": "Place", "PDE": "Parade",
    "CCT": "Circuit", "CRES": "Crescent", "CT": "Court", "CL": "Close", "TCE": "Terrace", "HWY": "Highway",
    "BVD": "Boulevard", "WAY": "Way", "WALK": "Walk", "SQ": "Square", "QY": "Quay", "ESP": "Esplanade",
    "GR": "Grove", "ROW": "Row", "MEWS": "Mews", "ARC": "Arcade", "PROM": "Promenade",
}

UNIT_WORDS = ("UNIT|APARTMENT|APT|FLAT|VILLA|STUDIO|TOWNHOUSE|PENTHOUSE|DUPLEX|MAISONETTE|"
              "SUITE|SHOP|OFFICE|KIOSK|FACTORY|WAREHOUSE|STORE|LOT|ROOM|CARSPACE|BERTH")
# Records with these words are not homes, so "1/80 Campbell St" must not match "SHOP 1/80 Campbell St".
NOT_A_HOME = {"SUITE", "SHOP", "OFFICE", "KIOSK", "FACTORY", "WAREHOUSE", "STORE", "LOT", "ROOM", "CARSPACE", "BERTH"}

STATES = "NSW|NEW SOUTH WALES|VIC|VICTORIA|QLD|QUEENSLAND|SA|WA|TAS|TASMANIA|ACT|NT"


@dataclass
class Address:
    unit: str | None = None       # "18E"
    unit_word: str | None = None  # "APARTMENT"
    number: str | None = None     # "219-231"
    lo: int | None = None         # 219
    hi: int | None = None         # 231, or None when it isn't a range
    street: str = ""              # "Sam Sing Street"
    street_key: str = ""          # "SAMSINGST"
    suburb: str | None = None     # "Waterloo"
    suburb_key: str | None = None  # "WATERLOO"

    @property
    def is_home(self) -> bool:
        return self.unit_word not in NOT_A_HOME


def clean_key(text: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text.upper()).split())


def make_street_key(street: str) -> str:
    """'Sam Sing St' and 'SAM SING STREET' both become 'SAMSINGST'. O'Connor and Oconnor match too."""
    words = re.sub(r"[^A-Z0-9 ]", "", street.upper()).split()
    return "".join(STREET_TYPES.get(w, w) for w in words)


def tidy(text: str) -> str:
    """Title-case text that arrived in capitals, and leave anything else alone."""
    return text.title() if text.isupper() else text


def full_street(street: str) -> str:
    """'SAM SING ST' -> 'Sam Sing Street'. The geocoder matches the full word better."""
    words = tidy(street).split()
    if len(words) > 1:
        words[-1] = FULL_WORDS.get(STREET_TYPES.get(words[-1].upper(), ""), words[-1])
    return " ".join(words)


def _split_unit(s: str) -> tuple[str | None, str | None, str]:
    """Take any unit off the front of the address. Returns (unit, word for it, the rest)."""
    # "Unit 1001, 2 Sam Sing St" / "UNIT 1001/2 Sam Sing" / "Apartment 18E 4 Distillery Dr"
    m = re.match(rf"({UNIT_WORDS})\.?\s*#?\s*([A-Z0-9-]+)\s*(?:[,/]\s*|\s+)(?=\d)", s, re.I)
    if m:
        return m.group(2).upper(), m.group(1).upper(), s[m.end():]
    # "1001/2 Sam Sing", "D534/810-822 Elizabeth", "18E/4 Distillery", "G/12 Foo"
    m = re.match(r"([A-Z]{0,3}\d*[A-Z]{0,2}(?:-\d+)?)\s*/\s*(?=\d)", s, re.I)
    if m and m.group(1):
        return m.group(1).upper(), None, s[m.end():]
    # "G02, 12 Foo St"
    m = re.match(r"([A-Z]{0,3}\d+[A-Z]?)\s*,\s*(?=\d)", s, re.I)
    if m:
        return m.group(1).upper(), None, s[m.end():]
    return None, None, s


def _split_street_suburb(rest: str, suburbs: list[str]) -> tuple[str, str | None]:
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if len(parts) >= 2:
        keys = {clean_key(s) for s in suburbs}
        known = next((p for p in parts[1:] if clean_key(p) in keys), None)
        return parts[0], known or parts[1]
    # No comma. Look for a suburb we know at the end, longest first ("Elizabeth Bay Road Elizabeth Bay").
    for label in sorted(suburbs, key=len, reverse=True):
        if rest.upper().endswith(" " + label.upper()):
            return rest[:-len(label) - 1].strip(), rest[-len(label):]
    # Otherwise cut after the first street-type word ("Campbell Parade Bondi Beach").
    words = rest.split()
    for i in range(1, len(words)):
        if words[i].upper() in STREET_TYPES:
            return " ".join(words[:i + 1]), " ".join(words[i + 1:]) or None
    return rest, None


def parse_address(text: str, suburbs: list[str] = ()) -> Address:
    """Read an address in any of the usual forms. `suburbs` helps when there are no commas."""
    s = " ".join((text or "").replace("–", "-").replace("—", "-").split())
    s = re.sub(r"\s*\([^)]*\)", "", s)  # "Waterloo (NSW)" -> "Waterloo"
    s = re.sub(rf"[\s,]+(?:{STATES})\b[\s,]*(?:\d{{4}})?\s*$", "", s, flags=re.I)  # "NSW 2017"
    s = re.sub(r"[\s,]+\d{4}\s*$", "", s).strip(" ,")  # a postcode with no state
    s = re.sub(r"\b(?:LEVEL|LVL|FLOOR)\s+(?:\d+|[GMB]\d*|UG|LG)\b\s*[,/]?\s*", "", s, flags=re.I)  # floors aren't units

    unit, word, s = _split_unit(s)
    out = Address(unit=unit, unit_word={"APT": "APARTMENT"}.get(word, word))

    m = re.match(r"(\d+[A-Z]?)(?:\s*(?:-|&|\bTO\b)\s*(\d+[A-Z]?))?[\s,]+(.+)", s, re.I)
    if not m:
        street, suburb = _split_street_suburb(s, list(suburbs))
    else:
        first, second, rest = m.groups()
        out.number = first.upper() + (f"-{second.upper()}" if second else "")
        out.lo = int(re.sub(r"\D", "", first))
        out.hi = int(re.sub(r"\D", "", second)) if second else None
        street, suburb = _split_street_suburb(rest, list(suburbs))

    out.street = street.strip(" ,")
    out.street_key = make_street_key(out.street)
    if suburb:
        out.suburb = tidy(suburb.strip(" ,"))
        out.suburb_key = clean_key(suburb)
    return out


def same_number(a: Address, b: Address) -> bool:
    """Equal street numbers, or ranges that overlap (810-822 covers 810; 903-921 covers 911)."""
    if a.lo is None or b.lo is None:
        return False
    if a.hi is None and b.hi is None:
        return a.number == b.number  # 113A is not 113
    return a.lo <= (b.hi or b.lo) and b.lo <= (a.hi or a.lo)


def unit_key(unit: str | None) -> str:
    """Ignore the letter's position and any padding: D534, 534D -> '534|D'; G01, G1 -> '1|G'."""
    if not unit:
        return ""
    digits = "-".join(str(int(d)) for d in re.findall(r"\d+", unit))
    return f"{digits}|{''.join(sorted(re.findall(r'[A-Z]', unit)))}"


def swapped_unit(unit: str | None) -> str | None:
    """D534 -> 534D and 534D -> D534. None when the unit isn't letters-and-digits."""
    m = re.fullmatch(r"([A-Z]+)(\d+)|(\d+)([A-Z]+)", unit or "")
    if not m:
        return None
    return f"{m.group(2)}{m.group(1)}" if m.group(1) else f"{m.group(4)}{m.group(3)}"


def pretty(a: Address) -> str:
    """'1001/2 Sam Sing Street, Waterloo', keeping the word only for non-homes ('Shop 1/80 ...')."""
    lead = f"{a.unit_word.title()} " if a.unit and not a.is_home else ""
    unit = f"{a.unit}/" if a.unit else ""
    place = f"{lead}{unit}{a.number or ''} {full_street(a.street)}".strip()
    return f"{place}, {a.suburb}" if a.suburb else place
