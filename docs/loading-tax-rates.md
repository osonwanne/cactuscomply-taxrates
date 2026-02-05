# Loading Tax Rates Guide

This guide explains how to load tax rates into the Supabase database for Arizona jurisdictions (counties and cities).

## Overview

There are two types of rate loading operations:

1. **Historical/One-off Loads** - Load large historical datasets with multiple effective dates (e.g., "AZTaxesRpt - SpRates.csv")
2. **Monthly Updates** - Add new monthly rates from ADOR (e.g., "TPT_RATETABLE_ALL_02012026.csv")

## Scripts

### 004_add_monthly_rates.py - For Monthly Updates

**Use this for:** Adding new monthly rate tables from ADOR (March 2026 onwards)

**File format:** `TPT_RATETABLE_ALL_MMDDYYYY.csv`

**Usage:**
```bash
# Specify exact file
python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv

# Auto-discover latest CSV in Downloads folder
python scripts/004_add_monthly_rates.py --auto

# Full path
python scripts/004_add_monthly_rates.py "C:/Users/noson/Downloads/TPT_RATETABLE_ALL_03012026.csv"
```

**What it does:**
- Parses effective date from filename (MMDDYYYY format)
- Creates single `rate_version` for that effective date
- Loads all rates from the CSV for that date
- Maps rates to correct columns based on jurisdiction level:
  - **Counties**: rate → `county_rate` column
  - **Cities**: rate → `city_rate` column
- Skips duplicates (idempotent)

**Example:**
```bash
# Add March 2026 rates
python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv
```

---

### 004b_load_historical_county_rates.py - For Historical Loads

**Use this for:** One-off loading of historical rate data with multiple effective dates

**File format:** `AZTaxesRpt - SpRates.csv` (has `RateStartDate` and `RateEndDate` columns)

**Usage:**
```bash
# Load historical data
python scripts/004b_load_historical_county_rates.py "C:/Users/noson/Downloads/AZTaxesRpt - SpRates (2).csv"

# Verify county coverage only (no loading)
python scripts/004b_load_historical_county_rates.py --verify
```

**What it does:**
- Parses `RateStartDate` from each CSV row
- Groups rates by effective date
- Creates multiple `rate_version` records (one per unique date)
- Loads all historical rates across all dates
- Maps rates to correct columns based on jurisdiction level
- Filters out future dates (> 2026-02-04)
- Provides verification of county coverage

**Example output:**
```
Parsed 5201 total records
Found 103 unique effective dates
Found 181 unique business codes
Date range: 1990-10-01 to 2026-01-01

Loading rates for 103 effective dates...
Total inserted: 528
Total skipped: 4673
```

---

## Data Structure

### Database Schema

**rate_versions** table:
- `id` - Auto-incrementing version ID
- `effective_date` - Date when rates become effective

**rates** table:
- `rate_version_id` - Links to rate_versions
- `jurisdiction_id` - Links to jurisdictions
- `business_code` - Business classification code (e.g., '011' = Restaurants)
- `state_rate` - Arizona state TPT rate (usually 0.0 in our data)
- `county_rate` - County excise tax rate (for county jurisdictions)
- `city_rate` - City privilege tax rate (for city jurisdictions)
- `total_rate` - Auto-calculated: state_rate + county_rate + city_rate

### Key Rules

1. **County rates** → `county_rate` column (migration 020)
2. **City rates** → `city_rate` column
3. Never mix: counties should have `city_rate = 0`, cities should have `county_rate = 0`

## Verification

### Check County Coverage

```bash
# Using script
python scripts/004b_load_historical_county_rates.py --verify

# Or standalone
python scripts/verify_county_rates.py
```

### Expected Results

All 15 Arizona counties should have rates:
- Apache (APA)
- Cochise (COH)
- Coconino (COC)
- Gila (GLA)
- Graham (GRA)
- Greenlee (GRN)
- La Paz (LAP)
- Maricopa (MAR)
- Mohave (MOH)
- Navajo (NAV)
- Pima (PMA)
- Pinal (PNL)
- Santa Cruz (STC)
- Yavapai (YAV)
- Yuma (YMA)

### Sample Verification Output

