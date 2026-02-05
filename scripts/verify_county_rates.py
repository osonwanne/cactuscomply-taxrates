"""
Quick verification of county rate coverage
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_KEY')
)

# Get all counties with rate counts
counties = supabase.table("jurisdictions").select(
    "id, county_name, region_code"
).eq("level", "county").order("county_name").execute()

print("\n" + "="*80)
print("COUNTY RATE VERIFICATION")
print("="*80)

for county in counties.data:
    county_id = county['id']
    county_name = county['county_name']
    region_code = county['region_code']

    # Get rate count
    rates = supabase.table("rates").select(
        "id, business_code, county_rate, rate_version_id",
        count='exact'
    ).eq("jurisdiction_id", county_id).execute()

    rate_count = rates.count or 0

    # Get unique business codes
    business_codes = set()
    versions = set()
    sample_rate = None

    for rate in rates.data:
        business_codes.add(rate['business_code'])
        versions.add(rate['rate_version_id'])
        if rate['business_code'] == '011' and not sample_rate:
            sample_rate = rate['county_rate']

    print(f"\n{county_name} ({region_code}):")
    print(f"  Total Rates: {rate_count}")
    print(f"  Business Codes: {len(business_codes)}")
    print(f"  Rate Versions: {len(versions)}")
    if sample_rate:
        print(f"  Sample (Business 011 - Restaurants): {sample_rate:.4%}")

print("\n" + "="*80)
print(f"TOTAL: {len(counties.data)} counties verified")
print("="*80)
