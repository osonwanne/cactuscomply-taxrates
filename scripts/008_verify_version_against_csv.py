"""
Verify (and optionally fix) a stored rate_version against its own ADOR CSV.

Re-parses the source CSV with the current (fixed) parse_rate, compares every
rate against what is stored for the given rate_version, and reports cells that
are "not in the right shape". With --apply, corrects the mismatched rows
in place (only city_rate / county_rate; total_rate is generated).

Default is a dry run — writes nothing unless --apply is passed.

Usage:
    python scripts/008_verify_version_against_csv.py <version_id> <csv_path>
    python scripts/008_verify_version_against_csv.py 115 "C:/Users/noson/Downloads/TPT_RATETABLE_ALL_04012026.csv"
    python scripts/008_verify_version_against_csv.py 115 "...04012026.csv" --apply
"""

import csv
import os
import sys
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

supabase: Client = create_client(
    os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))


def parse_rate(rate_str: str) -> float:
    """Identical to 004_add_monthly_rates.parse_rate (the fixed version)."""
    if not rate_str:
        return 0.0
    rate_str = str(rate_str).strip().replace("%", "")
    try:
        return round(float(rate_str) / 100.0, 6)
    except ValueError:
        return 0.0


def build_jurisdiction_cache() -> Dict[str, Tuple[int, str, str]]:
    """Copy of 004's build_jurisdiction_cache — county records win on code clashes."""
    result = supabase.table("jurisdictions").select(
        "id, city_code, region_code, level, city_name, county_name").execute()
    candidates: Dict[str, List[Tuple[int, str, str]]] = {}
    for j in result.data:
        level = j.get("level", "city")
        name = j.get("county_name", "") if level == "county" else j.get("city_name", "")
        entry = (j["id"], level, name)
        for code in [j.get("city_code"), j.get("region_code")]:
            if code:
                candidates.setdefault(code, []).append(entry)
    cache = {}
    for code, entries in candidates.items():
        if len(entries) == 1:
            cache[code] = entries[0]
        else:
            county = [e for e in entries if e[1] == "county"]
            cache[code] = county[0] if county else entries[0]
    return cache


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if len(args) < 2:
        print("Usage: python scripts/008_verify_version_against_csv.py <version_id> <csv_path> [--apply]")
        return

    version_id = int(args[0])
    csv_path = args[1]
    if not os.path.isfile(csv_path):
        print(f"ERROR: File not found: {csv_path}")
        return

    print("=" * 64)
    print(f"VERIFY rate_version {version_id} against {os.path.basename(csv_path)}")
    print(f"MODE: {'APPLY (will write)' if apply else 'DRY RUN (read only)'}")
    print("=" * 64)

    cache = build_jurisdiction_cache()

    # Correct rates from the CSV, keyed (jurisdiction_id, business_code)
    csv_rates: Dict[Tuple[int, str], float] = {}
    for row in csv.DictReader(open(csv_path, 'r', encoding='utf-8-sig')):
        region = (row.get('RegionCode') or '').strip()
        bcode = (row.get('BusinessCode') or '').strip()
        rate = parse_rate(row.get('TaxRate') or '0')
        if not (region and bcode and rate > 0):
            continue
        lookup = cache.get(region)
        if lookup:
            csv_rates[(lookup[0], bcode)] = rate

    # Stored rows for the version
    stored: List[dict] = []
    start, page = 0, 1000
    while True:
        res = supabase.table("rates").select(
            "id, jurisdiction_id, business_code, city_rate, county_rate"
        ).eq("rate_version_id", version_id).order("id").range(
            start, start + page - 1).execute()
        stored.extend(res.data)
        if len(res.data) < page:
            break
        start += page
    print(f"Stored rows: {len(stored)}   CSV resolved rates: {len(csv_rates)}\n")

    juris = {j["id"]: j for j in supabase.table("jurisdictions").select(
        "id, city_name, county_name, level").execute().data}

    def label(jid, bcode):
        j = juris.get(jid, {})
        nm = j.get("county_name") if j.get("level") == "county" else j.get("city_name")
        return f"{nm or '?'} ({jid}) / {bcode}"

    mismatches = []   # (row, stored_rate, correct_rate, level)
    not_in_csv = []
    for row in stored:
        key = (row["jurisdiction_id"], (row["business_code"] or "").strip())
        if key not in csv_rates:
            not_in_csv.append(row)
            continue
        correct = csv_rates[key]
        j = juris.get(row["jurisdiction_id"], {})
        level = j.get("level", "city")
        stored_rate = float((row["county_rate"] if level == "county"
                             else row["city_rate"]) or 0)
        if abs(stored_rate - correct) > 1e-9:
            mismatches.append((row, stored_rate, correct, level))

    print(f"Mismatched rows (wrong shape): {len(mismatches)}")
    print(f"Stored rows with no CSV match: {len(not_in_csv)}\n")

    if mismatches:
        print("--- MISMATCHES (stored -> correct) ---")
        for row, sr, cr, level in sorted(
                mismatches, key=lambda x: -abs(x[2] - x[1])):
            ratio = f"  [{sr / cr:.0f}x]" if cr else ""
            print(f"  {label(row['jurisdiction_id'], row['business_code']):<48} "
                  f"{sr:.4%} -> {cr:.4%}{ratio}")

    if not_in_csv:
        print(f"\n--- {len(not_in_csv)} stored rows have no CSV counterpart "
              f"(first 10) ---")
        for row in not_in_csv[:10]:
            print(f"  {label(row['jurisdiction_id'], row['business_code'])}")

    if not mismatches:
        print("\nVersion is in the right shape. Nothing to fix.")
        return

    if not apply:
        print(f"\nDRY RUN — {len(mismatches)} rows would be corrected. "
              f"Re-run with --apply to fix.")
        return

    print(f"\nApplying {len(mismatches)} corrections...")
    fixed = 0
    for row, sr, cr, level in mismatches:
        patch = {"county_rate": cr, "city_rate": 0.0} if level == "county" \
            else {"city_rate": cr, "county_rate": 0.0}
        supabase.table("rates").update(patch).eq("id", row["id"]).execute()
        fixed += 1
        if fixed % 100 == 0:
            print(f"  ...{fixed}/{len(mismatches)}")
    print(f"Done — {fixed} rows corrected in rate_version {version_id}.")


if __name__ == "__main__":
    main()
