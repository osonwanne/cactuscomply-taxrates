"""
Fix orphan 100x-bug rows that 008 cannot reach (no CSV counterpart).

The "1% stored as 100%" bug left some rows 100x too high. 008 corrects rows
that match a source CSV. A few special-district / tribal rows (extension &
redevelopment taxes) are not in the monthly ADOR CSV at all, so they need a
threshold-based fix instead.

No legitimate AZ TPT rate approaches 20%, so any stored rate above the
threshold (default 0.20) is certainly the bug and is divided by 100.
Default is a dry run; pass --apply to write.

Usage:
    python scripts/010_fix_high_rate_100x.py <version_id>
    python scripts/010_fix_high_rate_100x.py 112 --apply
    python scripts/010_fix_high_rate_100x.py 9 --apply --threshold 0.20
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

supabase: Client = create_client(
    os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    threshold = 0.20
    if "--threshold" in sys.argv:
        threshold = float(sys.argv[sys.argv.index("--threshold") + 1])
    if not args:
        print("Usage: python scripts/010_fix_high_rate_100x.py <version_id> "
              "[--apply] [--threshold 0.20]")
        return
    version_id = int(args[0])

    print("=" * 60)
    print(f"FIX 100x rows  version {version_id}  threshold>{threshold}  "
          f"MODE: {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 60)

    rows = supabase.table("rates").select(
        "id, jurisdiction_id, business_code, state_rate, county_rate, "
        "city_rate, total_rate"
    ).eq("rate_version_id", version_id).gt("total_rate", threshold).execute().data

    print(f"Rows above threshold (will be /100): {len(rows)}")
    if not rows:
        print("\nNothing to fix.")
        return

    juris = {j["id"]: j for j in supabase.table("jurisdictions").select(
        "id, city_name, county_name, level").execute().data}

    for r in rows:
        j = juris.get(r["jurisdiction_id"], {})
        nm = j.get("county_name") if j.get("level") == "county" else j.get("city_name")
        print(f"  {nm or '?'} / {r['business_code']:>4}   "
              f"{float(r['total_rate']):.4%} -> {float(r['total_rate']) / 100:.4%}")

    if not apply:
        print(f"\nDRY RUN — re-run with --apply to fix {len(rows)} rows.")
        return

    print(f"\nApplying {len(rows)} corrections...")
    fixed = 0
    for r in rows:
        supabase.table("rates").update({
            "state_rate": round(float(r["state_rate"] or 0) / 100, 6),
            "county_rate": round(float(r["county_rate"] or 0) / 100, 6),
            "city_rate": round(float(r["city_rate"] or 0) / 100, 6),
        }).eq("id", r["id"]).execute()
        fixed += 1
    print(f"Done — {fixed} rows corrected in rate_version {version_id}.")


if __name__ == "__main__":
    main()
