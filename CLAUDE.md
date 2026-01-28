# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Local development
pip install -r requirements.txt
python app.py                        # Starts Flask on http://localhost:5000

# Production
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Data loading scripts (in scripts/ folder)
python scripts/001_load_historical_rates.py       # Load historical rates (TRUNCATES first!)
python scripts/002_load_jan2026_rates.py          # Add January 2026 rates (incremental)
python scripts/003_restore_and_sync_rates.py      # Comprehensive restore and sync (see options below)
python scripts/004_add_monthly_rates.py <file>    # Add single monthly CSV (March 2026+)
```

## Architecture

This is a **Flask application** for managing Arizona TPT (Transaction Privilege Tax) rate data. It provides a web UI for CSV uploads and scripts for bulk data loading.

### Tech Stack
- **Flask 2.3** with Jinja templates
- **Supabase** (PostgreSQL) via `supabase-py`
- **Gunicorn** for production WSGI

### Project Layout
- `app.py` — Flask app with routes and Supabase operations
- `templates/` — Jinja HTML templates for web UI
- `uploads/` — Temporary storage for uploaded files
- `tests/` — Pytest test suite

### Scripts
| Script | Description |
|--------|-------------|
| `load_historical_rates.py` | Loads historical rates from CSV; **TRUNCATES tables first** |
| `load_jan2026_rates.py` | Adds January 2026 rates incrementally (no truncation) |
| `restore_and_sync_rates.py` | Comprehensive restore from backup + merge historical + sync ADOR CSVs |

### Database Tables (Supabase)
Uses the same Supabase database as `cactuscomply-integrations`:
- `jurisdictions` — City/county jurisdictions with `city_code`, `region_code`
- `rate_versions` — Effective dates for rate sets
- `rates` — Tax rates by `rate_version_id`, `jurisdiction_id`, `business_code`
- `business_class_codes` — Business classification codes (e.g., '011' = Restaurants)
- `current_rates` — View for latest rates

### Key Relationships
```
rate_versions (1) --< rates (many)
jurisdictions (1) --< rates (many)
business_class_codes (1) --< rates (many)
```

## Data Flow

### CSV Upload (Web UI)
1. User uploads ADOR CSV via web form with effective date
2. `parse_csv_content()` extracts region codes, business codes, rates
3. Upserts jurisdictions and business codes if new
4. Creates `rate_version` for the effective date
5. Inserts rates into `rates` table

### Bulk Loading (Scripts)
- **Historical**: Reads CSV with `RateStartDate` column, groups by date, creates rate_versions
- **ADOR CSVs**: Parses `TPT_RATETABLE_ALL_MMDDYYYY.csv` filenames for effective dates
- **Backup Restore**: Parses PostgreSQL COPY format from SQL backup files

## 003_restore_and_sync_rates.py Options

Default CSV files used:
- `AZTaxesRpt - SpRates (1) (2).csv` - Historical rates through Oct 2024
- `AZTaxesRpt - SpRates.csv` - Historical rates through Nov 2025
- `TPT_RATETABLE_ALL_*.csv` - ADOR monthly rate tables (Aug 2025 - Feb 2026)

```bash
# Full restore (backup + historical + ADOR)
python restore_and_sync_rates.py

# Skip backup restoration (use existing data)
python restore_and_sync_rates.py --skip-backup

# Only verify current coverage
python restore_and_sync_rates.py --verify-only

# Custom paths
python restore_and_sync_rates.py \
  --backup-path "path/to/backup.sql" \
  --historical-csvs "file1.csv" "file2.csv" \
  --downloads-dir "path/to/ador/csvs"
```

## Environment Variables

Required in `.env`:
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SERVICE_KEY` — Supabase service role key
- `SECRET_KEY` — Flask session key (optional, has default)

## Related Repositories

- **cactuscomply** — Next.js frontend (shows rates in /location-mapping)
- **cactuscomply-integrations** — Flask backend with API endpoints for rates

## Common Tasks

### Check rate coverage
```python
python -c "
from restore_and_sync_rates import verify_coverage
verify_coverage()
"
```

### Query specific jurisdiction rate
```python
# In Python with Supabase client
result = supabase.table('rates').select('city_rate, rate_versions(effective_date)').eq(
    'jurisdiction_id', 231  # TUCSON
).eq('business_code', '011').order('rate_version_id', desc=True).limit(1).execute()
```

### Add new ADOR CSV
1. Download CSV from azdor.gov
2. Save to Downloads folder as `TPT_RATETABLE_ALL_MMDDYYYY.csv`
3. Run: `python load_jan2026_rates.py` (update path in script)

### Restore from backup
1. Download Supabase backup (gzipped)
2. Extract SQL file
3. Run: `python restore_and_sync_rates.py --backup-path path/to/backup.sql`
