"""
Script to load historical tax rates with proper RateStartDate as effective_date
"""
import os
import csv
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def query_table_structure():
    """Step 1: Query current rates and rate_versions table structure"""
    print("\n" + "="*60)
    print("STEP 1: Querying current table structure")
    print("="*60)

    # Query rate_versions
    print("\n--- rate_versions table ---")
    try:
        result = supabase.table('rate_versions').select('*').limit(5).execute()
        if result.data:
            print(f"Columns: {list(result.data[0].keys())}")
            print(f"Sample rows ({len(result.data)}):")
            for row in result.data:
                print(f"  {row}")
        else:
            print("Table is empty")
    except Exception as e:
        print(f"Error: {e}")

    # Query rates
    print("\n--- rates table ---")
    try:
        result = supabase.table('rates').select('*').limit(5).execute()
        if result.data:
            print(f"Columns: {list(result.data[0].keys())}")
            print(f"Sample rows ({len(result.data)}):")
            for row in result.data:
                print(f"  {row}")
        else:
            print("Table is empty")
    except Exception as e:
        print(f"Error: {e}")

    # Count existing records
    print("\n--- Current record counts ---")
    try:
        rv_count = supabase.table('rate_versions').select('id', count='exact').execute()
        print(f"rate_versions: {rv_count.count} records")
    except Exception as e:
        print(f"rate_versions count error: {e}")

    try:
        r_count = supabase.table('rates').select('id', count='exact').execute()
        print(f"rates: {r_count.count} records")
    except Exception as e:
        print(f"rates count error: {e}")

def truncate_tables():
    """Step 2: Truncate the rates and rate_versions tables"""
    print("\n" + "="*60)
    print("STEP 2: Truncating tables")
    print("="*60)

    # Delete all rates first (foreign key constraint)
    print("\nDeleting all rates...")
    try:
        # Delete in batches to avoid timeout
        while True:
            result = supabase.table('rates').select('id').limit(1000).execute()
            if not result.data:
                break
            ids = [r['id'] for r in result.data]
            supabase.table('rates').delete().in_('id', ids).execute()
            print(f"  Deleted {len(ids)} rates...")
        print("  rates table cleared")
    except Exception as e:
        print(f"  Error deleting rates: {e}")

    # Delete all rate_versions
    print("\nDeleting all rate_versions...")
    try:
        while True:
            result = supabase.table('rate_versions').select('id').limit(1000).execute()
            if not result.data:
                break
            ids = [r['id'] for r in result.data]
            supabase.table('rate_versions').delete().in_('id', ids).execute()
            print(f"  Deleted {len(ids)} rate_versions...")
        print("  rate_versions table cleared")
    except Exception as e:
        print(f"  Error deleting rate_versions: {e}")

def parse_date(date_str):
    """Parse date from CSV format like '1/1/2021 12:00:00 AM'"""
    try:
        # Parse the datetime string
        dt = datetime.strptime(date_str.strip(), '%m/%d/%Y %I:%M:%S %p')
        return dt.strftime('%Y-%m-%d')
    except Exception as e:
        print(f"  Error parsing date '{date_str}': {e}")
        return None

