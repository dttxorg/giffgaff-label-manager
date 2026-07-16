#!/usr/bin/env python3
"""Build the bundled UK address pool from the official FHRS open-data API.

This is an offline maintenance command, not part of customer creation. It fetches
public-facing business premises, validates every postcode with Postcodes.io, and
writes a deterministic CSV consumed by ``backend/uk_random.py``.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, Optional


FHRS_API = "https://api.ratings.food.gov.uk"
POSTCODES_API = "https://api.postcodes.io/postcodes"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "uk_public_addresses.csv"
USER_AGENT = "giffgaff-label-manager-address-pool/1.0"

# Local-authority IDs come from the API's /Authorities endpoint. This small
# configuration controls geographic balance; no address is hand-maintained here.
CITY_AUTHORITIES: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("London", 95, ("London",)),
    ("Birmingham", 374, ("Birmingham",)),
    ("Manchester", 180, ("Manchester",)),
    ("Liverpool", 179, ("Liverpool",)),
    ("Leeds", 397, ("Leeds",)),
    ("Sheffield", 399, ("Sheffield",)),
    ("Bristol", 324, ("Bristol",)),
    ("Nottingham", 87, ("Nottingham",)),
    ("Leicester", 85, ("Leicester",)),
    ("Edinburgh", 210, ("Edinburgh",)),
    ("Glasgow", 213, ("Glasgow",)),
    ("Cardiff", 339, ("Cardiff",)),
    ("Belfast", 138, ("Belfast",)),
    ("Newcastle upon Tyne", 122, ("Newcastle upon Tyne", "Newcastle")),
    ("Oxford", 262, ("Oxford",)),
    ("Cambridge", 1, ("Cambridge",)),
    ("York", 406, ("York",)),
    ("Bath", 326, ("Bath",)),
    ("Exeter", 297, ("Exeter",)),
    ("Portsmouth", 287, ("Portsmouth",)),
    ("Brighton", 286, ("Brighton",)),
    ("Aberdeen", 197, ("Aberdeen",)),
    ("Dundee", 209, ("Dundee",)),
    ("Plymouth", 331, ("Plymouth",)),
    ("Coventry", 375, ("Coventry",)),
    ("Derby", 84, ("Derby",)),
    ("Southampton", 288, ("Southampton",)),
    ("Reading", 291, ("Reading",)),
    ("Wolverhampton", 380, ("Wolverhampton",)),
    ("Stoke-on-Trent", 382, ("Stoke-on-Trent", "Stoke on Trent")),
)

# Keep only types that normally have a public premises. This excludes mobile
# caterers and most home-based food businesses even when their address is listed.
PUBLIC_PREMISES_TYPES = {
    "Hospitals/Childcare/Caring Premises",
    "Hotel/bed & breakfast/guest house",
    "Pub/bar/nightclub",
    "Restaurant/Cafe/Canteen",
    "Retailers - other",
    "Retailers - supermarkets/hypermarkets",
    "School/college/university",
    "Takeaway/sandwich shop",
}

POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$")
ADDRESS_START_RE = re.compile(
    r"^(?:\d|[A-Z]{1,3}\d|(?:flat|unit|suite|shop|floor|storey|retail unit|room|block|plot|kiosk|arches?)\b)",
    re.IGNORECASE,
)
VAGUE_UNIT_RE = re.compile(
    r"^(?:flat|unit|suite|shop|floor|storey|retail unit|room|block|plot|kiosk|arches?)\s+[A-Z0-9/&-]+$",
    re.IGNORECASE,
)
SPACE_RE = re.compile(r"\s+")


def _json_request(url: str, *, payload: Optional[dict] = None, attempts: int = 3) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if url.startswith(FHRS_API):
        headers["x-api-version"] = "2"

    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except Exception as exc:  # pragma: no cover - exercised only on network failure
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after {attempts} attempts: {url}") from last_error


def normalize_postcode(value: object) -> Optional[str]:
    compact = re.sub(r"\s+", "", str(value or "").upper())
    if len(compact) < 5:
        return None
    postcode = f"{compact[:-3]} {compact[-3:]}"
    return postcode if POSTCODE_RE.fullmatch(postcode) else None


def _clean_line(value: object) -> str:
    return SPACE_RE.sub(" ", str(value or "").strip(" ,"))


def _comparison_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def establishment_to_row(
    establishment: dict,
    city: str,
    city_aliases: tuple[str, ...],
) -> Optional[dict[str, str]]:
    """Convert one FHRS establishment into a safe public-premises address row."""
    if establishment.get("BusinessType") not in PUBLIC_PREMISES_TYPES:
        return None

    postcode = normalize_postcode(establishment.get("PostCode"))
    if not postcode:
        return None

    lines = [
        _clean_line(establishment.get(f"AddressLine{index}"))
        for index in range(1, 5)
    ]
    lines = [line for line in lines if line]
    alias_keys = {_comparison_key(alias) for alias in city_aliases}
    if not any(_comparison_key(line) in alias_keys for line in lines):
        return None

    address_lines: list[str] = []
    seen_lines: set[str] = set()
    business_name = _clean_line(establishment.get("BusinessName"))
    business_key = _comparison_key(business_name)
    for line in lines:
        # A few councils store "Trading Name + numbered address" in one field.
        # Remove that exact prefix while retaining the postal part.
        if business_name and line.casefold().startswith(business_name.casefold()):
            remainder = line[len(business_name):].strip(" ,-/")
            if remainder and any(character.isdigit() for character in remainder):
                line = remainder
        key = _comparison_key(line)
        # Some councils repeat the trading name as AddressLine1. It identifies
        # the premises but makes a generated customer address look unnatural;
        # the numbered postal address on the following lines is sufficient.
        if key in alias_keys or key in seen_lines or key == business_key:
            continue
        seen_lines.add(key)
        address_lines.append(line)

    # When the first line is an unnumbered building/trading name and later lines
    # already contain a precise numbered address, keep the latter only. This
    # produces natural address-form input without weakening traceability.
    if (
        len(address_lines) > 1
        and not any(character.isdigit() for character in address_lines[0])
        and any(character.isdigit() for line in address_lines[1:] for character in line)
    ):
        address_lines.pop(0)

    address = ", ".join(address_lines)
    # A house/unit number makes the pairing substantially less ambiguous and
    # avoids vague records containing only a road or district name.
    if not address or not any(character.isdigit() for character in address):
        return None
    if _comparison_key(address) == _comparison_key(postcode):
        return None
    if not ADDRESS_START_RE.match(address):
        return None
    if VAGUE_UNIT_RE.fullmatch(address):
        return None
    if "po box" in address.casefold():
        return None

    source_id = str(establishment.get("FHRSID") or "").strip()
    if not source_id:
        return None
    return {
        "address": address,
        "city": city,
        "postcode": postcode,
        "source_id": source_id,
    }


def fetch_city_rows(
    city: str,
    authority_id: int,
    aliases: tuple[str, ...],
    quota: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    page_number = 1

    while len(rows) < quota and page_number <= 8:
        query = urllib.parse.urlencode({
            "localAuthorityId": authority_id,
            "pageSize": 100,
            "pageNumber": page_number,
        })
        response = _json_request(f"{FHRS_API}/Establishments?{query}")
        establishments = response.get("establishments") or []
        if not establishments:
            break
        for establishment in establishments:
            row = establishment_to_row(establishment, city, aliases)
            if not row:
                continue
            key = (row["address"].casefold(), row["postcode"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= quota:
                break
        page_number += 1
    return rows


def validate_postcodes(rows: Iterable[dict[str, str]]) -> set[str]:
    postcodes = sorted({row["postcode"] for row in rows})
    valid: set[str] = set()
    for start in range(0, len(postcodes), 100):
        response = _json_request(
            POSTCODES_API,
            payload={"postcodes": postcodes[start:start + 100]},
        )
        for result in response.get("result") or []:
            if result.get("result") is not None:
                valid.add(result["query"])
    return valid


def round_robin(rows_by_city: dict[str, list[dict[str, str]]], target: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    city_order = [city for city, _, _ in CITY_AUTHORITIES]
    index = 0
    while len(selected) < target:
        added = False
        for city in city_order:
            rows = rows_by_city.get(city, [])
            if index < len(rows):
                selected.append(rows[index])
                added = True
                if len(selected) == target:
                    break
        if not added:
            break
        index += 1
    return selected


def build_pool(target: int) -> list[dict[str, str]]:
    per_city_quota = max(30, (target // len(CITY_AUTHORITIES)) + 12)
    rows_by_city: dict[str, list[dict[str, str]]] = defaultdict(list)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_city_rows, city, authority_id, aliases, per_city_quota): city
            for city, authority_id, aliases in CITY_AUTHORITIES
        }
        for future in as_completed(futures):
            city = futures[future]
            rows_by_city[city] = future.result()
            print(f"{city}: {len(rows_by_city[city])} candidates", flush=True)

    all_rows = [row for rows in rows_by_city.values() for row in rows]
    valid_postcodes = validate_postcodes(all_rows)
    for city in rows_by_city:
        rows_by_city[city] = [
            row for row in rows_by_city[city]
            if row["postcode"] in valid_postcodes
        ]

    selected = round_robin(rows_by_city, target)
    if len(selected) < target:
        raise RuntimeError(
            f"only {len(selected)} verified addresses available; requested {target}"
        )
    return selected


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("address", "city", "postcode", "source_id"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=600)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.target < 500:
        parser.error("--target must be at least 500")

    rows = build_pool(args.target)
    write_csv(rows, args.output)
    city_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        city_counts[row["city"]] += 1
    print(f"wrote {len(rows)} verified addresses to {args.output}")
    print("city range:", min(city_counts.values()), "to", max(city_counts.values()))


if __name__ == "__main__":
    main()
