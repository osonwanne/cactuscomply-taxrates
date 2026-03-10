"""
Backfill County Rates for Missing Versions

After cleanup of duplicate county jurisdictions (old level='city' records deleted),
the correct level='county' jurisdiction records are missing rates for versions
110-113 and others (Aug 2025 - Feb 2026).

This script reads ADOR CSVs from the Downloads folder and inserts county rates
for the correct jurisdiction IDs using the county_rate column.

It does NOT create new rate_versions — it adds county rates to existing versions.

Usage:
    python scripts/005_backfill_county_rates.py
    python scripts/005_backfill_county_rates.py --dry-run
"""

import csv
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DOWNLOADS_DIR = r"C:\Users\noson\Downloads"

# Arizona County Region Codes (15 counties)
COUNTY_CODES = {
    "APA": "Apache",
    "COH": "Cochise",
    "COC": "Coconino",
    "GLA": "Gila",
    "GRA": "Graham",
    "GRN": "Greenlee",
    "LAP": "La Paz",
    "MAR": "Maricopa",
    "MOH": "Mohave",
    "NAV": "Navajo",
    "PMA": "Pima",
    "PNL": "Pinal",
    "STC": "Santa Cruz",
    "YAV": "Yavapai",
    "YMA": "Yuma",
}

# CSVs to backfill and their effective dates
CSV_FILES = [
    ("TPT_RATETABLE_ALL_08012025.csv", "2025-08-01"),
    ("TPT_RATETABLE_ALL_09012025.csv", "2025-09-01"),
    ("TPT_RATETABLE_ALL_10012025.csv", "2025-10-01"),
    ("TPT_RATETABLE_ALL_11012025.csv", "2025-11-01"),
    ("TPT_RATETABLE_ALL_01012026.csv", "2026-01-01"),
    ("TPT_RATETABLE_ALL_02012026.csv", "2026-02-01"),
]


def parse_rate(rate_str: str) -> float:
    """Parse rate string to decimal."""
    if not rate_str:
        return 0.0
    rate_str = str(rate_str).strip().replace("%", "")
    try:
        rate = float(rate_str)
        if rate > 1:
            rate = rate / 100.0
        return round(rate, 6)
    except ValueError:
        return 0.0


def get_county_jurisdiction_map() -> Dict[str, int]:
    """Map county region_code -> jurisdiction_id for level='county' records."""
    result = supabase.table("jurisdictions").select(
        "id, region_code, county_name"
    ).eq("level", "county").execute()

    mapping = {}
    for j in result.data:
        if j.get("region_code"):
            mapping[j["region_code"]] = j["id"]
    return mapping


def get_version_id_for_date(effective_date: str) -> Optional[int]:
    """Get the most recent (highest) version ID for a given effective_date."""
    result = supabase.table("rate_versions").select("id").eq(
        "effective_date", effective_date
    ).order("id", desc=True).limit(1).execute()

    if result.data:
        return result.data[0]["id"]
    return None


def get_existing_county_rates(version_id: int, county_jids: List[int]) -> set:
    """Get existing (jurisdiction_id, business_code) pairs for county rates in a version."""
    existing = set()
    for jid in county_jids:
        result = supabase.table("rates").select("business_code").eq(
            "rate_version_id", version_id
        ).eq("jurisdiction_id", jid).execute()
        for r in result.data:
            existing.add((jid, r["business_code"]))
    return existing


def extract_county_rates_from_csv(csv_path: str) -> List[dict]:
    """Extract only county rates from an ADOR CSV."""
    records = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            region_code = row.get('RegionCode', row.get('\ufeffRegionCode', '')).strip()
            if region_code not in COUNTY_CODES:
                continue

            business_code = row.get('BusinessCode', '').strip()
            tax_rate = row.get('TaxRate', '0').strip()
            rate = parse_rate(tax_rate)

            if business_code and rate > 0:
                records.append({
                    'region_code': region_code,
                    'business_code': business_code,
                    'rate': rate,
                })
    return records


def backfill_county_rates(dry_run: bool = False):
    """Main backfill logic."""
    print("=" * 60)
    print("BACKFILL COUNTY RATES")
    print("=" * 60)

    # Get county jurisdiction mapping
    county_map = get_county_jurisdiction_map()
    print(f"\nFound {len(county_map)} county jurisdictions:")
    for code, jid in sorted(county_map.items()):
        print(f"  {code} ({COUNTY_CODES.get(code, '?')}): jurisdiction_id={jid}")

    county_jids = list(county_map.values())
    total_inserted = 0

    for csv_filename, effective_date in CSV_FILES:
        csv_path = os.path.join(DOWNLOADS_DIR, csv_filename)
        if not os.path.isfile(csv_path):
            print(f"\nSKIP: {csv_filename} not found")
            continue

        version_id = get_version_id_for_date(effective_date)
        if not version_id:
            print(f"\nSKIP: No rate_version for {effective_date}")
            continue

        print(f"\n--- {csv_filename} -> version {version_id} ({effective_date}) ---")

        # Extract county rates from CSV
        county_records = extract_county_rates_from_csv(csv_path)
        print(f"  Found {len(county_records)} county rate records in CSV")

        # Check existing
        existing = get_existing_county_rates(version_id, county_jids)
        print(f"  Existing county rates in version: {len(existing)}")

        # Build insert batch
        rates_to_insert = []
        skipped = 0
        missing = 0

        for r in county_records:
            jid = county_map.get(r['region_code'])
            if not jid:
                missing += 1
                continue

            if (jid, r['business_code']) in existing:
                skipped += 1
                continue

            rates_to_insert.append({
                "rate_version_id": version_id,
                "jurisdiction_id": jid,
                "business_code": r['business_code'],
                "state_rate": 0.0,
                "county_rate": r['rate'],
                "city_rate": 0.0,
            })

        print(f"  To insert: {len(rates_to_insert)}")
        print(f"  Skipped (already exists): {skipped}")
        if missing:
            print(f"  Missing jurisdiction: {missing}")

        if dry_run:
            print("  [DRY RUN] Would insert above")
            if rates_to_insert:
                sample = rates_to_insert[0]
                print(f"  Sample: jid={sample['jurisdiction_id']} biz={sample['business_code']} county_rate={sample['county_rate']}")
            continue

        # Insert in batches
        inserted = 0
        if rates_to_insert:
            batch_size = 500
            for i in range(0, len(rates_to_insert), batch_size):
                batch = rates_to_insert[i:i + batch_size]
                try:
                    supabase.table('rates').insert(batch).execute()
                    inserted += len(batch)
                except Exception as e:
                    print(f"  ERROR inserting batch: {e}")

        print(f"  Inserted: {inserted}")
        total_inserted += inserted

    print(f"\n{'=' * 60}")
    print(f"Total inserted: {total_inserted}")

    # Verify
    print(f"\nVerification - county rate coverage on new IDs:")
    for csv_filename, effective_date in CSV_FILES:
        version_id = get_version_id_for_date(effective_date)
        if not version_id:
            continue
        count = supabase.table('rates').select('id', count='exact').eq(
            'rate_version_id', version_id
        ).in_('jurisdiction_id', county_jids).execute()
        print(f"  {effective_date} (v{version_id}): {count.count} county rates")

    print(f"\n{'=' * 60}")
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    backfill_county_rates(dry_run=dry_run)