```
Apache (APA):
  Total Rates: 37
  Business Codes: 36
  Rate Versions: 13
  Sample (Business 011 - Restaurants): 6.1000%

Maricopa (MAR):
  Total Rates: 331
  Business Codes: 43
  Rate Versions: 24
  Sample (Business 011 - Restaurants): 6.3000%
```

## Common Scenarios

### Scenario 1: Adding New Monthly ADOR CSV

ADOR emails new CSV for March 2026: `TPT_RATETABLE_ALL_03012026.csv`

```bash
# 1. Save file to Downloads folder
# 2. Run monthly script
python scripts/004_add_monthly_rates.py --auto

# Or specify exact file
python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv
```

### Scenario 2: Loading Historical Data (One-off)

ADOR provides comprehensive historical CSV spanning 1/1/2024 - 1/31/2026:

```bash
# 1. Save file to Downloads
# 2. Run historical loader
python scripts/004b_load_historical_county_rates.py "C:/Users/noson/Downloads/AZTaxesRpt - SpRates (2).csv"

# 3. Verify coverage
python scripts/004b_load_historical_county_rates.py --verify
```

### Scenario 3: Checking What's Already Loaded

```bash
# Check current state
python -c "
from scripts.004_add_monthly_rates import verify_rates
verify_rates()
"

# Or use verification script
python scripts/verify_county_rates.py
```

## File Formats

### ADOR Monthly CSV Format

**Filename:** `TPT_RATETABLE_ALL_MMDDYYYY.csv`

**Columns:**
- `RegionCode` - City code or county code (e.g., "AJ", "MAR")
- `BusinessCode` - Business classification (e.g., "011")
- `BusinessCodesName` - Description
- `TaxRate` - Rate as percentage (e.g., "2.4" = 2.4%)

**Example:**
```csv
RegionCode,RegionName,BusinessCode,BusinessCodesName,TaxRate
AJ,APACHE JUNCTION,011,RESTAURANTS AND BARS,2.400000
MAR,MARICOPA,011,RESTAURANTS AND BARS,6.300000
```

### Historical CSV Format

**Filename:** `AZTaxesRpt - SpRates.csv`

**Additional columns:**
- `RateStartDate` - When rate becomes effective (e.g., "1/1/2021 12:00:00 AM")
- `RateEndDate` - When rate expires (usually "12/31/9999 12:00:00 AM")

**Example:**
```csv
RegionCode,RegionName,BusinessCode,BusinessCodesName,TaxRate,TaxRateType,RateStartDate,RateEndDate
MAR,MARICOPA,011,RESTAURANTS AND BARS,6.300000,Percent,8/1/2017 12:00:00 AM,12/31/9999 12:00:00 AM
```

## Troubleshooting

### Problem: "Missing jurisdiction" errors

**Cause:** CSV has region codes not in the jurisdictions table

**Solution:** Check if jurisdictions need to be added first (cities/counties not in database)

### Problem: All rates show as "Skipped"

**Cause:** Rates already exist for that version

**Solution:** This is normal - script is idempotent. If you need to reload, delete the rate_version first

### Problem: County rates showing in city_rate column

**Cause:** Old data before migration 020

**Solution:** Run migration 020 to fix column mapping:
```bash
# In cactuscomply-integrations repo
psql [...] -f migrations/020_fix_rates_column_mapping.sql
```

### Problem: Unicode errors on Windows

**Cause:** Windows CMD doesn't support emoji characters

**Solution:** Use `--verify` flag or the standalone `verify_county_rates.py` script

## Migration History

**Migration 019** - Converted counties from city-level to county-level in jurisdictions table

**Migration 020** - Fixed rates table column mapping (county rates → county_rate column)

These migrations ensure that:
1. Counties are properly labeled with `level='county'`
2. County rates are in the `county_rate` column, not `city_rate`
3. Cities remain with `level='city'` and rates in `city_rate` column

## Related Documentation

- [CLAUDE.md](../CLAUDE.md) - Main project documentation
- [restore_and_sync_rates.py](../scripts/003_restore_and_sync_rates.py) - Comprehensive restore script
- [Migration 020](../../cactuscomply-integrations/migrations/020_fix_rates_column_mapping.sql) - Column mapping fix

## Last Updated

2026-02-04 - Added county rate loading support with historical CSV handling
