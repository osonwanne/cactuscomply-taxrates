# 2026-05-21 — Rate 100× Bug Eradication + Date-Aware Rate Versioning

Session covering the May/June 2026 ADOR rate loads, a full cleanup of the
"1% stored as 100%" bug across every historical rate version, and making the
"current rate" resolution date-aware so future months can be pre-loaded
safely.

## Monthly loads

| Version | Effective | Rows | Notes |
|---------|-----------|------|-------|
| v116 | 2026-05-01 | 4592 | May 2026 ADOR table |
| v117 | 2026-06-01 | 4593 | June 2026 — pre-loaded, dormant until 2026-06-01 |

Both loaded with `scripts/004_add_monthly_rates.py`. June vs May: 0 real rate
changes, 1 new rate (Tucson / code 445 @ 4.5%). Peoria 214 (1.8%) and
Maricopa 014 (6.3%) unchanged — no Stripe impact.

## The 100× bug ("1% stored as 100%")

The old loader only divided a CSV rate by 100 when it was `> 1`. Every ADOR
rate of 1% or less was therefore stored 100× too high (e.g. a 0.5% rate
stored as `0.5` = 50%). Commits `bd31a28` / `74844c2` (2026-03-31) fixed the
*script* but never backfilled data already loaded.

**Result of this session: all 107 rate_versions swept — 0 rows with
`total_rate > 0.20` remaining.** No legitimate AZ TPT rate approaches 20%, so
that threshold cleanly separates bug rows from real rates.

### How each version was fixed

- **CSV-matched fix** — `008_verify_version_against_csv.py` re-parses a
  version's own ADOR CSV with the corrected logic and corrects any stored row
  that disagrees. Used for v9, v10, v110–v116 (CSVs available in Downloads).
- **Orphan/threshold fix** — `010_fix_high_rate_100x.py` divides any row with
  `total_rate > 0.20` by 100. Used for rows absent from any CSV (special-
  district extension taxes — codes 003/303/370) and for the 13 small pre-2025
  versions with no CSV on hand: v18, v19, v20, v22, v27, v30, v40, v43, v54,
  v66, v78, v85, v108.

### Two special cases

- **v10 (Nov 2025) was duplicate-loaded** — 8004 rows ≈ 2× normal. Deduped to
  4613 with `009_dedup_version_rows.py` (every duplicate group was verified
  identical-valued before removal), then 100× fixed.
- **v111 (Sep 2025) — ADOR source error.** The Sep 2025 ADOR CSV *itself*
  lists codes 185 and 350 at `100`. This is bad source data, not our storage
  bug. Both codes are 1% in every other version (v9, v38, v67), so the rows
  were corrected to 1%. Caution: re-running `008` on v111 would "restore" the
  bad 100% from the CSV — do not.

## Date-aware rate versioning

**Problem:** "current rates" resolved to the absolute `MAX(effective_date)`.
The moment a future month was pre-loaded, it went live immediately — before
its effective date.

**Fixed in three places**, all now resolving via `effective_date <= today`:

1. **`current_rates` view** — see `cactuscomply-integrations/migrations/
   341_current_rates_view_date_aware.sql` (applied to project
   `deewovpugkzskjudmvej`).
2. **`007_sync_stripe_tax_rates.py`** — `get_current_version()` picks the
   latest version whose effective date has arrived, so a pre-loaded future
   month does not push tax rates to Stripe early.
3. **`cactuscomply-integrations/services/ador_service.py`** —
   `get_current_tax_rates()` (endpoint `GET /api/ador/tax-rates/`) gained the
   same `.lte("effective_date", today)` guard.

**Historical / period lookups were already correct** — `enrichment_service`
rates each transaction by its own transaction date, and
`xml_generation_service` rates county lines by the filing period start. Both
cap at `effective_date <= period/txn date`, so pre-loaded future months
cannot affect historical or amended filings.

## New scripts (in `scripts/`)

| Script | Purpose |
|--------|---------|
| `004_dry_run.py` | Read-only drift check of a monthly CSV vs the prior version |
| `008_verify_version_against_csv.py` | Verify / fix a stored version against its own ADOR CSV. UPDATE-only — never deletes |
| `009_dedup_version_rows.py` | Remove duplicate rows within a version (keeps lowest id; refuses groups with differing rates) |
| `010_fix_high_rate_100x.py` | Threshold fix (`>0.20` → `/100`) for orphan rows absent from any CSV |

Note: `008` originally paginated the `rates` fetch without an `ORDER BY`,
causing page-boundary drift between runs — fixed by adding `.order("id")`.

## Commits & deploy

- `cactuscomply-taxrates` — `a71f058` (new scripts + date-aware `007`).
- `cactuscomply-integrations` — `e355010` (migration 341 + `ador_service.py`
  guard); deployed live on DigitalOcean. Follow-up `3551cb6` updates a unit
  test mock for the new query chain.

## Open / follow-up

- 13 small pre-2025 versions are fixed; if any *other* historical period is
  ever amended, re-verify that version first.
- `004_add_monthly_rates.py` still has no built-in dry-run flag — use
  `004_dry_run.py` separately before each monthly load.
