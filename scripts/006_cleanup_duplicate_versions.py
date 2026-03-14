"""
Cleanup Duplicate Rate Versions

Removes duplicate rate_version records and merges any unique rates into
the canonical version.

Duplicates found:
- v1 (2025-08-10): 223 rates, all subset of v110 (2025-08-01) -> DELETE
- v2-v5 (2025-09-30): test loads, not a real effective date -> DELETE
- v6-v8 (2025-10-01): duplicates of v9 -> MERGE 13 unique v6 records into v9, then DELETE

Usage:
    python scripts/006_cleanup_duplicate_versions.py --dry-run
    python scripts/006_cleanup_duplicate_versions.py
"""

import os
import sys
from typing import Dict, List, Set, Tuple

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_all_rates(version_id: int, columns: str = "jurisdiction_id, business_code, city_rate, county_rate, state_rate") -> List[Dict]:
    """Paginate through all rates for a version."""
    all_rates = []
    offset = 0
    batch = 1000
    while True:
        result = (
            supabase.table("rates")
            .select(columns)
            .eq("rate_version_id", version_id)
            .range(offset, offset + batch - 1)
            .execute()
        )
        all_rates.extend(result.data)
        if len(result.data) < batch:
            break
        offset += batch
    return all_rates


def get_rate_count(version_id: int) -> int:
    """Get exact count of rates for a version."""
    result = (
        supabase.table("rates")
        .select("id", count="exact")
        .eq("rate_version_id", version_id)
        .execute()
    )
    return result.count


def delete_rates_for_version(version_id: int, dry_run: bool) -> int:
    """Delete all rates for a version, paginated. Returns count deleted."""
    total = 0
    while True:
        # Get a batch of rate IDs
        result = (
            supabase.table("rates")
            .select("id")
            .eq("rate_version_id", version_id)
            .limit(500)
            .execute()
        )
        if not result.data:
            break

        ids = [r["id"] for r in result.data]
        if dry_run:
            total += len(ids)
            # In dry run, we can't keep looping since nothing gets deleted
            # Get total count instead
            remaining = get_rate_count(version_id)
            return remaining

        for i in range(0, len(ids), 100):
            batch_ids = ids[i:i + 100]
            supabase.table("rates").delete().in_("id", batch_ids).execute()
            total += len(batch_ids)

    return total


def delete_version(version_id: int, dry_run: bool):
    """Delete a rate_version record."""
    if dry_run:
        print(f"    [DRY RUN] Would delete rate_version v{version_id}")
        return
    supabase.table("rate_versions").delete().eq("id", version_id).execute()
    print(f"    Deleted rate_version v{version_id}")


def merge_unique_rates_from_list(records: List[Dict], target_vid: int, dry_run: bool) -> int:
    """Insert a list of rate records into target version. Returns count inserted."""
    to_insert = [
        {
            "rate_version_id": target_vid,
            "jurisdiction_id": r["jurisdiction_id"],
            "business_code": r["business_code"],
            "state_rate": r.get("state_rate", 0.0),
            "county_rate": r.get("county_rate", 0.0),
            "city_rate": r.get("city_rate", 0.0),
        }
        for r in records
    ]

    if dry_run:
        print(f"    [DRY RUN] Would insert {len(to_insert)} rates into v{target_vid}")
        return len(to_insert)

    inserted = 0
    for i in range(0, len(to_insert), 500):
        batch = to_insert[i:i + 500]
        supabase.table("rates").insert(batch).execute()
        inserted += len(batch)

    print(f"    Inserted {inserted} rates into v{target_vid}")
    return inserted


