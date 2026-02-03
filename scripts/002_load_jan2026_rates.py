"""
Script to load January 2026 tax rates
"""
import os
import csv
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def parse_date(date_str):
    """Parse date from CSV format like '1/01/2026 0:00'"""
    try:
        # Try new format first: 1/01/2026 0:00
        dt = datetime.strptime(date_str.strip(), '%m/%d/%Y %H:%M')
        return dt.strftime('%Y-%m-%d')
    except:
        try:
            # Try alternate format: 1/1/2021 12:00:00 AM
            dt = datetime.strptime(date_str.strip(), '%m/%d/%Y %I:%M:%S %p')
            return dt.strftime('%Y-%m-%d')
        except Exception as e:
            print(f"  Error parsing date '{date_str}': {e}")
            return None

def load_csv_data(csv_path):
    """Load CSV data with RateStartDate as effective_date"""
    print(f"\nLoading CSV: {csv_path}")

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

    print(f"\nFound {len(rates_by_date)} unique effective dates")

    # Show dates we'll be adding
    existing = supabase.table('rate_versions').select('effective_date').execute()
    existing_dates = set(r['effective_date'] for r in existing.data)

    new_dates = [d for d in sorted(rates_by_date.keys()) if d not in existing_dates]
    print(f"\nNew dates to add: {new_dates}")

    if not new_dates:
        print("No new dates to add!")
        return

    # Build jurisdiction lookup with level information
    jurisdictions = {}
    j_result = supabase.table('jurisdictions').select('id, city_code, region_code, level').execute()
    for j in j_result.data:
        level = j.get('level', 'city')
        if j.get('city_code'):
            jurisdictions[j['city_code']] = (j['id'], level)
        if j.get('region_code'):
            jurisdictions[j['region_code']] = (j['id'], level)

    # Process only new dates
    total_rates = 0
    for effective_date in new_dates:
        rows = rates_by_date[effective_date]

        # Ensure jurisdictions exist
        for row in rows:
            region_code = row.get('RegionCode', '').strip()
            region_name = row.get('RegionName', '').strip()
            if region_code and region_code not in jurisdictions:
                max_id_result = supabase.table('jurisdictions').select('id').order('id', desc=True).limit(1).execute()
                new_id = (max_id_result.data[0]['id'] + 1) if max_id_result.data else 1
                supabase.table('jurisdictions').insert({
                    'id': new_id,
                    'level': 'city',
                    'state_code': 'AZ',
                    'city_code': region_code,
                    'city_name': region_name or f"{region_code} City"
                }).execute()
                jurisdictions[region_code] = (new_id, 'city')
                print(f"  Created jurisdiction: {region_code}")

        # Ensure business codes exist
        for row in rows:
            code = row.get('BusinessCode', '').strip()
            name = row.get('BusinessCodesName', '').strip()
            if code:
                try:
                    supabase.table('business_class_codes').upsert({
                        'code': code,
                        'description': name or f'Business Code {code}'
                    }).execute()
                except:
                    pass

        # Create rate_version
        rv_result = supabase.table('rate_versions').insert({
            'effective_date': effective_date,
            'loaded_at': effective_date
        }).execute()

        rate_version_id = rv_result.data[0]['id']
        print(f"\nCreated rate_version {rate_version_id} for {effective_date}")

        # Insert rates
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

        # Insert in batches
        batch_size = 500
        for i in range(0, len(rates_to_insert), batch_size):
            batch = rates_to_insert[i:i+batch_size]
            supabase.table('rates').insert(batch).execute()

        print(f"  Inserted {len(rates_to_insert)} rates")
        total_rates += len(rates_to_insert)

    print(f"\nTOTAL: {total_rates} new rates inserted")

def verify():
    """Verify the data"""
    print("\n" + "="*60)
    print("VERIFICATION")
    print("="*60)

    # Check for 2026-01-01
    rv = supabase.table('rate_versions').select('*').eq('effective_date', '2026-01-01').execute()
    if rv.data:
        print(f"\n2026-01-01 rate_version: {rv.data[0]}")

        # Count rates for this version
        rates = supabase.table('rates').select('id', count='exact').eq('rate_version_id', rv.data[0]['id']).execute()
        print(f"Rates for this version: {rates.count}")
    else:
        print("\nNo 2026-01-01 rate_version found!")

    # PX + 011 check
    print("\nPX + 011 (Restaurants and Bars) rates:")
    j_result = supabase.table('jurisdictions').select('id').eq('city_code', 'PX').execute()
    if j_result.data:
        jurisdiction_id = j_result.data[0]['id']
        result = supabase.table('rates').select(
            '*, rate_versions(effective_date)'
        ).eq('jurisdiction_id', jurisdiction_id).eq('business_code', '011').execute()

        for rate in sorted(result.data, key=lambda x: x['rate_versions']['effective_date'] if x.get('rate_versions') else ''):
            rv = rate.get('rate_versions', {})
            eff_date = rv.get('effective_date', 'N/A') if rv else 'N/A'
            print(f"  {eff_date}: {rate['city_rate']*100:.1f}%")

if __name__ == '__main__':
    csv_path = r"C:\Users\noson\Downloads\TPT_RATETABLE_ALL_01012026 (2).csv"
    load_csv_data(csv_path)
    verify()
