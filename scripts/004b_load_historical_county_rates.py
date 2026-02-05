"""
Load Historical County and City Rates from ADOR CSV

Loads rates from AZTaxesRpt - SpRates CSV which contains historical rates
with RateStartDate and RateEndDate columns. Creates rate_versions for each
unique effective date and properly maps rates to county_rate or city_rate
columns based on jurisdiction level.

Usage:
    python scripts/004b_load_historical_county_rates.py "C:/Users/noson/Downloads/AZTaxesRpt - SpRates (2).csv"
    python scripts/004b_load_historical_county_rates.py --verify  # Just verify coverage

Based on migration 020: County rates go in county_rate column, city rates in city_rate column.
"""

import csv
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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


def parse_rate(rate_str: str) -> float:
    """Parse rate string to decimal with 6 decimal precision."""
    if not rate_str:
        return 0.0

    rate_str = str(rate_str).strip().replace("%", "")
    try:
        rate = float(rate_str)
        # If rate > 1, assume it's a percentage (e.g., 5.6% = 5.6)
        if rate > 1:
            rate = rate / 100.0
        return round(rate, 6)
    except ValueError:
        print(f"WARNING: Could not parse rate: '{rate_str}', using 0.0")
        return 0.0


def parse_date(date_str: str) -> Optional[str]:
    """Parse date string to ISO format (YYYY-MM-DD)."""
    if not date_str:
        return None

    date_str = str(date_str).strip()
    try:
        # Handle ADOR date format: "1/01/2021 0:00" or "1/01/2021 12:00:00 AM"
        if " 0:00" in date_str:
            date_str = date_str.replace(" 0:00", "")
        if " 12:00:00 AM" in date_str:
            date_str = date_str.replace(" 12:00:00 AM", "")

        # Try various date formats
        for fmt in [
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%m-%d-%Y",
            "%Y/%m/%d",
        ]:
            try:
                parsed_date = datetime.strptime(date_str, fmt).date()
                return parsed_date.isoformat()
            except ValueError:
                continue

        print(f"WARNING: Could not parse date: '{date_str}'")
        return None
    except Exception as e:
        print(f"WARNING: Error parsing date '{date_str}': {e}")
        return None


def build_jurisdiction_cache() -> Dict[str, Tuple[int, str, str]]:
    """
    Build cache of city_code/region_code -> (jurisdiction_id, level, name).

    Returns:
        Dict mapping region codes to (id, level, display_name)
    """
    result = supabase.table("jurisdictions").select(
        "id, city_code, region_code, level, city_name, county_name"
    ).execute()

    cache = {}
    for j in result.data:
        level = j.get("level", "city")
        # Determine display name
        if level == "county":
            display_name = j.get("county_name", "")
        else:
            display_name = j.get("city_name", "")

        # Cache by city_code (for cities)
        if j.get("city_code"):
            cache[j["city_code"]] = (j["id"], level, display_name)

        # Cache by region_code (for counties)
        if j.get("region_code"):
            cache[j["region_code"]] = (j["id"], level, display_name)

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

    print(f"  Created rate_version {new_id} for {effective_date}")
    return new_id


def ensure_business_code_exists(code: str, name: str):
    """Ensure business code exists."""
    try:
        supabase.table('business_class_codes').upsert({
            'code': code,
            'description': name or f'Business Code {code}'
        }).execute()
    except Exception as e:
        print(f"WARNING: Could not upsert business code {code}: {e}")


