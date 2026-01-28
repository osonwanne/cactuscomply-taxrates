# Syncing ADOR Tax Rates

This guide explains how to download and sync the latest Arizona TPT (Transaction Privilege Tax) rates from the Arizona Department of Revenue (ADOR).

## Monthly Rate Updates

ADOR publishes updated tax rate tables monthly. After February 2026, follow these steps to sync new rates.

### Step 1: Download the Latest CSV

1. Go to [ADOR Tax Rate Table](https://azdor.gov/business/transaction-privilege-tax/tax-rate-table)
2. Look for the **"Tax Rate Table in .csv format"** section
3. Download the latest CSV file (named like `TPT_RATETABLE_ALL_MMDDYYYY.csv`)
4. Save it to your Downloads folder

### Step 2: Run the Add Monthly Script

From the `cactuscomply-taxrates` directory:

```bash
# Add rates from a single CSV file
python scripts/004_add_monthly_rates.py TPT_RATETABLE_ALL_03012026.csv

# Or with full path
python scripts/004_add_monthly_rates.py "C:/Users/noson/Downloads/TPT_RATETABLE_ALL_03012026.csv"
```

The script will:
- Parse the effective date from the filename (e.g., `03012026` = March 1, 2026)
- Create a new `rate_version` for that date (if it doesn't exist)
- Insert new rates (skips duplicates automatically)
- Show before/after statistics

### Alternative: Sync All CSVs

If you have multiple CSV files to process, use the comprehensive script:

```bash
# Sync all TPT_RATETABLE_ALL_*.csv files in Downloads folder
python scripts/003_restore_and_sync_rates.py --skip-backup --skip-historical
```

This finds and processes all matching CSV files in chronological order.

### Step 3: Verify

```bash
# Check the sync results
python scripts/003_restore_and_sync_rates.py --verify-only
```

This shows:
- Total rate versions and date range
- Total rates count
- Jurisdictions and business codes covered
- Sample rates for test cities

## Script Options

```bash
# Full restore from backup + historical CSVs + ADOR CSVs
python scripts/003_restore_and_sync_rates.py

# Skip backup restoration (use existing data)
python scripts/003_restore_and_sync_rates.py --skip-backup

# Skip historical CSV merge
python scripts/003_restore_and_sync_rates.py --skip-historical

# Skip ADOR CSV sync
python scripts/003_restore_and_sync_rates.py --skip-ador

# Only verify current state
python scripts/003_restore_and_sync_rates.py --verify-only

# Custom Downloads directory
python scripts/003_restore_and_sync_rates.py --downloads-dir "/path/to/csvs"
```

## File Naming Convention

ADOR CSV files must follow this naming pattern:
```
TPT_RATETABLE_ALL_MMDDYYYY.csv
```

Examples:
- `TPT_RATETABLE_ALL_03012026.csv` - March 1, 2026
- `TPT_RATETABLE_ALL_04012026.csv` - April 1, 2026

The script extracts the effective date from the filename.

## Data Sources

| File Type | Description | Date Range |
|-----------|-------------|------------|
| `AZTaxesRpt - SpRates*.csv` | Historical rates (rate changes only) | 1990 - Nov 2025 |
| `TPT_RATETABLE_ALL_*.csv` | Monthly ADOR rate tables | Aug 2025 - current |

## Troubleshooting

### Connection Errors
If you see `ReadError` or connection timeout errors, the script is making too many API calls. The latest version uses batch operations to avoid this. If it still happens:
1. Wait a few minutes
2. Run with `--skip-backup --skip-historical` to just add ADOR CSVs
3. The script skips existing rates automatically

### Missing Jurisdictions
Not all jurisdictions have rates in every file. The script creates jurisdictions as needed from the CSV data.

### Duplicate Detection
The script checks for existing rates before inserting and skips duplicates. You can safely re-run the sync multiple times.
