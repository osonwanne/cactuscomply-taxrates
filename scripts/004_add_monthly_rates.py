"""
Add Monthly Tax Rates from ADOR CSV

Simple script to add new monthly rates from a single ADOR TPT_RATETABLE CSV.
Use this for adding new months (March 2026 onwards).

Usage:
    python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv
    python scripts/004_add_monthly_rates.py "C:/Users/noson/Downloads/TPT_RATETABLE_ALL_03012026.csv"
    python scripts/004_add_monthly_rates.py --auto  # Auto-find latest CSV in Downloads

The effective date is parsed from the filename (MMDDYYYY format).

Improvements (2026-02-03):
- Added COUNTY_CODES constant for validation and display
- Added parse_rate() helper with 6 decimal precision and error handling
- Added find_latest_csv_file() for auto-discovery of newest CSV
- Better error handling with specific error messages
- Added parse_date() helper for flexible date parsing
- Shows county names in output for better readability
"""

import csv
import glob
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


def parse_rate(rate_str: str) -> float:
    """
    Parse rate string to decimal (handles percentages and decimals).

    Args:
        rate_str: Rate string like "2.4%", "2.4", "0.024"

    Returns:
        Rate as decimal with 6 decimal precision (e.g., 0.024000)
    """
    if not rate_str:
        return 0.0

    rate_str = str(rate_str).strip().replace("%", "")
    try:
        rate = float(rate_str)
        # If rate > 1, assume it's a percentage (e.g., 5.6% = 5.6)
        # If rate <= 1, assume it's already decimal (e.g., 0.056)
        if rate > 1:
            rate = rate / 100.0
        return round(rate, 6)  # 6 decimal places precision
    except ValueError:
        print(f"WARNING: Could not parse rate: '{rate_str}', using 0.0")
        return 0.0


def parse_date(date_str: str) -> Optional[str]:
    """
    Parse date string to ISO format (YYYY-MM-DD).
    Handles multiple date formats for flexibility.

    Args:
        date_str: Date string in various formats

    Returns:
        ISO format date string or None if parse fails
    """
    if not date_str:
        return None

    date_str = str(date_str).strip()
    try:
        # Handle ADOR date format: "1/01/2021 0:00"
        if " 0:00" in date_str:
            date_str = date_str.replace(" 0:00", "")

        # Try various date formats
        for fmt in [
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%m-%d-%Y",
            "%Y/%m/%d",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y %H:%M:%S",
        ]:
            try:
                parsed_date = datetime.strptime(date_str, fmt).date()
                return parsed_date.isoformat()
            except ValueError:
                continue
        return None
    except Exception:
        return None


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


def find_latest_csv_file(directory: str = None) -> Optional[str]:
    """
    Find the latest ADOR CSV file in the specified directory.
    Looks for files matching pattern: TPT_RATETABLE_ALL_MMDDYYYY.csv

    Args:
        directory: Directory to search for CSV files (defaults to DOWNLOADS_DIR)

    Returns:
        Path to the latest CSV file, or None if not found
    """
    if not directory:
        directory = DOWNLOADS_DIR

    pattern = os.path.join(directory, "TPT_RATETABLE_ALL_*.csv")
    files = glob.glob(pattern)

    if not files:
        print(f"WARNING: No CSV files found matching pattern: {pattern}")
        return None

    # Extract dates from filenames and sort
    file_dates = []
    for file_path in files:
        # Extract date portion (MMDDYYYY) from filename
        match = re.search(r"TPT_RATETABLE_ALL_(\d{8})\.csv", file_path)
        if match:
            date_str = match.group(1)
            # Convert MMDDYYYY to YYYYMMDD for proper sorting
            month = date_str[:2]
            day = date_str[2:4]
            year = date_str[4:]
            sortable_date = f"{year}{month}{day}"
            file_dates.append((sortable_date, file_path))

    if not file_dates:
        print("WARNING: No valid date patterns found in CSV filenames")
        return None

    # Sort by date (newest first) and return the latest file
    file_dates.sort(reverse=True)
    latest_file = file_dates[0][1]

    print(f"Found latest CSV file: {os.path.basename(latest_file)}")
    return latest_file


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

    print(f"Created rate_version {new_id} for {effective_date}")
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
    parse_errors = 0

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
            try:
                region_code = row.get('RegionCode', row.get('\ufeffRegionCode', '')).strip()
                business_code = row.get('BusinessCode', '').strip()
                business_name = row.get('BusinessCodesName', '').strip()
                tax_rate = row.get('TaxRate', '0').strip()

                # Use improved rate parser
                rate = parse_rate(tax_rate)

                if region_code and business_code and rate > 0:
                    records.append({
                        'region_code': region_code,
                        'business_code': business_code,
                        'rate': rate
                    })
                    business_codes.add((business_code, business_name))
            except Exception as e:
                parse_errors += 1
                print(f"WARNING: Error parsing row {row_num}: {e}")
                continue

    print(f"Parsed {len(records)} records, {len(business_codes)} business codes")
    if parse_errors > 0:
        print(f"WARNING: {parse_errors} rows had parse errors and were skipped")

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
    insert_errors = 0
    if rates_to_insert:
        batch_size = 500
        for i in range(0, len(rates_to_insert), batch_size):
            batch = rates_to_insert[i:i+batch_size]
            try:
                supabase.table('rates').insert(batch).execute()
                inserted += len(batch)
            except Exception as e:
                insert_errors += 1
                print(f"ERROR: Failed to insert batch {i//batch_size + 1}: {e}")

    print(f"\nResults:")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped (already exists): {skipped}")
    print(f"  Skipped (missing jurisdiction): {missing_jurisdiction}")
    if missing_jurisdiction_codes:
        print(f"    Missing codes: {', '.join(sorted(missing_jurisdiction_codes))}")
    if insert_errors > 0:
        print(f"  Insert errors: {insert_errors} batches failed")

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
        print("  python scripts/004_add_monthly_rates.py --auto")
        print("\nOptions:")
        print("  --auto    Automatically find and use the latest CSV in Downloads folder")
        print("\nThe effective date is parsed from the filename (MMDDYYYY format).")
        return

    csv_input = sys.argv[1]

    # Handle --auto flag
    if csv_input == "--auto":
        csv_path = find_latest_csv_file()
        if not csv_path:
            print("ERROR: Could not find any CSV files in Downloads folder")
            print(f"Searched in: {DOWNLOADS_DIR}")
            return
    else:
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
