# County/City Rate Column Mapping Fix

**Date**: 2026-02-03
**Status**: ✅ COMPLETED

## Problem

All rate loading scripts (001, 002, 003, 004) were hardcoding ALL rates into the `city_rate` column, even for county-level jurisdictions. This is the same bug that was fixed in production data via Migration 020 in the integrations repo.

### Impact
- County rates were incorrectly stored in `city_rate` column
- City rates were correctly stored in `city_rate` column
- `county_rate` column was always 0 for all newly loaded rates
- This would break XML generation for any data loaded after Feb 2026

## Root Cause

Scripts were not checking jurisdiction level when inserting rates:

```python
# WRONG - All rates went into city_rate
rates_to_insert.append({
    "state_rate": 0.0,
    "county_rate": 0.0,        # Always 0
    "city_rate": r['rate']     # All rates here
})
```

## Solution

Updated all 4 rate loading scripts to:

1. **Load jurisdiction level** when building the cache
2. **Check jurisdiction level** before inserting rates
3. **Put rates in correct column** based on level

```python
# CORRECT - Rates go into correct column
if jurisdiction_level == 'county':
    county_rate = r['rate']
    city_rate = 0.0
else:  # city level
    county_rate = 0.0
    city_rate = r['rate']

rates_to_insert.append({
    "state_rate": 0.0,
    "county_rate": county_rate,
    "city_rate": city_rate
})
```

## Scripts Updated

### 1. `scripts/001_load_historical_rates.py`
- Updated `build_jurisdiction_cache()` to return `Dict[str, Tuple[int, str]]`
- Added level-based rate column selection (lines 204-247)

### 2. `scripts/002_load_jan2026_rates.py`
- Updated jurisdiction cache to include level (lines 66-73)
- Added level-based rate column selection (lines 115-148)
- Updated jurisdiction creation to store tuple (line 91)

### 3. `scripts/003_restore_and_sync_rates.py`
- Updated `build_jurisdiction_cache()` to return tuples with level
- Updated `ensure_jurisdiction_exists()` to return `(id, level)` tuple
- Fixed rate insertion in **two places**:
  - Historical CSV merge (lines 298-326)
  - ADOR CSV sync (lines 425-448)
- Updated function signatures for type safety

### 4. `scripts/004_add_monthly_rates.py`
- Updated `build_jurisdiction_cache()` to return `Dict[str, Tuple[int, str]]`
- Added level-based rate column selection (lines 149-178)

## Verification

After loading new rates with the updated scripts, verify they're in the correct columns:

```sql
-- Check rates are in correct columns by jurisdiction level
SELECT
  j.level,
  j.city_name,
  j.county_name,
  COUNT(*) as rate_count,
  SUM(CASE WHEN r.county_rate > 0 THEN 1 ELSE 0 END) as has_county_rate,
  SUM(CASE WHEN r.city_rate > 0 THEN 1 ELSE 0 END) as has_city_rate,
  SUM(CASE WHEN r.county_rate > 0 AND r.city_rate > 0 THEN 1 ELSE 0 END) as has_both
FROM rates r
JOIN jurisdictions j ON r.jurisdiction_id = j.id
WHERE r.rate_version_id = (SELECT MAX(id) FROM rate_versions)
GROUP BY j.level, j.city_name, j.county_name
ORDER BY j.level, rate_count DESC
LIMIT 20;
```

### Expected Results

**For county-level jurisdictions:**
- `has_county_rate` should equal `rate_count`
- `has_city_rate` should be 0
- `has_both` should be 0

**For city-level jurisdictions:**
- `has_city_rate` should equal `rate_count`
- `has_county_rate` should be 0
- `has_both` should be 0

### Sample Verification Query

```sql
-- Verify Maricopa County (should have rates in county_rate)
SELECT
  j.county_name,
  j.level,
  r.business_code,
  r.county_rate,
  r.city_rate,
  r.total_rate
FROM rates r
JOIN jurisdictions j ON r.jurisdiction_id = j.id
JOIN rate_versions rv ON r.rate_version_id = rv.id
WHERE j.county_name = 'Maricopa'
  AND j.level = 'county'
  AND r.business_code = '011'
ORDER BY rv.effective_date DESC
LIMIT 5;

-- Verify Phoenix City (should have rates in city_rate)
SELECT
  j.city_name,
  j.level,
  r.business_code,
  r.county_rate,
  r.city_rate,
  r.total_rate
FROM rates r
JOIN jurisdictions j ON r.jurisdiction_id = j.id
JOIN rate_versions rv ON r.rate_version_id = rv.id
WHERE j.city_name = 'PHOENIX'
  AND j.level = 'city'
  AND r.business_code = '011'
ORDER BY rv.effective_date DESC
LIMIT 5;
```

## Related Changes

This fix aligns with the migrations made in `cactuscomply-integrations`:

- **Migration 018**: Populated `county_name` for all cities
- **Migration 019**: Fixed 6 mislabeled counties, created 9 missing counties
- **Migration 020**: Moved existing county rates from `city_rate` to `county_rate`

## Testing Checklist

- [x] All scripts compile without syntax errors
- [ ] Test 004 script with a new monthly CSV
- [ ] Verify rates are in correct columns using SQL queries above
- [ ] Confirm XML generation still works correctly
- [ ] Validate county/city transaction separation in generated XML

## Rollback

If issues are discovered, rates can be fixed with:

```sql
-- Move county rates back to city_rate (NOT RECOMMENDED)
UPDATE rates r
SET
  city_rate = r.county_rate,
  county_rate = 0.0
FROM jurisdictions j
WHERE r.jurisdiction_id = j.id
  AND j.level = 'county'
  AND r.county_rate > 0
  AND r.rate_version_id = [SPECIFIC_VERSION_ID];
```

However, it's better to delete incorrectly loaded rates and reload with the fixed scripts.
