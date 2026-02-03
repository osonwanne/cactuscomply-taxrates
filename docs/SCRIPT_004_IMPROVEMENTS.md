# Script 004 Improvements - Changelog

**Date:** 2026-02-03
**File:** `scripts/004_add_monthly_rates.py`
**Purpose:** Merge best practices from ADORSyncService into script 004

---

## Changes Made

### 1. Added `parse_rate()` Helper Function
**Lines:** 66-84

**What it does:**
- Parses rate strings with better error handling
- Rounds to 6 decimal places for precision
- Handles empty/null values gracefully
- Logs warnings for unparseable rates instead of crashing

**Before:**
```python
rate = float(tax_rate.replace('%', ''))
if rate > 1:
    rate = rate / 100.0
```

**After:**
```python
rate = parse_rate(tax_rate)

def parse_rate(rate_str: str) -> float:
    if not rate_str:
        return 0.0
    rate_str = str(rate_str).strip().replace("%", "")
    try:
        rate = float(rate_str)
        if rate > 1:
            rate = rate / 100.0
        return round(rate, 6)  # 6 decimal places precision
    except ValueError:
        print(f"WARNING: Could not parse rate: '{rate_str}', using 0.0")
        return 0.0
```

---

### 2. Added `parse_date()` Helper Function
**Lines:** 87-118

**What it does:**
- Handles multiple date formats for flexibility
- Useful if ADOR changes CSV date format in the future
- Currently not used but available for future enhancement

**Usage:**
```python
parsed_date = parse_date("1/01/2026 0:00")  # Returns "2026-01-01"
```

---

### 3. Added `COUNTY_CODES` Constant
**Lines:** 43-60

**What it does:**
- Defines all 15 Arizona counties with region codes
- Can be used for validation and display
- Makes county detection logic more maintainable

**Usage:**
```python
COUNTY_CODES = {
    "APA": "Apache",
    "COH": "Cochise",
    "COC": "Coconino",
    # ... 12 more counties
}
```

---

### 4. Added `find_latest_csv_file()` Function
**Lines:** 135-175

**What it does:**
- Auto-discovers the newest ADOR CSV in Downloads folder
- Sorts by date extracted from filename
- Enables `--auto` flag for convenience

**Usage:**
```bash
# Old way: specify exact filename
python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv

# New way: auto-find latest
python scripts/004_add_monthly_rates.py --auto
```

**Implementation:**
```python
def find_latest_csv_file(directory: str = None) -> Optional[str]:
    """Find the latest ADOR CSV file in the specified directory."""
    pattern = os.path.join(directory or DOWNLOADS_DIR, "TPT_RATETABLE_ALL_*.csv")
    files = glob.glob(pattern)

    # Extract dates and sort (YYYYMMDD format)
    file_dates = []
    for file_path in files:
        match = re.search(r"TPT_RATETABLE_ALL_(\d{8})\.csv", file_path)
        if match:
            date_str = match.group(1)
            # Convert MMDDYYYY to YYYYMMDD for sorting
            sortable_date = f"{date_str[4:]}{date_str[:2]}{date_str[2:4]}"
            file_dates.append((sortable_date, file_path))

    file_dates.sort(reverse=True)
    return file_dates[0][1] if file_dates else None
```

---

### 5. Enhanced `build_jurisdiction_cache()`
**Lines:** 178-202

**What changed:**
- Now returns `(id, level, display_name)` tuple instead of just `(id, level)`
- Includes jurisdiction name for better output

**Before:**
```python
cache[j["city_code"]] = (j["id"], level)
```

**After:**
```python
display_name = j.get("county_name" if level == "county" else "city_name", "")
cache[j["city_code"]] = (j["id"], level, display_name)
```

---

### 6. Better Error Handling in CSV Parsing
**Lines:** 265-283

**What changed:**
- Added row number tracking for better error messages
- Counts parse errors separately
- Shows specific error messages with row numbers
- Continues processing after individual row errors

**Before:**
```python
except:
    continue  # Silent failure
```

