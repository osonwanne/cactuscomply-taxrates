"""
De-duplicate rows within a single rate_version.

Some versions were loaded multiple times, leaving several identical rows for
the same (jurisdiction_id, business_code). This keeps the lowest-id row per
pair and deletes the rest.

Safety: if any duplicate group has DIFFERING rate values, that group is NOT
touched and is reported — dedup only proceeds where the extra rows are proven
redundant. Default is a dry run; pass --apply to delete.

Usage:
    python scripts/009_dedup_version_rows.py <version_id>
    python scripts/009_dedup_version_rows.py 10 --apply
"""

import os
import sys
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

supabase: Client = create_client(
    os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY'))


def fetch_all(version_id: int) -> List[dict]:
    rows: List[dict] = []
    start, page = 0, 1000
    while True:
        res = supabase.table("rates").select(
            "id, jurisdiction_id, business_code, state_rate, county_rate, city_rate"
        ).eq("rate_version_id", version_id).order("id").range(
            start, start + page - 1).execute()
        rows.extend(res.data)
        if len(res.data) < page:
            break
        start += page
    return rows


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if not args:
        print("Usage: python scripts/009_dedup_version_rows.py <version_id> [--apply]")
        return
    version_id = int(args[0])

    print("=" * 60)
    print(f"DEDUP rate_version {version_id}   "
          f"MODE: {'APPLY' if apply else 'DRY RUN'}")
    print("=" * 60)

    rows = fetch_all(version_id)
    print(f"Total rows: {len(rows)}")

    groups: Dict[Tuple[int, str], List[dict]] = {}
    for r in rows:
        groups.setdefault(
            (r["jurisdiction_id"], (r["business_code"] or "").strip()), []
        ).append(r)
    print(f"Distinct (jurisdiction, business_code) pairs: {len(groups)}")

    delete_ids: List[int] = []
    conflict_groups = 0
    for key, grp in groups.items():
        if len(grp) == 1:
            continue
        vals = {(str(r["state_rate"]), str(r["county_rate"]), str(r["city_rate"]))
                for r in grp}
        if len(vals) > 1:
            conflict_groups += 1
            print(f"  CONFLICT (left untouched): juris={key[0]} code={key[1]} "
                  f"-> {len(grp)} rows with {len(vals)} distinct rate sets")
            continue
        keep = min(grp, key=lambda r: r["id"])
        delete_ids.extend(r["id"] for r in grp if r["id"] != keep["id"])

    print(f"\nDuplicate rows to delete: {len(delete_ids)}")
    print(f"Conflict groups skipped : {conflict_groups}")
    print(f"Rows after dedup        : {len(rows) - len(delete_ids)}")

    if not delete_ids:
        print("\nNothing to dedup.")
        return
    if not apply:
        print("\nDRY RUN — re-run with --apply to delete.")
        return

    print(f"\nDeleting {len(delete_ids)} rows...")
    deleted = 0
    for i in range(0, len(delete_ids), 200):
        batch = delete_ids[i:i + 200]
        supabase.table("rates").delete().in_("id", batch).execute()
        deleted += len(batch)
        print(f"  ...{deleted}/{len(delete_ids)}")
    print(f"Done — {deleted} duplicate rows removed from rate_version {version_id}.")


if __name__ == "__main__":
    main()