def load_rates_from_csv(csv_path: str, verify_only: bool = False):
    """Load rates from CSV, grouping by effective date."""
    print(f"\nProcessing: {os.path.basename(csv_path)}")

    # Build jurisdiction cache
    jurisdiction_cache = build_jurisdiction_cache()
    print(f"Loaded {len(jurisdiction_cache)} jurisdictions from database")

    # Parse CSV and group by effective date
    records_by_date = defaultdict(list)
    business_codes = set()
    parse_errors = 0
    skipped_future = 0

    print("\nParsing CSV...")
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                region_code = row.get('RegionCode', row.get('\ufeffRegionCode', '')).strip()
                business_code = row.get('BusinessCode', '').strip()
                business_name = row.get('BusinessCodesName', '').strip()
                tax_rate = row.get('TaxRate', '0').strip()
                rate_start = row.get('RateStartDate', '').strip()

                # Parse rate
                rate = parse_rate(tax_rate)

                # Parse effective date
                effective_date = parse_date(rate_start)

                # Skip if no effective date or rate is 0
                if not effective_date:
                    parse_errors += 1
                    continue

                # Skip future dates (after 2026-02-04)
                if effective_date > "2026-02-04":
                    skipped_future += 1
                    continue

                if region_code and business_code and rate > 0:
                    records_by_date[effective_date].append({
                        'region_code': region_code,
                        'business_code': business_code,
                        'rate': rate
                    })
                    business_codes.add((business_code, business_name))

            except Exception as e:
                parse_errors += 1
                if parse_errors <= 5:  # Only show first 5 errors
                    print(f"WARNING: Error parsing row {row_num}: {e}")
                continue

    print(f"\nParsed {sum(len(recs) for recs in records_by_date.values())} total records")
    print(f"Found {len(records_by_date)} unique effective dates")
    print(f"Found {len(business_codes)} unique business codes")
    if parse_errors > 0:
        print(f"WARNING: {parse_errors} rows had parse errors and were skipped")
    if skipped_future > 0:
        print(f"Skipped {skipped_future} future-dated records")

    # Show date range
    sorted_dates = sorted(records_by_date.keys())
    if sorted_dates:
        print(f"\nDate range: {sorted_dates[0]} to {sorted_dates[-1]}")
        print(f"\nTop 10 dates by record count:")
        date_counts = [(date, len(records_by_date[date])) for date in sorted_dates]
        date_counts.sort(key=lambda x: x[1], reverse=True)
        for date, count in date_counts[:10]:
            print(f"  {date}: {count} rates")

    if verify_only:
        print("\n[VERIFY ONLY MODE - No data will be loaded]")
        return

    # Ensure business codes exist
    print(f"\nUpserting {len(business_codes)} business codes...")
    for code, name in business_codes:
        ensure_business_code_exists(code, name)

    # Process each effective date
    print(f"\nLoading rates for {len(records_by_date)} effective dates...")
    total_inserted = 0
    total_skipped = 0

    for effective_date in sorted(records_by_date.keys()):
        records = records_by_date[effective_date]
        print(f"\n{'='*60}")
        print(f"Effective Date: {effective_date} ({len(records)} rates)")
        print(f"{'='*60}")

        # Get or create rate version
        version_id = get_or_create_rate_version(effective_date)

        # Get existing rates for this version to avoid duplicates
        existing = supabase.table("rates").select("jurisdiction_id, business_code").eq(
            "rate_version_id", version_id
        ).execute()
        existing_keys = {(r['jurisdiction_id'], r['business_code']) for r in existing.data}

        # Build batch of new rates
        rates_to_insert = []
        skipped = 0
        missing_jurisdiction = 0
        missing_jurisdiction_codes = set()

        for r in records:
            lookup = jurisdiction_cache.get(r['region_code'])
            if not lookup:
                missing_jurisdiction += 1
                missing_jurisdiction_codes.add(r['region_code'])
                continue

            jurisdiction_id, jurisdiction_level, display_name = lookup

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
                    print(f"  ERROR: Failed to insert batch {i//batch_size + 1}: {e}")

        print(f"  Results: Inserted={inserted}, Skipped={skipped}, Missing={missing_jurisdiction}")
        if missing_jurisdiction_codes:
            print(f"    Missing codes: {', '.join(sorted(missing_jurisdiction_codes))}")

        total_inserted += inserted
        total_skipped += skipped

    print(f"\n{'='*60}")
    print(f"OVERALL RESULTS")
    print(f"{'='*60}")
    print(f"Total inserted: {total_inserted}")
    print(f"Total skipped: {total_skipped}")


def verify_county_coverage():
    """Verify that all 15 Arizona counties have rates."""
    print("\n" + "="*60)
    print("VERIFYING COUNTY COVERAGE")
    print("="*60)

    # Get all counties from jurisdictions table
    counties = supabase.table("jurisdictions").select(
        "id, county_name, region_code"
    ).eq("level", "county").execute()

    print(f"\nFound {len(counties.data)} counties in jurisdictions table:")

    # Check each county for rates
    counties_without_rates = []

    for county in counties.data:
        county_id = county['id']
        county_name = county.get('county_name', 'Unknown')
        region_code = county.get('region_code', '')

        # Get count of rates for this county
        rates = supabase.table("rates").select(
            "id", count='exact'
        ).eq("jurisdiction_id", county_id).execute()

        rate_count = rates.count or 0

        if rate_count == 0:
            counties_without_rates.append((county_name, region_code))
            print(f"  [NO RATES] {county_name} ({region_code})")
        else:
            # Get sample rate
            sample = supabase.table("rates").select(
                "business_code, county_rate, city_rate"
            ).eq("jurisdiction_id", county_id).limit(1).execute()

            if sample.data:
                sample_rate = sample.data[0]
                print(f"  [OK] {county_name} ({region_code}): {rate_count} rates "
                      f"(e.g., business {sample_rate['business_code']}: "
                      f"county={sample_rate['county_rate']}, city={sample_rate['city_rate']})")
            else:
                print(f"  [OK] {county_name} ({region_code}): {rate_count} rates")

    print(f"\n{'='*60}")
    if counties_without_rates:
        print(f"WARNING: {len(counties_without_rates)} counties WITHOUT rates:")
        for name, code in counties_without_rates:
            print(f"   - {name} ({code})")
    else:
        print("SUCCESS: ALL COUNTIES HAVE RATES!")
    print("="*60)

    return len(counties_without_rates) == 0


def main():
    verify_only = False
    csv_path = None

    # Parse arguments
    for arg in sys.argv[1:]:
        if arg == "--verify":
            verify_only = True
        elif not csv_path:
            csv_path = arg

    # If verify flag only, skip CSV loading
    if verify_only and not csv_path:
        verify_county_coverage()
        return

    if not csv_path:
        print("Usage: python scripts/004b_load_historical_county_rates.py <csv_file>")
        print("\nExamples:")
        print('  python scripts/004b_load_historical_county_rates.py "C:/Users/noson/Downloads/AZTaxesRpt - SpRates (2).csv"')
        print('  python scripts/004b_load_historical_county_rates.py --verify')
        print("\nOptions:")
        print("  --verify    Just verify county coverage, don't load data")
        return

    # Check file exists
    if not os.path.isfile(csv_path):
        print(f"ERROR: File not found: {csv_path}")
        return

    print("="*60)
    print("LOAD HISTORICAL COUNTY AND CITY RATES")
    print("="*60)

    # Load rates
    load_rates_from_csv(csv_path, verify_only=False)

    # Verify coverage
    verify_county_coverage()

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)


if __name__ == "__main__":
    main()