**After:**
```python
except Exception as e:
    parse_errors += 1
    print(f"WARNING: Error parsing row {row_num}: {e}")
    continue

# Later in output:
if parse_errors > 0:
    print(f"WARNING: {parse_errors} rows had parse errors and were skipped")
```

---

### 7. Improved Missing Jurisdiction Reporting
**Lines:** 315-319, 361-363

**What changed:**
- Tracks which region codes are missing
- Shows list of missing codes in output

**Before:**
```python
missing_jurisdiction += 1
# No visibility into which codes were missing
```

**After:**
```python
missing_jurisdiction += 1
missing_jurisdiction_codes.add(r['region_code'])

# In output:
if missing_jurisdiction_codes:
    print(f"    Missing codes: {', '.join(sorted(missing_jurisdiction_codes))}")
```

---

### 8. Better Error Handling in Batch Insert
**Lines:** 350-357

**What changed:**
- Counts insert errors separately
- Shows batch number that failed
- Reports total insert errors in summary

**Before:**
```python
except Exception as e:
    print(f"Error inserting batch: {e}")
```

**After:**
```python
except Exception as e:
    insert_errors += 1
    print(f"ERROR: Failed to insert batch {i//batch_size + 1}: {e}")

# Later in output:
if insert_errors > 0:
    print(f"  Insert errors: {insert_errors} batches failed")
```

---

### 9. Enhanced `ensure_business_code_exists()`
**Lines:** 232-239

**What changed:**
- More specific error handling
- Shows which business code failed

**Before:**
```python
except:
    pass  # Silent failure
```

**After:**
```python
except Exception as e:
    print(f"WARNING: Could not upsert business code {code}: {e}")
```

---

### 10. Updated Documentation and Usage
**Lines:** 1-23, 419-430

**What changed:**
- Added improvement notes to docstring
- Added `--auto` flag to usage examples
- Documented new options

**New usage:**
```bash
python scripts/004_add_monthly_rates.py <csv_file>
python scripts/004_add_monthly_rates.py --auto

Options:
  --auto    Automatically find and use the latest CSV in Downloads folder
```

---

## Summary of Improvements

### High Impact:
✅ **parse_rate()** - Better precision and error handling
✅ **find_latest_csv_file()** - Convenience feature for auto-discovery
✅ **Better error messages** - Specific row numbers and codes
✅ **COUNTY_CODES constant** - Better organization

### Medium Impact:
✅ **parse_date()** - Future-proofing for date format changes
✅ **Enhanced jurisdiction cache** - Includes display names
✅ **Missing jurisdiction tracking** - Shows which codes are missing

### Low Impact:
✅ **Better function documentation** - Clearer docstrings
✅ **Import additions** - Added `glob` and `Optional` for new features

---

## Testing Recommendations

### 1. Test existing functionality
```bash
# Should work exactly as before
python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv
```

### 2. Test new --auto flag
```bash
# Should find newest CSV in Downloads
python scripts/004_add_monthly_rates.py --auto
```

### 3. Test error handling
- Try with malformed CSV (missing columns)
- Try with invalid rates (non-numeric)
- Verify error messages are helpful

### 4. Verify rate precision
```python
# Check that rates are stored with 6 decimals
SELECT city_rate, county_rate
FROM rates
WHERE rate_version_id = (SELECT MAX(id) FROM rate_versions)
LIMIT 10;
```

---

## What Was NOT Changed

✅ **Core logic preserved:**
- Rate versioning logic - unchanged
- Batch insert logic - unchanged
- Duplicate detection - unchanged
- County vs city rate assignment - unchanged

✅ **Database operations:**
- No schema changes required
- Same Supabase queries
- Same table structure

---

## Rollback Plan

If issues are found:
```bash
cd ~/Documents/GitHub/cactuscomply-taxrates
git log scripts/004_add_monthly_rates.py
git checkout <previous-commit> scripts/004_add_monthly_rates.py
```

---

## Related Files

- `scripts/004_add_monthly_rates.py` - This file (improved)
- `cactuscomply-integrations/services/ador_sync_service.py` - Source of improvements
- `cactuscomply-integrations/docs/ador-sync-improvements.md` - Original improvement plan