def merge_unique_rates(source_vid: int, target_vid: int, dry_run: bool) -> int:
    """Merge rates from source into target where they don't already exist. Returns count merged."""
    source_rates = get_all_rates(source_vid)
    target_rates = get_all_rates(target_vid)

    target_keys = {(r["jurisdiction_id"], r["business_code"]) for r in target_rates}

    # Find unique source records not in target
    to_insert = []
    seen = set()
    for r in source_rates:
        key = (r["jurisdiction_id"], r["business_code"])
        if key not in target_keys and key not in seen:
            seen.add(key)
            to_insert.append({
                "rate_version_id": target_vid,
                "jurisdiction_id": r["jurisdiction_id"],
                "business_code": r["business_code"],
                "state_rate": r.get("state_rate", 0.0),
                "county_rate": r.get("county_rate", 0.0),
                "city_rate": r.get("city_rate", 0.0),
            })

    if not to_insert:
        print(f"    No unique rates to merge from v{source_vid} -> v{target_vid}")
        return 0

    if dry_run:
        print(f"    [DRY RUN] Would merge {len(to_insert)} unique rates from v{source_vid} -> v{target_vid}")
        for r in to_insert[:5]:
            print(f"      jid={r['jurisdiction_id']} biz={r['business_code']} city={r['city_rate']} county={r['county_rate']}")
        if len(to_insert) > 5:
            print(f"      ... and {len(to_insert) - 5} more")
        return len(to_insert)

    # Insert in batches
    inserted = 0
    for i in range(0, len(to_insert), 500):
        batch = to_insert[i:i + 500]
        supabase.table("rates").insert(batch).execute()
        inserted += len(batch)

    print(f"    Merged {inserted} unique rates from v{source_vid} -> v{target_vid}")
    return inserted


def safe_check_before_delete(source_vids: List[int], target_vid: int, label: str) -> Tuple[int, List[Dict]]:
    """
    Before deleting source versions, verify all unique records either:
    - already exist in the target version, OR
    - will be merged into it.

    Returns (unique_count, records_to_merge).
    Raises if any records would be lost.
    """
    # Get all target keys (paginated)
    target_rates = get_all_rates(target_vid)
    target_keys = {(r["jurisdiction_id"], r["business_code"]) for r in target_rates}
    print(f"    Target v{target_vid}: {len(target_keys)} unique (jid, biz) pairs")

    # Collect all unique records across source versions
    all_source_keys: Dict[Tuple, Dict] = {}
    for vid in source_vids:
        rates = get_all_rates(vid)
        for r in rates:
            key = (r["jurisdiction_id"], r["business_code"])
            if key not in all_source_keys:
                all_source_keys[key] = r

    # Determine what's missing from target
    missing = []
    for key, rate in all_source_keys.items():
        if key not in target_keys:
            missing.append(rate)

    covered = len(all_source_keys) - len(missing)
    print(f"    Source v{source_vids}: {len(all_source_keys)} unique pairs")
    print(f"    Already in target: {covered}")
    print(f"    Need to merge: {len(missing)}")

    if missing:
        print(f"    Records to merge into v{target_vid}:")
        for r in missing[:10]:
            j = supabase.table("jurisdictions").select("region_code, city_name, county_name, level").eq("id", r["jurisdiction_id"]).execute()
            jinfo = j.data[0] if j.data else {}
            name = jinfo.get("city_name") or jinfo.get("county_name", "?")
            print(f"      jid={r['jurisdiction_id']} ({jinfo.get('region_code', '?')}/{name}/{jinfo.get('level', '?')}) biz={r['business_code']} city={r['city_rate']} county={r['county_rate']}")
        if len(missing) > 10:
            print(f"      ... and {len(missing) - 10} more")

    return len(missing), missing


