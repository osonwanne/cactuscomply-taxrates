"""
Add Monthly Tax Rates from ADOR CSV

Simple script to add new monthly rates from a single ADOR TPT_RATETABLE CSV.
Use this for adding new months (March 2026 onwards).

Usage:
    python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv
    python scripts/004_add_monthly_rates.py "C:/Users/noson/Downloads/TPT_RATETABLE_ALL_03012026.csv"

The effective date is parsed from the filename (MMDDYYYY format).
"""

import csv
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DOWNLOADS_DIR = r"C:\Users\noson\Downloads"


def parse_date_from_filename(filename: str) -> str:
    """Extract effective date from filename like TPT_RATETABLE_ALL_03012026.csv"""
    match = re.search(r'(\d{8})', filename)
    if not match:
        raise ValueError(f"Cannot parse date from filename: {filename}")

    date_str = match.group(1)
    month = int(date_str[:2])
    day = int(date_str[2:4])
    year = int(date_str[4:])
    return f"{year}-{month:02d}-{day:02d}"


def build_jurisdiction_cache() -> Dict[str, Tuple[int, str]]:
    """Build cache of city_code/region_code -> (jurisdiction_id, level)."""
    result = supabase.table("jurisdictions").select("id, city_code, region_code, level").execute()

    cache = {}
    for j in result.data:
        level = j.get("level", "city")  # Default to city if not specified
        if j.get("city_code"):
            cache[j["city_code"]] = (j["id"], level)
        if j.get("region_code"):
            cache[j["region_code"]] = (j["id"], level)

    return cache


def get_or_create_rate_version(effective_date: str) -> int:
    """Get existing rate_version or create new one."""
    existing = supabase.table("rate_versions").select("id").eq("effective_date", effective_date).execute()

    if existing.data:
        return existing.data[0]["id"]

    # Get max ID
    max_id_result = supabase.table("rate_versions").select("id").order("id", desc=True).limit(1).execute()
    new_id = (max_id_result.data[0]["id"] + 1) if max_id_result.data else 1

    # Create new version
    supabase.table("rate_versions").insert({
        "id": new_id,
        "effective_date": effective_date
    }).execute()

    print(f"Created rate_version {new_id} for {effective_date}")
    return new_id


def ensure_business_code_exists(code: str, name: str):
    """Ensure business code exists."""
    try:
        supabase.table('business_class_codes').upsert({
            'code': code,
            'description': name or f'Business Code {code}'
        }).execute()
    except:
        pass


def add_rates_from_csv(csv_path: str, effective_date: str):
    """Add rates from a single CSV file."""
    print(f"\nProcessing: {os.path.basename(csv_path)}")
    print(f"Effective date: {effective_date}")

    # Build jurisdiction cache
    jurisdiction_cache = build_jurisdiction_cache()
    print(f"Loaded {len(jurisdiction_cache)} jurisdictions")

    # Parse CSV
    records = []
    business_codes = set()
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                region_code = row.get('RegionCode', row.get('\ufeffRegionCode', '')).strip()
                business_code = row.get('BusinessCode', '').strip()
                business_name = row.get('BusinessCodesName', '').strip()
                tax_rate = row.get('TaxRate', '0').strip()

                rate = float(tax_rate.replace('%', ''))
                if rate > 1:
                    rate = rate / 100.0

                if region_code and business_code:
                    records.append({
                        'region_code': region_code,
                        'business_code': business_code,
                        'rate': rate
                    })
                    business_codes.add((business_code, business_name))
            except:
                continue

    print(f"Parsed {len(records)} records, {len(business_codes)} business codes")

    # Ensure business codes exist
    for code, name in business_codes:
        ensure_business_code_exists(code, name)

    # Get or create rate version
    version_id = get_or_create_rate_version(effective_date)

    # Get existing rates for this version to avoid duplicates
    existing = supabase.table("rates").select("jurisdiction_id, business_code").eq(
        "rate_version_id", version_id
    ).execute()
    existing_keys = {(r['jurisdiction_id'], r['business_code']) for r in existing.data}
    print(f"Found {len(existing_keys)} existing rates for this version")

    # Build batch of new rates
    rates_to_insert = []
    skipped = 0
    missing_jurisdiction = 0

    for r in records:
        lookup = jurisdiction_cache.get(r['region_code'])
        if not lookup:
            missing_jurisdiction += 1
            continue

        jurisdiction_id, jurisdiction_level = lookup

        if (jurisdiction_id, r['business_code']) in existing_keys:
            skipped += 1
            continue

        # Put rate in correct column based on jurisdiction level
        # Counties: rate goes in county_rate column
        # Cities: rate goes in city_rate column
        if jurisdiction_level == 'county':
            county_rate = r['rate']
            city_rate = 0.0
        else:  # city level
            county_rate = 0.0
            city_rate = r['rate']

        rates_to_insert.append({
            "rate_version_id": version_id,
            "jurisdiction_id": jurisdiction_id,
            "business_code": r['business_code'],
            "state_rate": 0.0,
            "county_rate": county_rate,
            "city_rate": city_rate
        })

    # Batch insert
    inserted = 0
    if rates_to_insert:
        batch_size = 500
        for i in range(0, len(rates_to_insert), batch_size):
            batch = rates_to_insert[i:i+batch_size]
            try:
                supabase.table('rates').insert(batch).execute()
                inserted += len(batch)
            except Exception as e:
                print(f"Error inserting batch: {e}")

    print(f"\nResults:")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"  Skipped (missing jurisdiction): {missing_jurisdiction}")

    return inserted


def verify_rates():
    """Show current rate coverage."""
    versions = supabase.table('rate_versions').select('id, effective_date').order('effective_date', desc=True).limit(5).execute()
    rates_count = supabase.table('rates').select('id', count='exact').execute()

    print(f"\nCurrent state:")
    print(f"  Total rates: {rates_count.count}")
    print(f"  Recent rate versions:")
    for v in versions.data:
        count = supabase.table('rates').select('id', count='exact').eq('rate_version_id', v['id']).execute()
        print(f"    {v['effective_date']}: {count.count} rates (version {v['id']})")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/004_add_monthly_rates.py <csv_file>")
        print("\nExamples:")
        print("  python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv")
        print("  python scripts/004_add_monthly_rates.py C:/Users/noson/Downloads/TPT_RATETABLE_ALL_03012026.csv")
        print("\nThe effective date is parsed from the filename (MMDDYYYY format).")
        return

    csv_input = sys.argv[1]

    # Check if it's just a filename (look in Downloads) or full path
    if os.path.isfile(csv_input):
        csv_path = csv_input
    elif os.path.isfile(os.path.join(DOWNLOADS_DIR, csv_input)):
        csv_path = os.path.join(DOWNLOADS_DIR, csv_input)
    else:
        print(f"ERROR: File not found: {csv_input}")
        print(f"Also checked: {os.path.join(DOWNLOADS_DIR, csv_input)}")
        return

    # Parse effective date from filename
    try:
        effective_date = parse_date_from_filename(os.path.basename(csv_path))
    except ValueError as e:
        print(f"ERROR: {e}")
        return

    print("="*60)
    print("ADD MONTHLY TAX RATES")
    print("="*60)

    # Show current state
    verify_rates()

    # Add rates
    add_rates_from_csv(csv_path, effective_date)

    # Show final state
    print("\n" + "="*60)
    verify_rates()

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)


if __name__ == "__main__":
    main()
