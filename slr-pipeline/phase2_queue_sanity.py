#!/usr/bin/env python3
"""
Phase 2 Queue sanity check.

Verifies that:
  - Items in "Phase 1 - 01-Keep / 00-Queue" actually have s1:*:keep tag
    OR are in a Phase 1 source 01-Keep collection
  - Items in "Phase 1 - 02-Maybe / 00-Queue" actually have s1:*:maybe tag
    OR are in a Phase 1 source 02-Maybe collection

Reports:
  - Items that belong but are missing (should be in queue but aren't)
  - Items that don't belong (are in queue but shouldn't be)
  - Items with conflicting tags (e.g. in keep queue but tagged discard)

Usage:
    python3 phase2_queue_sanity.py
"""
import json

import os
def _load_env_file():
    """Project-scoped .env loader: $ZOTERO_ENV_FILE, else walk up from CWD to
    repo root for .env. Never overwrites already-set env vars. Different
    projects keep different keys by living in different working trees."""
    from pathlib import Path
    cands=[]
    if os.environ.get("ZOTERO_ENV_FILE"):
        cands.append(Path(os.environ["ZOTERO_ENV_FILE"]))
    d=Path.cwd()
    for _ in range(6):
        cands.append(d/".env")
        if (d/".git").exists(): break
        d=d.parent
    for p in cands:
        if p.exists():
            for ln in p.read_text().splitlines():
                ln=ln.split("#",1)[0].strip()
                if "=" in ln:
                    k,v=ln.split("=",1); os.environ.setdefault(k.strip(),v.strip())
            return str(p)
    return None
_load_env_file()
# ZOTERO_SANITIZED: keys read from env / project .env (see .env.example)
import urllib.request
import time
from collections import defaultdict

ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")  # from env / project .env
BASE = "https://api.zotero.org/groups/6505702"
RATE_LIMIT_SEC = 0.3

# Phase 2 collection keys (discovered 2026-05-26)
PHASE2_KEEP_QUEUE   = "JFHGBVLY"   # Phase 1 - 01-Keep / 00-Queue
PHASE2_MAYBE_QUEUE  = "JUDYQCPU"   # Phase 1 - 02-Maybe / 00-Queue

# Phase 1 source 01-Keep and 02-Maybe collection keys
SOURCE_KEEPS = {
    "ieee":             "RP3EIYC7",
    "scopus":           "CZQJI2GN",
    "acm":              "K5QW2C8B",
    "arxiv":            "DKHBF3NP",
    "wos":              "WZEH9TJI",
    "coursework":       "ZT3TKLVS",
    "practitioner":     "WBGJ4YA5",
    "cao":              "GP3U9EX8",
    "naimi-references": "ZXIXRWKG",
    "naimi-chapters":   "DIDV7BKH",
    "ssrn":             "CP5FPT68",
}
SOURCE_MAYBES = {
    "ieee":             "8QZTPYXN",
    "scopus":           "8WKIYV69",
    "acm":              "VMKJ5XZP",
    "arxiv":            "YVBP9QKM",
    "wos":              "WZEH9TJI",
    "coursework":       "ZT3TKLVS",
    "ssrn":             "3QZJEDKF",
    "cao":              "GP3U9EX8",
    "naimi-references": "ZXIXRWKG",
    "naimi-chapters":   "DIDV7BKH",
}

def zget(path):
    req = urllib.request.Request(f"{BASE}{path}")
    req.add_header("Zotero-API-Key", ZOTERO_API_KEY)
    req.add_header("Zotero-API-Version", "3")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def get_all_items(coll_key):
    items = []
    start = 0
    while True:
        data = zget(f"/collections/{coll_key}/items/top?limit=100&start={start}")
        if not data: break
        items.extend(data)
        if len(data) < 100: break
        start += 100
        time.sleep(RATE_LIMIT_SEC)
    return items

def get_collection_item_keys(coll_key):
    return {item["key"] for item in get_all_items(coll_key)}