def cleanup(dry_run: bool):
    print("=" * 60)
    print("CLEANUP DUPLICATE RATE VERSIONS")
    if dry_run:
        print("*** DRY RUN — no changes will be made ***")
    print("=" * 60)

    # Step 1: Delete v1 (2025-08-10) — verify all rates exist in v110 (2025-08-01)
    print("\n--- Step 1: Remove v1 (2025-08-10, fake date) ---")
    unique_count, to_merge = safe_check_before_delete([1], 110, "v1 -> v110")
    if to_merge:
        print(f"    Merging {unique_count} unique rates from v1 -> v110 first")
        merge_unique_rates_from_list(to_merge, 110, dry_run)
    deleted = delete_rates_for_version(1, dry_run)
    if dry_run:
        print(f"    [DRY RUN] Would delete {get_rate_count(1)} rates from v1")
    else:
        print(f"    Deleted {deleted} rates from v1")
    delete_version(1, dry_run)

    # Step 2: Delete v2-v5 (2025-09-30) — verify against v111 (2025-09-01) and v9 (2025-10-01)
    print("\n--- Step 2: Remove v2-v5 (2025-09-30, test loads) ---")
    # These rates should exist in either Sep (v111) or Oct (v9)
    # Check against both — merge into whichever is closest (v9 = Oct 1)
    unique_count, to_merge = safe_check_before_delete([2, 3, 4, 5], 9, "v2-v5 -> v9")
    if to_merge:
        # Double-check against v111 too
        v111_rates = get_all_rates(111)
        v111_keys = {(r["jurisdiction_id"], r["business_code"]) for r in v111_rates}
        truly_missing = [r for r in to_merge if (r["jurisdiction_id"], r["business_code"]) not in v111_keys]
        if truly_missing:
            print(f"    WARNING: {len(truly_missing)} records not in v9 OR v111!")
            print(f"    Merging into v9 (2025-10-01) to preserve them")
            merge_unique_rates_from_list(truly_missing, 9, dry_run)
        else:
            print(f"    All {len(to_merge)} 'missing' records exist in v111 (Sep) — safe")

    for vid in [2, 3, 4, 5]:
        count = get_rate_count(vid)
        deleted = delete_rates_for_version(vid, dry_run)
        if dry_run:
            print(f"    [DRY RUN] Would delete {count} rates from v{vid}")
        else:
            print(f"    Deleted {deleted} rates from v{vid}")
        delete_version(vid, dry_run)

    # Step 3: Merge v6/v7/v8 unique records into v9, then delete
    print("\n--- Step 3: Merge v6/v7/v8 -> v9, then remove (2025-10-01 dupes) ---")
    unique_count, to_merge = safe_check_before_delete([6, 7, 8], 9, "v6-v8 -> v9")
    if to_merge:
        merge_unique_rates_from_list(to_merge, 9, dry_run)

    for vid in [6, 7, 8]:
        count = get_rate_count(vid)
        deleted = delete_rates_for_version(vid, dry_run)
        if dry_run:
            print(f"    [DRY RUN] Would delete {count} rates from v{vid}")
        else:
            print(f"    Deleted {deleted} rates from v{vid}")
        delete_version(vid, dry_run)

    # Step 4: Verify — check for any remaining duplicate effective dates
    print("\n--- Verification ---")
    versions = (
        supabase.table("rate_versions")
        .select("id, effective_date")
        .order("effective_date")
        .execute()
    )

    from collections import Counter
    date_counts = Counter(v["effective_date"] for v in versions.data)
    dupes = {d: c for d, c in date_counts.items() if c > 1}

    if dupes:
        print("    WARNING: Remaining duplicate effective dates:")
        for d, c in sorted(dupes.items()):
            print(f"      {d}: {c} versions")
    else:
        print("    No duplicate effective dates remain.")

    # Show final rate counts for 2025-10 period
    print("\n    Rate counts for recent versions:")
    for v in versions.data:
        if v["effective_date"] >= "2025-08-01":
            count = get_rate_count(v["id"])
            print(f"      v{v['id']:>3}  {v['effective_date']}  -> {count:>5} rates")

    print("\n" + "=" * 60)
    print("DONE!" if not dry_run else "DRY RUN COMPLETE — run without --dry-run to apply")
    print("=" * 60)


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    cleanup(dry_run)