def load_csv_data(csv_path):
    """Step 3: Load CSV data with RateStartDate as effective_date"""
    print("\n" + "="*60)
    print(f"STEP 3: Loading CSV data from {csv_path}")
    print("="*60)

    # Read and group by RateStartDate
    rates_by_date = {}

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rate_start_date = row.get('RateStartDate', '')
            effective_date = parse_date(rate_start_date)

            if not effective_date:
                continue

            if effective_date not in rates_by_date:
                rates_by_date[effective_date] = []

            rates_by_date[effective_date].append(row)

    print(f"\nFound {len(rates_by_date)} unique effective dates:")
    for date in sorted(rates_by_date.keys()):
        print(f"  {date}: {len(rates_by_date[date])} rates")

    # First, ensure all jurisdictions exist
    print("\n--- Ensuring jurisdictions exist ---")
    all_regions = set()
    for rows in rates_by_date.values():
        for row in rows:
            region_code = row.get('RegionCode', '').strip()
            region_name = row.get('RegionName', '').strip()
            if region_code:
                all_regions.add((region_code, region_name))

    for region_code, region_name in all_regions:
        try:
            existing = supabase.table('jurisdictions').select('id').eq('city_code', region_code).execute()
            if not existing.data:
                # Get max ID
                max_id_result = supabase.table('jurisdictions').select('id').order('id', desc=True).limit(1).execute()
                new_id = (max_id_result.data[0]['id'] + 1) if max_id_result.data else 1

                supabase.table('jurisdictions').insert({
                    'id': new_id,
                    'level': 'city',
                    'state_code': 'AZ',
                    'city_code': region_code,
                    'city_name': region_name or f"{region_code} City"
                }).execute()
                print(f"  Created jurisdiction: {region_code} ({region_name})")
        except Exception as e:
            print(f"  Error with jurisdiction {region_code}: {e}")

    # Ensure all business codes exist
    print("\n--- Ensuring business codes exist ---")
    all_codes = set()
    for rows in rates_by_date.values():
        for row in rows:
            code = row.get('BusinessCode', '').strip()
            name = row.get('BusinessCodesName', '').strip()
            if code:
                all_codes.add((code, name))

    for code, name in all_codes:
        try:
            supabase.table('business_class_codes').upsert({
                'code': code,
                'description': name or f'Business Code {code}'
            }).execute()
        except Exception as e:
            print(f"  Error with business code {code}: {e}")
    print(f"  Processed {len(all_codes)} business codes")

    # Create rate_versions and rates for each effective date
    print("\n--- Creating rate versions and rates ---")
    total_rates = 0

    for effective_date in sorted(rates_by_date.keys()):
        rows = rates_by_date[effective_date]

        # Create rate_version
        try:
            rv_result = supabase.table('rate_versions').insert({
                'effective_date': effective_date,
                'loaded_at': effective_date
            }).execute()

            rate_version_id = rv_result.data[0]['id']
            print(f"\n  Created rate_version {rate_version_id} for {effective_date}")

            # Build jurisdiction lookup with level information
            jurisdictions = {}
            j_result = supabase.table('jurisdictions').select('id, city_code, region_code, level').execute()
            for j in j_result.data:
                level = j.get('level', 'city')
                if j.get('city_code'):
                    jurisdictions[j['city_code']] = (j['id'], level)
                if j.get('region_code'):
                    jurisdictions[j['region_code']] = (j['id'], level)

            # Insert rates in batches
            rates_to_insert = []
            for row in rows:
                region_code = row.get('RegionCode', '').strip()
                business_code = row.get('BusinessCode', '').strip()
                tax_rate = row.get('TaxRate', '0').strip()

                lookup = jurisdictions.get(region_code)
                if not lookup:
                    continue

                jurisdiction_id, jurisdiction_level = lookup

                try:
                    rate_value = float(tax_rate)
                    # Convert percentage to decimal if needed
                    if rate_value > 1:
                        rate_decimal = rate_value / 100.0
                    else:
                        rate_decimal = rate_value
                except ValueError:
                    rate_decimal = 0.0

                # Put rate in correct column based on jurisdiction level
                if jurisdiction_level == 'county':
                    county_rate = rate_decimal
                    city_rate = 0.0
                else:  # city level
                    county_rate = 0.0
                    city_rate = rate_decimal

                rates_to_insert.append({
                    'rate_version_id': rate_version_id,
                    'business_code': business_code,
                    'jurisdiction_id': jurisdiction_id,
                    'state_rate': 0.0,
                    'county_rate': county_rate,
                    'city_rate': city_rate
                })

            # Insert in batches of 500
            batch_size = 500
            for i in range(0, len(rates_to_insert), batch_size):
                batch = rates_to_insert[i:i+batch_size]
                supabase.table('rates').insert(batch).execute()

            print(f"    Inserted {len(rates_to_insert)} rates")
            total_rates += len(rates_to_insert)

        except Exception as e:
            print(f"  Error processing {effective_date}: {e}")

    print(f"\n  TOTAL: {total_rates} rates inserted across {len(rates_by_date)} rate versions")

def verify_px_011():
    """Step 4: Verify with PX + 011 query"""
    print("\n" + "="*60)
    print("STEP 4: Verification - PX + 011 query")
    print("="*60)

    # Get jurisdiction ID for PX (Phoenix)
    print("\nLooking up PX (Phoenix) jurisdiction...")
    j_result = supabase.table('jurisdictions').select('id, city_code, city_name').eq('city_code', 'PX').execute()

    if not j_result.data:
        print("  ERROR: PX jurisdiction not found!")
        return

    jurisdiction_id = j_result.data[0]['id']
    print(f"  Found: {j_result.data[0]}")

    # Query rates for PX + 011 (Restaurants and Bars)
    print("\nQuerying rates for PX + business code 011 (Restaurants and Bars)...")

    result = supabase.table('rates').select(
        '*, rate_versions(effective_date)'
    ).eq('jurisdiction_id', jurisdiction_id).eq('business_code', '011').execute()

    if result.data:
        print(f"\nFound {len(result.data)} rate records:")
        print("-" * 80)
        for rate in sorted(result.data, key=lambda x: x['rate_versions']['effective_date'] if x.get('rate_versions') else ''):
            rv = rate.get('rate_versions', {})
            eff_date = rv.get('effective_date', 'N/A') if rv else 'N/A'
            print(f"  Effective: {eff_date} | City Rate: {rate['city_rate']} | Version ID: {rate['rate_version_id']}")
    else:
        print("  No rates found for PX + 011")

    # Also show summary stats
    print("\n--- Summary Statistics ---")
    rv_count = supabase.table('rate_versions').select('id', count='exact').execute()
    r_count = supabase.table('rates').select('id', count='exact').execute()
    print(f"Total rate_versions: {rv_count.count}")
    print(f"Total rates: {r_count.count}")

def main():
    print("="*60)
    print("HISTORICAL TAX RATES LOADER")
    print("="*60)

    # CSV file path
    csv_path = r"C:\Users\noson\Downloads\AZTaxesRpt - SpRates.csv"

    # Step 1: Query current structure
    query_table_structure()

    # Step 2: Truncate tables
    truncate_tables()

    # Step 3: Load CSV data
    load_csv_data(csv_path)

    # Step 4: Verify
    verify_px_011()

    print("\n" + "="*60)
    print("DONE!")
    print("="*60)

if __name__ == '__main__':
    main()