def item_s1_decisions(item):
    tags = {t.get("tag", "") for t in item.get("data", {}).get("tags", [])}
    decisions = set()
    for tag in tags:
        if tag.startswith("s1:") and any(d in tag for d in [":keep", ":maybe", ":discard"]):
            # e.g. s1:human:keep -> keep
            decisions.add(tag.split(":")[-1])
    return decisions

def union_decision(item):
    """Apply union rule: human overrides claude."""
    tags = {t.get("tag", "") for t in item.get("data", {}).get("tags", [])}
    human = next((t.split(":")[-1] for t in tags if t.startswith("s1:human:")), None)
    claude = next((t.split(":")[-1] for t in tags if t.startswith("s1:claude:")), None)
    return human or claude or None

def main():
    print("=== Phase 2 Queue Sanity Check ===\n")

    # ---- Build set of all Phase 1 Keep and Maybe keys ----
    print("Building Phase 1 Keep/Maybe key sets from source collections...")
    all_keep_keys = set()
    all_maybe_keys = set()

    for src, coll_key in SOURCE_KEEPS.items():
        try:
            keys = get_collection_item_keys(coll_key)
            all_keep_keys |= keys
            print(f"  Keep/{src}: {len(keys)} items")
        except Exception as e:
            print(f"  Keep/{src}: ERROR {e}")

    for src, coll_key in SOURCE_MAYBES.items():
        try:
            keys = get_collection_item_keys(coll_key)
            all_maybe_keys |= keys
            print(f"  Maybe/{src}: {len(keys)} items")
        except Exception as e:
            print(f"  Maybe/{src}: ERROR {e}")

    # Items in both keep and maybe (cross-source edge case)
    in_both = all_keep_keys & all_maybe_keys
    print(f"\nUnique Phase 1 Keep keys: {len(all_keep_keys)}")
    print(f"Unique Phase 1 Maybe keys: {len(all_maybe_keys)}")
    print(f"In both Keep and Maybe: {len(in_both)}")

    # ---- Fetch Phase 2 Queue contents ----
    print(f"\nFetching Phase 2 Keep Queue ({PHASE2_KEEP_QUEUE})...")
    p2_keep_items = get_all_items(PHASE2_KEEP_QUEUE)
    p2_keep_keys = {item["key"] for item in p2_keep_items}
    print(f"  Items in Phase 2 Keep Queue: {len(p2_keep_items)}")

    print(f"Fetching Phase 2 Maybe Queue ({PHASE2_MAYBE_QUEUE})...")
    p2_maybe_items = get_all_items(PHASE2_MAYBE_QUEUE)
    p2_maybe_keys = {item["key"] for item in p2_maybe_items}
    print(f"  Items in Phase 2 Maybe Queue: {len(p2_maybe_items)}")

    # ---- CHECK 1: Items in Phase 2 Keep Queue that aren't Phase 1 Keeps ----
    print(f"\n{'='*60}")
    print("CHECK 1: Items in Phase 2 Keep Queue that are NOT in any Phase 1 Keep collection")
    wrong_in_keep_queue = p2_keep_keys - all_keep_keys
    print(f"  Count: {len(wrong_in_keep_queue)}")
    if wrong_in_keep_queue:
        for key in sorted(wrong_in_keep_queue)[:20]:
            item = next((i for i in p2_keep_items if i["key"] == key), None)
            title = item.get("data", {}).get("title", "")[:70] if item else "?"
            union = union_decision(item) if item else "?"
            in_maybe = "YES" if key in all_maybe_keys else "no"
            print(f"  {key}: union={union} in_phase1_maybe={in_maybe} | {title}")

    # ---- CHECK 2: Items in Phase 2 Maybe Queue that aren't Phase 1 Maybes ----
    print(f"\n{'='*60}")
    print("CHECK 2: Items in Phase 2 Maybe Queue that are NOT in any Phase 1 Maybe collection")
    wrong_in_maybe_queue = p2_maybe_keys - all_maybe_keys
    print(f"  Count: {len(wrong_in_maybe_queue)}")
    if wrong_in_maybe_queue:
        for key in sorted(wrong_in_maybe_queue)[:20]:
            item = next((i for i in p2_maybe_items if i["key"] == key), None)
            title = item.get("data", {}).get("title", "")[:70] if item else "?"
            union = union_decision(item) if item else "?"
            in_keep = "YES" if key in all_keep_keys else "no"
            print(f"  {key}: union={union} in_phase1_keep={in_keep} | {title}")

    # ---- CHECK 3: Tag consistency for items IN the queues ----
    print(f"\n{'='*60}")
    print("CHECK 3: Tag vs Queue placement consistency")
    tag_conflicts = []

    for item in p2_keep_items:
        union = union_decision(item)
        if union and union != "keep":
            tag_conflicts.append({
                "key": item["key"],
                "queue": "Phase2-Keep-Queue",
                "union_decision": union,
                "title": item.get("data", {}).get("title", "")[:70],
            })

    for item in p2_maybe_items:
        union = union_decision(item)
        if union and union != "maybe":
            tag_conflicts.append({
                "key": item["key"],
                "queue": "Phase2-Maybe-Queue",
                "union_decision": union,
                "title": item.get("data", {}).get("title", "")[:70],
            })

    print(f"  Items whose union decision conflicts with their queue placement: {len(tag_conflicts)}")
    for c in tag_conflicts[:20]:
        print(f"  {c['key']} in {c['queue']} but union={c['union_decision']} | {c['title']}")

    # ---- CHECK 4: Phase 1 Keeps missing from Phase 2 Keep Queue ----
    print(f"\n{'='*60}")
    print("CHECK 4: Phase 1 Keeps NOT yet in Phase 2 Keep Queue")
    missing_from_keep_queue = all_keep_keys - p2_keep_keys
    print(f"  Count: {len(missing_from_keep_queue)}")
    if missing_from_keep_queue:
        print(f"  (These items passed Phase 1 Keep but haven't been added to Phase 2 Queue yet)")
        print(f"  First 5 sample keys: {list(missing_from_keep_queue)[:5]}")

    # ---- CHECK 5: Phase 1 Maybes missing from Phase 2 Maybe Queue ----
    print(f"\n{'='*60}")
    print("CHECK 5: Phase 1 Maybes NOT yet in Phase 2 Maybe Queue")
    missing_from_maybe_queue = all_maybe_keys - p2_maybe_keys
    print(f"  Count: {len(missing_from_maybe_queue)}")
    if missing_from_maybe_queue:
        print(f"  (These items passed Phase 1 Maybe but haven't been added to Phase 2 Queue yet)")
        print(f"  First 5 sample keys: {list(missing_from_maybe_queue)[:5]}")

    # ---- SUMMARY ----
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"  Phase 1 Keeps:                    {len(all_keep_keys)}")
    print(f"  Phase 1 Maybes:                   {len(all_maybe_keys)}")
    print(f"  Phase 2 Keep Queue populated:     {len(p2_keep_keys)}")
    print(f"  Phase 2 Maybe Queue populated:    {len(p2_maybe_keys)}")
    print(f"  Wrong items in Keep Queue:        {len(wrong_in_keep_queue)}")
    print(f"  Wrong items in Maybe Queue:       {len(wrong_in_maybe_queue)}")
    print(f"  Tag conflicts:                    {len(tag_conflicts)}")
    print(f"  Missing from Keep Queue:          {len(missing_from_keep_queue)}")
    print(f"  Missing from Maybe Queue:         {len(missing_from_maybe_queue)}")

    if (len(wrong_in_keep_queue) == 0 and len(wrong_in_maybe_queue) == 0 and
            len(tag_conflicts) == 0 and len(missing_from_keep_queue) == 0 and
            len(missing_from_maybe_queue) == 0):
        print("\n✓ All checks passed — Phase 2 queues are correct and complete")
    else:
        print("\n⚠️  Issues found — review output above before proceeding to Phase 2 screening")

if __name__ == "__main__":
    main()
