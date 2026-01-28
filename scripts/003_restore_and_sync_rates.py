"""
Comprehensive Rates Restoration and Sync Script

This script:
1. Restores rates from the Jan 26 backup
2. Merges historical rates from AZTaxesRpt CSV (1990-2024)
3. Syncs latest ADOR CSVs (2025-2026)
4. Ensures all jurisdictions, business codes, and effective dates are covered

Usage:
    python restore_and_sync_rates.py

Options:
    --skip-backup    Skip backup restoration (use existing data)
    --skip-historical Skip historical CSV merge
    --skip-ador      Skip ADOR CSV sync
    --verify-only    Only run verification, no modifications
"""

import csv
import os
import re
import sys
import argparse
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Set, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Default paths
BACKUP_PATH = r"C:\Users\noson\Downloads\backup_jan26.sql"
DOWNLOADS_DIR = r"C:\Users\noson\Downloads"

# Historical CSVs - both will be processed (2025 file is more comprehensive)
HISTORICAL_CSVS = [
    r"C:\Users\noson\Downloads\AZTaxesRpt - SpRates (1) (2).csv",  # Through Oct 2024
    r"C:\Users\noson\Downloads\AZTaxesRpt - SpRates.csv",          # Through Nov 2025
]


def parse_backup_sql(backup_path: str) -> Tuple[List[Dict], List[Dict]]:
    """Parse the backup SQL file to extract rate_versions and rates data."""
    print(f"\n[1] Parsing backup file: {backup_path}")

    with open(backup_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract rate_versions
    rv_match = re.search(r'COPY public\.rate_versions.*?FROM stdin;\n(.*?)\n\\\.', content, re.DOTALL)
    rate_versions = []
    if rv_match:
        for line in rv_match.group(1).strip().split('\n'):
            if line.strip():
                parts = line.split('\t')
                rate_versions.append({
                    'id': int(parts[0]),
                    'effective_date': parts[1],
                    'loaded_at': parts[2] if len(parts) > 2 else None
                })

    # Extract rates
    rates_match = re.search(r'COPY public\.rates.*?FROM stdin;\n(.*?)\n\\\.', content, re.DOTALL)
    rates = []
    if rates_match:
        for line in rates_match.group(1).strip().split('\n'):
            if line.strip():
                parts = line.split('\t')
                rates.append({
                    'id': int(parts[0]),
                    'rate_version_id': int(parts[1]),
                    'business_code': parts[2],
                    'jurisdiction_id': int(parts[3]),
                    'state_rate': float(parts[4]),
                    'county_rate': float(parts[5]),
                    'city_rate': float(parts[6])
                })

    print(f"    Found {len(rate_versions)} rate_versions, {len(rates)} rates")
    return rate_versions, rates


def parse_historical_csv(csv_path: str) -> List[Dict]:
    """Parse the AZTaxesRpt historical CSV."""
    print(f"\n    Parsing: {os.path.basename(csv_path)}")

    records = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Parse date - handle different formats
                date_str = row.get('RateStartDate', '').strip()
                if not date_str:
                    continue

                # Try different date formats
                start_date = None
                for fmt in ['%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y %H:%M', '%m/%d/%Y']:
                    try:
                        start_date = datetime.strptime(date_str.split()[0] if ' ' not in fmt else date_str, fmt)
                        break
                    except:
                        continue

                if not start_date:
                    # Last resort: extract just the date part
                    try:
                        parts = date_str.split()[0].split('/')
                        start_date = datetime(int(parts[2]), int(parts[0]), int(parts[1]))
                    except:
                        continue

                # Parse rate
                rate_str = row.get('TaxRate', '0').strip()
                rate = float(rate_str.replace('%', ''))
                if rate > 1:
                    rate = rate / 100.0

                records.append({
                    'region_code': row.get('RegionCode', '').strip(),
                    'region_name': row.get('RegionName', '').strip(),
                    'business_code': row.get('BusinessCode', '').strip(),
                    'business_name': row.get('BusinessCodesName', '').strip(),
                    'rate': rate,
                    'effective_date': start_date.strftime('%Y-%m-%d')
                })
            except Exception as e:
                continue

    # Get unique dates
    unique_dates = set(r['effective_date'] for r in records)
    unique_regions = set(r['region_code'] for r in records)
    unique_codes = set(r['business_code'] for r in records)

    print(f"    Found {len(records)} records")
    print(f"    {len(unique_dates)} effective dates: {min(unique_dates)} to {max(unique_dates)}")
    print(f"    {len(unique_regions)} regions, {len(unique_codes)} business codes")

    return records


def build_jurisdiction_cache() -> Dict[str, int]:
    """Build cache of region_code -> jurisdiction_id."""
    print("\n[3] Building jurisdiction cache...")

    result = supabase.table("jurisdictions").select("id, city_code, region_code").execute()

    cache = {}
    for j in result.data:
        if j.get("city_code"):
            cache[j["city_code"]] = j["id"]
        if j.get("region_code"):
            cache[j["region_code"]] = j["id"]

    print(f"    Cached {len(cache)} jurisdiction mappings")
    return cache


def get_current_state() -> Dict:
    """Get current database state."""
    versions = supabase.table('rate_versions').select('id, effective_date').execute()
    rates_count = supabase.table('rates').select('id', count='exact').execute()

    return {
        'rate_versions': len(versions.data),
        'rates': rates_count.count,
        'version_ids': [v['id'] for v in versions.data],
        'max_version_id': max(v['id'] for v in versions.data) if versions.data else 0
    }


def truncate_and_restore_backup(rate_versions: List[Dict], rates: List[Dict]):
    """Truncate tables and restore from backup."""
    print("\n[4] Truncating and restoring from backup...")

    # Truncate in correct order (rates first due to FK)
    print("    Truncating rates...")
    supabase.table('rates').delete().neq('id', -99999).execute()

    print("    Truncating rate_versions...")
    supabase.table('rate_versions').delete().neq('id', -99999).execute()

    # Insert rate_versions
    print(f"    Inserting {len(rate_versions)} rate_versions...")
    for rv in rate_versions:
        supabase.table('rate_versions').insert({
            'id': rv['id'],
            'effective_date': rv['effective_date']
        }).execute()

    # Insert rates in batches
    print(f"    Inserting {len(rates)} rates...")
    batch_size = 500
    for i in range(0, len(rates), batch_size):
        batch = rates[i:i+batch_size]
        supabase.table('rates').insert(batch).execute()
        if (i + batch_size) % 2000 == 0:
            print(f"      Inserted {min(i + batch_size, len(rates))}/{len(rates)}")

    print("    Backup restored!")


def get_or_create_rate_version(effective_date: str, next_id: int) -> Tuple[int, int]:
    """Get existing rate_version or create new one. Returns (version_id, next_id)."""
    existing = supabase.table("rate_versions").select("id").eq("effective_date", effective_date).execute()

    if existing.data:
        return existing.data[0]["id"], next_id

    # Create new version
    supabase.table("rate_versions").insert({
        "id": next_id,
        "effective_date": effective_date
    }).execute()

    return next_id, next_id + 1


def ensure_jurisdiction_exists(region_code: str, region_name: str, cache: Dict[str, int]) -> int:
    """Ensure jurisdiction exists, create if needed. Returns jurisdiction_id."""
    if region_code in cache:
        return cache[region_code]

    # Get max ID
    max_id_result = supabase.table('jurisdictions').select('id').order('id', desc=True).limit(1).execute()
    new_id = (max_id_result.data[0]['id'] + 1) if max_id_result.data else 1

    # Insert new jurisdiction
    supabase.table('jurisdictions').insert({
        'id': new_id,
        'level': 'city',
        'state_code': 'AZ',
        'city_code': region_code,
        'city_name': region_name or f"{region_code} City"
    }).execute()

    cache[region_code] = new_id
    print(f"      Created jurisdiction: {region_code} ({region_name}) -> ID {new_id}")
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


def merge_historical_rates(historical_records: List[Dict], jurisdiction_cache: Dict[str, int], start_version_id: int):
    """Merge historical rates into the database using batch operations."""
    print(f"\n    Merging {len(historical_records)} historical rates (starting version ID: {start_version_id})...")

    # Ensure all business codes exist first
    print("    Ensuring business codes exist...")
    codes = {(r['business_code'], r.get('business_name', '')) for r in historical_records}
    for code, name in codes:
        ensure_business_code_exists(code, name)
    print(f"    Processed {len(codes)} business codes")

    # Group records by effective_date
    by_date = defaultdict(list)
    for r in historical_records:
        by_date[r['effective_date']].append(r)

    sorted_dates = sorted(by_date.keys())
    print(f"    Processing {len(sorted_dates)} effective dates...")

    next_id = start_version_id
    stats = {'versions_created': 0, 'rates_inserted': 0, 'skipped': 0}

    for i, effective_date in enumerate(sorted_dates):
        records = by_date[effective_date]

        # Get or create rate version
        version_id, next_id = get_or_create_rate_version(effective_date, next_id)
        if next_id > version_id:
            stats['versions_created'] += 1

        # Get existing rates for this version to avoid duplicates
        existing_rates = supabase.table("rates").select("jurisdiction_id, business_code").eq(
            "rate_version_id", version_id
        ).execute()
        existing_keys = {(r['jurisdiction_id'], r['business_code']) for r in existing_rates.data}

        # Build batch of new rates
        rates_to_insert = []
        for r in records:
            jurisdiction_id = jurisdiction_cache.get(r['region_code'])
            if not jurisdiction_id:
                jurisdiction_id = ensure_jurisdiction_exists(r['region_code'], r.get('region_name', ''), jurisdiction_cache)

            if not jurisdiction_id:
                stats['skipped'] += 1
                continue

            # Skip if already exists
            if (jurisdiction_id, r['business_code']) in existing_keys:
                continue

            rates_to_insert.append({
                "rate_version_id": version_id,
                "jurisdiction_id": jurisdiction_id,
                "business_code": r['business_code'],
                "state_rate": 0.0,
                "county_rate": 0.0,
                "city_rate": r['rate']
            })

        # Batch insert
        if rates_to_insert:
            batch_size = 500
            for j in range(0, len(rates_to_insert), batch_size):
                batch = rates_to_insert[j:j+batch_size]
                try:
                    supabase.table('rates').insert(batch).execute()
                    stats['rates_inserted'] += len(batch)
                except Exception as e:
                    print(f"      Error inserting batch: {e}")
                    # Try individual inserts as fallback
                    for rate in batch:
                        try:
                            supabase.table('rates').insert(rate).execute()
                            stats['rates_inserted'] += 1
                        except:
                            pass

        # Progress update every 10 dates
        if (i + 1) % 10 == 0:
            print(f"      Processed {i + 1}/{len(sorted_dates)} dates, {stats['rates_inserted']} rates inserted")

    print(f"    Versions created: {stats['versions_created']}")
    print(f"    Rates inserted: {stats['rates_inserted']}")
    print(f"    Skipped (no jurisdiction): {stats['skipped']}")

    return next_id


def sync_ador_csvs(csv_dir: str, jurisdiction_cache: Dict[str, int], start_version_id: int):
    """Sync ADOR CSV files for 2025-2026 data."""
    print(f"\n[6] Syncing TPT_RATETABLE CSVs (starting version ID: {start_version_id})...")

    # Find all TPT_RATETABLE CSV files
    csv_files = []
    for f in os.listdir(csv_dir):
        if f.startswith('TPT_RATETABLE_ALL_') and f.endswith('.csv'):
            # Parse date from filename
            match = re.search(r'(\d{8})', f)
            if match:
                date_str = match.group(1)
                month = int(date_str[:2])
                day = int(date_str[2:4])
                year = int(date_str[4:])
                effective_date = f"{year}-{month:02d}-{day:02d}"
                csv_files.append((effective_date, os.path.join(csv_dir, f)))

    # Sort by date and remove duplicates (keep first occurrence)
    csv_files.sort()
    seen_dates = set()
    unique_files = []
    for date, path in csv_files:
        if date not in seen_dates:
            seen_dates.add(date)
            unique_files.append((date, path))

    print(f"    Found {len(unique_files)} unique ADOR CSVs")
    for date, path in unique_files:
        print(f"      {date}: {os.path.basename(path)}")

    next_id = start_version_id
    total_stats = {'versions_created': 0, 'rates_inserted': 0}

    for effective_date, csv_path in unique_files:
        print(f"\n    Processing {effective_date}...")

        # Parse CSV
        records = []
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    region_code = row.get('RegionCode', row.get('\ufeffRegionCode', '')).strip()
                    business_code = row.get('BusinessCode', '').strip()
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
                except:
                    continue

        print(f"      Parsed {len(records)} records")

        # Get or create rate version
        version_id, next_id = get_or_create_rate_version(effective_date, next_id)
        if next_id > version_id:
            total_stats['versions_created'] += 1

        # Get existing rates for this version
        existing_rates = supabase.table("rates").select("jurisdiction_id, business_code").eq(
            "rate_version_id", version_id
        ).execute()
        existing_keys = {(r['jurisdiction_id'], r['business_code']) for r in existing_rates.data}

        # Build batch of new rates
        rates_to_insert = []
        for r in records:
            jurisdiction_id = jurisdiction_cache.get(r['region_code'])
            if not jurisdiction_id:
                continue

            if (jurisdiction_id, r['business_code']) in existing_keys:
                continue

            rates_to_insert.append({
                "rate_version_id": version_id,
                "jurisdiction_id": jurisdiction_id,
                "business_code": r['business_code'],
                "state_rate": 0.0,
                "county_rate": 0.0,
                "city_rate": r['rate']
            })

        # Batch insert
        inserted = 0
        if rates_to_insert:
            batch_size = 500
            for j in range(0, len(rates_to_insert), batch_size):
                batch = rates_to_insert[j:j+batch_size]
                try:
                    supabase.table('rates').insert(batch).execute()
                    inserted += len(batch)
                except Exception as e:
                    print(f"      Error: {e}")

        print(f"      Inserted: {inserted} (skipped {len(existing_keys)} existing)")
        total_stats['rates_inserted'] += inserted

    print(f"\n    ADOR sync complete:")
    print(f"      Versions created: {total_stats['versions_created']}")
    print(f"      Total rates inserted: {total_stats['rates_inserted']}")


def verify_coverage():
    """Verify final coverage."""
    print("\n[7] Verifying coverage...")

    # Rate versions
    versions = supabase.table('rate_versions').select('id, effective_date').order('effective_date').execute()
    print(f"\n    Rate versions: {len(versions.data)}")
    if versions.data:
        print(f"      Date range: {versions.data[0]['effective_date']} to {versions.data[-1]['effective_date']}")
        print(f"      ID range: {versions.data[0]['id']} to {versions.data[-1]['id']}")

    # Rates
    rates = supabase.table('rates').select('jurisdiction_id, business_code', count='exact').execute()
    jurisdictions = set(r['jurisdiction_id'] for r in rates.data)
    business_codes = set(r['business_code'] for r in rates.data)

    total_jur = supabase.table('jurisdictions').select('id', count='exact').execute()
    total_codes = supabase.table('business_class_codes').select('code', count='exact').execute()

    print(f"\n    Rates: {rates.count}")
    print(f"    Jurisdictions with rates: {len(jurisdictions)}/{total_jur.count}")
    print(f"    Business codes with rates: {len(business_codes)}/{total_codes.count}")

    # Check specific test jurisdictions
    print("\n    Test jurisdiction rates (011 - Restaurants):")
    test_jurs = [
        ('TU', 'TUCSON'),
        ('ME', 'MESA'),
        ('YM', 'YUMA'),
        ('SE', 'SEDONA'),
        ('PX', 'PHOENIX')
    ]

    for city_code, name in test_jurs:
        # Get jurisdiction ID
        j_result = supabase.table('jurisdictions').select('id').eq('city_code', city_code).execute()
        if not j_result.data:
            print(f"      {name}: JURISDICTION NOT FOUND")
            continue

        jur_id = j_result.data[0]['id']
        rate = supabase.table('rates').select('city_rate, rate_version_id').eq(
            'jurisdiction_id', jur_id
        ).eq('business_code', '011').order('rate_version_id', desc=True).limit(1).execute()

        if rate.data:
            pct = rate.data[0]['city_rate'] * 100
            print(f"      {name} ({city_code}): {pct:.2f}%")
        else:
            print(f"      {name} ({city_code}): NO RATE FOUND")


def main():
    parser = argparse.ArgumentParser(description="Restore and sync tax rates")
    parser.add_argument('--skip-backup', action='store_true', help='Skip backup restoration')
    parser.add_argument('--skip-historical', action='store_true', help='Skip historical CSV merge')
    parser.add_argument('--skip-ador', action='store_true', help='Skip ADOR CSV sync')
    parser.add_argument('--verify-only', action='store_true', help='Only run verification')
    parser.add_argument('--backup-path', default=BACKUP_PATH, help='Path to backup SQL file')
    parser.add_argument('--historical-csvs', nargs='*', default=HISTORICAL_CSVS, help='Paths to historical rates CSVs')
    parser.add_argument('--downloads-dir', default=DOWNLOADS_DIR, help='Directory with ADOR CSVs')

    args = parser.parse_args()

    print("="*60)
    print("COMPREHENSIVE RATES RESTORATION AND SYNC")
    print("="*60)

    if args.verify_only:
        verify_coverage()
        return

    # Get current state
    print("\nCurrent database state:")
    state = get_current_state()
    print(f"  Rate versions: {state['rate_versions']}")
    print(f"  Rates: {state['rates']}")

    # Build jurisdiction cache
    jurisdiction_cache = build_jurisdiction_cache()

    next_version_id = state['max_version_id'] + 1

    if not args.skip_backup:
        # Check backup file exists
        if not os.path.exists(args.backup_path):
            print(f"\nERROR: Backup file not found: {args.backup_path}")
            print("Please extract the backup first or use --skip-backup")
            return

        # Parse backup
        rate_versions, rates = parse_backup_sql(args.backup_path)

        # Restore backup
        truncate_and_restore_backup(rate_versions, rates)

        # Get max version ID from backup
        max_backup_version = max(rv['id'] for rv in rate_versions)
        next_version_id = max_backup_version + 1

        # Rebuild jurisdiction cache after restore
        jurisdiction_cache = build_jurisdiction_cache()

    if not args.skip_historical:
        # Process all historical CSVs
        print(f"\n[5] Processing historical CSVs...")
        all_historical_records = []
        for csv_path in args.historical_csvs:
            if os.path.exists(csv_path):
                records = parse_historical_csv(csv_path)
                all_historical_records.extend(records)
            else:
                print(f"\nWARNING: Historical CSV not found: {csv_path}")

        if all_historical_records:
            # Deduplicate by (effective_date, region_code, business_code) - keep latest value
            seen = {}
            for r in all_historical_records:
                key = (r['effective_date'], r['region_code'], r['business_code'])
                seen[key] = r  # Later entries overwrite earlier (2025 file wins)

            unique_records = list(seen.values())
            print(f"\n    Combined: {len(all_historical_records)} records -> {len(unique_records)} unique")

            # Merge historical rates
            next_version_id = merge_historical_rates(unique_records, jurisdiction_cache, next_version_id)
        else:
            print("\nWARNING: No historical CSVs found. Skipping historical merge...")

    if not args.skip_ador:
        # Check downloads dir exists
        if not os.path.isdir(args.downloads_dir):
            print(f"\nWARNING: Downloads directory not found: {args.downloads_dir}")
            print("Skipping ADOR sync...")
        else:
            # Sync ADOR CSVs
            sync_ador_csvs(args.downloads_dir, jurisdiction_cache, next_version_id)

    # Verify
    verify_coverage()

    print("\n" + "="*60)
    print("RESTORATION AND SYNC COMPLETE!")
    print("="*60)


if __name__ == "__main__":
    main()
