"""
Dry-run drift check for a monthly ADOR CSV.

Read-only. Writes nothing. Mirrors 004_add_monthly_rates.py's jurisdiction
resolution exactly so the diff reflects what an actual load would do.

Compares the new CSV against the most recent prior rate_version and reports
new / changed / removed rates, plus the two Stripe-relevant cells
(Peoria PE/214 and Maricopa County MAR/014).

Usage:
    python scripts/004_dry_run.py "C:/Users/noson/Downloads/TPT_RATETABLE_ALL_05012026.csv"
"""

import csv
import os
import re
import sys
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def parse_rate(rate_str: str) -> float:
    """Parse rate string to decimal — identical to 004_add_monthly_rates.parse_rate."""
    if not rate_str:
        return 0.0
    rate_str = str(rate_str).strip().replace("%", "")
    try:
        return round(float(rate_str) / 100.0, 6)
    except ValueError:
        return 0.0


def parse_date_from_filename(filename: str) -> str:
    match = re.search(r'(\d{8})', filename)
    if not match:
        raise ValueError(f"Cannot parse date from filename: {filename}")
    d = match.group(1)
    return f"{int(d[4:])}-{int(d[:2]):02d}-{int(d[2:4]):02d}"


def build_jurisdiction_cache() -> Dict[str, Tuple[int, str, str]]:
    """Copy of 004's build_jurisdiction_cache — county records win on code clashes."""
    result = supabase.table("jurisdictions").select(
        "id, city_code, region_code, level, city_name, county_name"
    ).execute()

    candidates: Dict[str, List[Tuple[int, str, str]]] = {}
    for j in result.data:
        level = j.get("level", "city")
        display_name = j.get("county_name", "") if level == "county" else j.get("city_name", "")
        entry = (j["id"], level, display_name)
        for code in [j.get("city_code"), j.get("region_code")]:
            if code:
                candidates.setdefault(code, []).append(entry)

    cache = {}
    for code, entries in candidates.items():
        if len(entries) == 1:
            cache[code] = entries[0]
        else:
            county_entries = [e for e in entries if e[1] == "county"]
            cache[code] = county_entries[0] if county_entries else entries[0]
    return cache


