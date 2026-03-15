"""
Sync Stripe Tax Rates with CactusComply Tax Rates DB

Monitors tax rates for CactusComply's business address (8427 W Salter Dr, Peoria, AZ 85382)
and updates Stripe tax rates on all active subscriptions when rates change.

Jurisdiction mapping:
  - PE (Peoria, city, id=198): Business Code 214 - Rental, Leasing and Licensing for Use of TPP
  - MAR (Maricopa County, id=71): Business Code 014 - Personal Property Rental

Auto-triggered by 004_add_monthly_rates.py after CSV ingestion.
Can also be run standalone.

Usage:
    python scripts/007_sync_stripe_tax_rates.py              # Check & sync now
    python scripts/007_sync_stripe_tax_rates.py --dry-run     # Preview changes without applying
    python scripts/007_sync_stripe_tax_rates.py --force       # Force update even if rates unchanged

Requires STRIPE_SECRET_KEY in .env (or environment variable).
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# --- Config ---

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# CactusComply business address: 8427 W Salter Dr, Peoria, AZ 85382
PEORIA_JURISDICTION_ID = 198       # PE - Peoria (city)
MARICOPA_JURISDICTION_ID = 71      # MAR - Maricopa County
PEORIA_BUSINESS_CODE = "214"       # Rental, Leasing and Licensing for Use of TPP
MARICOPA_BUSINESS_CODE = "014"     # Personal Property Rental

# File to track last-synced rates (stored alongside this script)
STATE_FILE = Path(__file__).parent / ".stripe_tax_sync_state.json"

# --- Helpers ---

def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_stripe():
    """Import and configure stripe. Fails fast if not installed or key missing."""
    if not STRIPE_SECRET_KEY:
        print("ERROR: STRIPE_SECRET_KEY must be set in .env or environment")
        print("  Get it from https://dashboard.stripe.com/apikeys")
        sys.exit(1)
    try:
        import stripe
    except ImportError:
        print("ERROR: stripe package not installed. Run: pip install stripe")
        sys.exit(1)
    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


def load_state() -> dict:
    """Load last-synced state from disk."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    """Persist sync state to disk."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_current_rates(sb: Client) -> dict:
    """Fetch the latest rates for Peoria (214) and Maricopa County (014)."""
    rates = {}

    # Peoria city rate
    result = (
        sb.table("rates")
        .select("city_rate, county_rate, rate_version_id, rate_versions!inner(effective_date)")
        .eq("jurisdiction_id", PEORIA_JURISDICTION_ID)
        .eq("business_code", PEORIA_BUSINESS_CODE)
        .order("rate_version_id", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        row = result.data[0]
        rates["peoria"] = {
            "rate": float(row["city_rate"]),
            "effective_date": row["rate_versions"]["effective_date"],
            "jurisdiction": "Peoria",
            "business_code": PEORIA_BUSINESS_CODE,
            "description": "Rental, Leasing and Licensing for Use of TPP",
        }

    # Maricopa county rate
    result = (
        sb.table("rates")
        .select("city_rate, county_rate, rate_version_id, rate_versions!inner(effective_date)")
        .eq("jurisdiction_id", MARICOPA_JURISDICTION_ID)
        .eq("business_code", MARICOPA_BUSINESS_CODE)
        .order("rate_version_id", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        row = result.data[0]
        rates["maricopa"] = {
            "rate": float(row["county_rate"]),
            "effective_date": row["rate_versions"]["effective_date"],
            "description": "Personal Property Rental",
            "jurisdiction": "Maricopa County",
            "business_code": MARICOPA_BUSINESS_CODE,
        }

    return rates


def rates_changed(current: dict, previous: dict) -> bool:
    """Check if rates differ from last sync."""
    if not previous:
        return True
    for key in ["peoria", "maricopa"]:
        if key not in current or key not in previous:
            return True
        if current[key]["rate"] != previous.get(key, {}).get("rate"):
            return True
    return False


def find_or_create_tax_rate(stripe, display_name: str, percentage: float, jurisdiction: str, metadata: dict) -> str:
    """Find existing Stripe tax rate matching our metadata, or create a new one.

    Stripe tax rates are immutable — if rate changes, we create a new one and
    archive the old. We match on metadata['cactuscomply_key'] to find ours.
    """
    cc_key = metadata.get("cactuscomply_key", "")

    # Search existing active tax rates
    tax_rates = stripe.TaxRate.list(active=True, limit=100)
    for tr in tax_rates.auto_paging_iter():
        if tr.metadata.get("cactuscomply_key") == cc_key:
            # Found our rate — check if percentage matches
            if float(tr.percentage) == round(percentage * 100, 4):
                print(f"  ✓ Existing Stripe tax rate {tr.id} matches ({tr.percentage}%)")
                return tr.id
            else:
                # Rate changed — archive old one
                print(f"  → Archiving old tax rate {tr.id} ({tr.percentage}%)")
                stripe.TaxRate.modify(tr.id, active=False)
                break

    # Create new tax rate
    pct = round(percentage * 100, 4)  # Convert decimal to percentage (0.018 → 1.8)
    tr = stripe.TaxRate.create(
        display_name=display_name,
        description=f"AZ TPT - {jurisdiction} ({metadata.get('business_code', '')})",
        percentage=pct,
        inclusive=False,
        jurisdiction="AZ",
        country="US",
        metadata=metadata,
    )
    print(f"  ✓ Created new Stripe tax rate {tr.id} ({pct}%)")
    return tr.id


def update_all_subscriptions(stripe, tax_rate_ids: list, dry_run: bool = False):
    """Update all active subscriptions to use the given tax rates."""
    updated = 0
    skipped = 0

    subs = stripe.Subscription.list(status="active", limit=100)
    for sub in subs.auto_paging_iter():
        current_rate_ids = [tr.id for tr in (sub.default_tax_rates or [])]
        if set(current_rate_ids) == set(tax_rate_ids):
            skipped += 1
            continue

        if dry_run:
            print(f"  [DRY RUN] Would update subscription {sub.id}")
            updated += 1
            continue

        stripe.Subscription.modify(sub.id, default_tax_rates=tax_rate_ids)
        updated += 1

    print(f"\n  Subscriptions updated: {updated}")
    if skipped:
        print(f"  Subscriptions already correct: {skipped}")


# --- Main ---

def run_stripe_sync(dry_run: bool = False, force: bool = False):
    """Callable entry point for use by other scripts (e.g. 004_add_monthly_rates.py)."""
    _sync(dry_run=dry_run, force=force)


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    _sync(dry_run=dry_run, force=force)


def _sync(dry_run: bool = False, force: bool = False):
    print("=" * 60)
    print("CactusComply → Stripe Tax Rate Sync")
    print(f"Address: 8427 W Salter Dr, Peoria, AZ 85382")
    print(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if dry_run:
        print("MODE: DRY RUN (no changes will be made)")
    print("=" * 60)

    # 1. Fetch current rates from Supabase
    print("\n1. Fetching current tax rates from database...")
    sb = get_supabase()
    current_rates = fetch_current_rates(sb)

    if "peoria" not in current_rates or "maricopa" not in current_rates:
        print("ERROR: Could not fetch one or both rates from database")
        print(f"  Found: {list(current_rates.keys())}")
        sys.exit(1)

    peoria = current_rates["peoria"]
    maricopa = current_rates["maricopa"]
    print(f"  PE  - Peoria (214):          {peoria['rate'] * 100:.1f}% (effective {peoria['effective_date']})")
    print(f"  MAR - Maricopa County (014): {maricopa['rate'] * 100:.1f}% (effective {maricopa['effective_date']})")

    # 2. Check if rates changed
    print("\n2. Checking for rate changes...")
    previous_state = load_state()
    previous_rates = previous_state.get("rates", {})

    if not force and not rates_changed(current_rates, previous_rates):
        print("  No rate changes detected. Stripe is up to date.")
        print("  (Use --force to update anyway)")
        return

    if previous_rates:
        for key in ["peoria", "maricopa"]:
            old = previous_rates.get(key, {}).get("rate", "N/A")
            new = current_rates[key]["rate"]
            if old != new:
                old_pct = f"{old * 100:.1f}%" if isinstance(old, (int, float)) else old
                print(f"  CHANGED: {current_rates[key]['jurisdiction']}: {old_pct} → {new * 100:.1f}%")
            else:
                print(f"  Unchanged: {current_rates[key]['jurisdiction']}: {new * 100:.1f}%")
    else:
        print("  First sync — will create Stripe tax rates")

    # 3. Create/update Stripe tax rates
    print("\n3. Syncing Stripe tax rates...")
    stripe = get_stripe()

    peoria_tr_id = find_or_create_tax_rate(
        stripe,
        display_name="AZ TPT - Peoria",
        percentage=peoria["rate"],
        jurisdiction="Peoria",
        metadata={
            "cactuscomply_key": "peoria_214",
            "jurisdiction_id": str(PEORIA_JURISDICTION_ID),
            "business_code": PEORIA_BUSINESS_CODE,
            "effective_date": peoria["effective_date"],
        },
    )

    maricopa_tr_id = find_or_create_tax_rate(
        stripe,
        display_name="AZ TPT - Maricopa County",
        percentage=maricopa["rate"],
        jurisdiction="Maricopa County",
        metadata={
            "cactuscomply_key": "maricopa_014",
            "jurisdiction_id": str(MARICOPA_JURISDICTION_ID),
            "business_code": MARICOPA_BUSINESS_CODE,
            "effective_date": maricopa["effective_date"],
        },
    )

    tax_rate_ids = [peoria_tr_id, maricopa_tr_id]

    # 4. Update all active subscriptions
    print("\n4. Updating active subscriptions...")
    update_all_subscriptions(stripe, tax_rate_ids, dry_run=dry_run)

    # 5. Save state
    if not dry_run:
        save_state({
            "rates": current_rates,
            "stripe_tax_rate_ids": {
                "peoria": peoria_tr_id,
                "maricopa": maricopa_tr_id,
            },
            "last_synced": datetime.now().isoformat(),
        })
        print(f"\n  State saved to {STATE_FILE}")

    print("\n" + "=" * 60)
    total = current_rates["peoria"]["rate"] + current_rates["maricopa"]["rate"]
    print(f"Total tax rate on subscriptions: {total * 100:.1f}% ({peoria['rate'] * 100:.1f}% + {maricopa['rate'] * 100:.1f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
