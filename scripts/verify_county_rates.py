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


# ============================================================================
# CITY-TO-COUNTY SANITY CHECK
# ============================================================================
# Catches the class of bug that hit Day 2: scalar `jurisdictions.county_name`
# values for individual cities can drift from reality (typos, copy-paste from
# original seed migrations 018 + 021 in cactuscomply-integrations). The
# previous verify loop only inspects `level='county'` rows; this block adds
# `level='city'` checks for cities with known correct county assignments.
#
# Adding rows here is cheap — AZ city-to-county is public-record geography.
# Add a row whenever a new city lands in our jurisdictions table OR is
# referenced by a campaign filter.
#
# Bug fixed by migration 243 (2026-04-27) in cactuscomply-integrations:
#   SURPRISE was 'Apache'   -> Maricopa
#   PRESCOTT was 'Maricopa' -> Yavapai
#   SHOW LOW was 'Yuma'     -> Navajo
#   PATAGONIA was 'La Paz'  -> Santa Cruz

EXPECTED_CITY_COUNTIES = {
    # AZDOR Region Code -> (city_name as stored UPPER, expected county_name)
    # The 4 corrected cities (D2-Bug-9):
    "SU": ("SURPRISE",   "Maricopa"),
    "PC": ("PRESCOTT",   "Yavapai"),
    "SL": ("SHOW LOW",   "Navajo"),
    "PT": ("PATAGONIA",  "Santa Cruz"),
    # Sample of correct ones (defensive — catches if anyone breaks them):
    "ME": ("MESA",       "Maricopa"),
    "TC": ("TUCSON",     "Pima"),
    "PX": ("PHOENIX",    "Maricopa"),
    "GL": ("GLENDALE",   "Maricopa"),
}

print("\n" + "="*80)
print("CITY-TO-COUNTY SANITY CHECK")
print("="*80)

city_results = supabase.table("jurisdictions").select(
    "id, city_name, city_code, county_name, county_names"
).eq("level", "city").in_("city_code", list(EXPECTED_CITY_COUNTIES.keys())).execute()

failures = []
for row in city_results.data:
    code = row.get("city_code")
    expected = EXPECTED_CITY_COUNTIES.get(code)
    if not expected:
        continue
    expected_name, expected_county = expected
    actual_name = row.get("city_name") or ""
    actual_county = row.get("county_name") or ""
    multi = row.get("county_names") or []

    name_ok = actual_name.upper() == expected_name
    county_ok = actual_county == expected_county

    status = "OK" if (name_ok and county_ok) else "FAIL"
    multi_note = f" (multi-county: {multi})" if multi else ""
    print(f"  [{status}] {code} {expected_name}: county_name='{actual_county}' (expected '{expected_county}'){multi_note}")

    if not (name_ok and county_ok):
        failures.append({
            "city_code": code,
            "expected_name": expected_name,
            "expected_county": expected_county,
            "actual_name": actual_name,
            "actual_county": actual_county,
        })

# Surface missing rows (city_code expected but no row found)
found_codes = {row.get("city_code") for row in city_results.data}
for code, (expected_name, _) in EXPECTED_CITY_COUNTIES.items():
    if code not in found_codes:
        print(f"  [MISS] {code} {expected_name}: jurisdictions row not found")
        failures.append({"city_code": code, "expected_name": expected_name, "missing": True})

if failures:
    print("\n" + "="*80)
    print(f"FAIL: {len(failures)} city-to-county mismatch(es) - see above")
    print("="*80)
    raise SystemExit(1)
else:
    print(f"\n[OK] All {len(EXPECTED_CITY_COUNTIES)} expected cities verified.")
    print("="*80)