def fetch_all_rates(version_id: int) -> Dict[Tuple[int, str], float]:
    """Paginate through all rates for a version -> {(jurisdiction_id, business_code): rate}."""
    out: Dict[Tuple[int, str], float] = {}
    start = 0
    page = 1000
    while True:
        res = supabase.table("rates").select(
            "jurisdiction_id, business_code, city_rate, county_rate"
        ).eq("rate_version_id", version_id).order("id").range(
            start, start + page - 1).execute()
        for r in res.data:
            rate = float(r.get("city_rate") or 0) + float(r.get("county_rate") or 0)
            out[(r["jurisdiction_id"], (r["business_code"] or "").strip())] = round(rate, 6)
        if len(res.data) < page:
            break
        start += page
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/004_dry_run.py <csv_path>")
        return

    csv_path = sys.argv[1]
    if not os.path.isfile(csv_path):
        print(f"ERROR: File not found: {csv_path}")
        return

    new_eff = parse_date_from_filename(os.path.basename(csv_path))
    print("=" * 64)
    print(f"DRY RUN — {os.path.basename(csv_path)}  (effective {new_eff})")
    print("=" * 64)

    # Prior version = latest rate_version with effective_date < new effective date
    vers = supabase.table("rate_versions").select("id, effective_date").order(
        "effective_date", desc=True).execute()
    prior = next((v for v in vers.data if v["effective_date"] < new_eff), None)
    if not prior:
        print("WARNING: no prior rate_version found — every row will read as NEW.")
        prior_rates: Dict[Tuple[int, str], float] = {}
        prior_label = "(none)"
    else:
        prior_rates = fetch_all_rates(prior["id"])
        prior_label = f"v{prior['id']} / {prior['effective_date']}"
    print(f"Comparing against prior version: {prior_label}  ({len(prior_rates)} rates)\n")

    existing_new = supabase.table("rate_versions").select("id").eq(
        "effective_date", new_eff).execute()
    if existing_new.data:
        print(f"NOTE: a rate_version for {new_eff} already exists "
              f"(id {existing_new.data[0]['id']}) — 004 would skip duplicate rows.\n")

    cache = build_jurisdiction_cache()

    # Parse CSV into the same key space the loader uses
    new_rates: Dict[Tuple[int, str], float] = {}
    missing_codes: Dict[str, int] = {}
    dup_in_csv = 0
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            region = (row.get('RegionCode') or '').strip()
            bcode = (row.get('BusinessCode') or '').strip()
            rate = parse_rate(row.get('TaxRate') or '0')
            if not (region and bcode and rate > 0):
                continue
            lookup = cache.get(region)
            if not lookup:
                missing_codes[region] = missing_codes.get(region, 0) + 1
                continue
            key = (lookup[0], bcode)
            if key in new_rates:
                dup_in_csv += 1
            new_rates[key] = rate

    # Diff
    changed, new_rows, removed = [], [], []
    for key, rate in new_rates.items():
        if key not in prior_rates:
            new_rows.append((key, rate))
        elif abs(prior_rates[key] - rate) > 1e-9:
            changed.append((key, prior_rates[key], rate))
    for key in prior_rates:
        if key not in new_rates:
            removed.append(key)

    unchanged = len(new_rates) - len(new_rows) - len(changed)
    over_one = [(k, v) for k, v in new_rates.items() if v > 1]

    print(f"CSV resolved rates : {len(new_rates)}")
    print(f"  unchanged        : {unchanged}")
    print(f"  CHANGED          : {len(changed)}")
    print(f"  NEW (not in prior): {len(new_rows)}")
    print(f"  REMOVED (in prior, gone in CSV): {len(removed)}")
    print(f"  duplicate keys within CSV: {dup_in_csv}")
    print(f"  rates > 1.0 (100x bug check): {len(over_one)}")
    if missing_codes:
        tot = sum(missing_codes.values())
        print(f"  rows with unmapped RegionCode: {tot} "
              f"({', '.join(sorted(missing_codes))})")

    juris = supabase.table("jurisdictions").select(
        "id, city_name, county_name, level").execute()
    jmap = {j["id"]: j for j in juris.data}

    def label(jid, bcode):
        j = jmap.get(jid, {})
        nm = j.get("county_name") if j.get("level") == "county" else j.get("city_name")
        return f"{nm or '?'} ({jid}) / {bcode}"

    if changed:
        print("\n--- CHANGED RATES ---")
        for (jid, bc), old, new in sorted(changed, key=lambda x: -abs(x[2] - x[1])):
            print(f"  {label(jid, bc):<48} {old:.4%} -> {new:.4%}")
    if new_rows:
        print("\n--- NEW RATES (first 30) ---")
        for (jid, bc), rate in sorted(new_rows)[:30]:
            print(f"  {label(jid, bc):<48} {rate:.4%}")
    if removed:
        print("\n--- REMOVED RATES (first 30) ---")
        for jid, bc in sorted(removed)[:30]:
            print(f"  {label(jid, bc):<48} (was {prior_rates[(jid, bc)]:.4%})")
    if over_one:
        print("\n--- WARNING: RATES > 1.0 (possible 100x bug) ---")
        for (jid, bc), v in over_one[:30]:
            print(f"  {label(jid, bc):<48} {v}")

    # Stripe-relevant cells
    print("\n--- STRIPE CHECK (007 watches these) ---")
    for code, bcode, who in [("PE", "214", "Peoria city"),
                             ("MAR", "014", "Maricopa County")]:
        lookup = cache.get(code)
        if not lookup:
            print(f"  {who}: RegionCode {code} not in jurisdiction cache")
            continue
        key = (lookup[0], bcode)
        old = prior_rates.get(key)
        new = new_rates.get(key)
        old_s = f"{old:.4%}" if old is not None else "—"
        new_s = f"{new:.4%}" if new is not None else "—"
        flag = "  <-- CHANGED, Stripe sync would fire" if (
            old != new) else "  (no change)"
        print(f"  {who} [{code}/{bcode}]: {old_s} -> {new_s}{flag}")

    print("\n" + "=" * 64)
    print("DRY RUN COMPLETE — nothing written.")
    print("=" * 64)


if __name__ == "__main__":
    main()
