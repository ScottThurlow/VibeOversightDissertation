#!/usr/bin/env python3
"""
Export Phase 2 Queue items from Zotero to CSV for Pass 2 screening.

Fetches items from both Phase 2 Queue collections (Keep queue and Maybe queue),
deduplicates by item_key, and outputs item_key, title, abstract, source_queue.

Usage:
    python3 export_phase2_queue.py \
        --keep-queue JFHGBVLY \
        --maybe-queue JUDYQCPU \
        --output queue_export.csv
"""
import argparse

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
import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error

ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")  # from env / project .env
LIB = "6505702"
BASE = f"https://api.zotero.org/groups/{LIB}"
RATE_LIMIT_SEC = 0.3

def zget(path, retries=5):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{BASE}{path}")
            req.add_header("Zotero-API-Key", ZOTERO_API_KEY)
            req.add_header("Zotero-API-Version", "3")
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    return []

def get_all_items(coll_key):
    items = []
    start = 0
    while True:
        data = zget(f"/collections/{coll_key}/items/top?limit=100&start={start}")
        if not data:
            break
        items.extend(data)
        if len(data) < 100:
            break
        start += 100
        time.sleep(RATE_LIMIT_SEC)
    return items

def extract_abstract(item):
    return (item.get("data", {}).get("abstractNote", "") or "").strip()

def extract_authors(item):
    creators = item.get("data", {}).get("creators", [])
    authors = []
    for c in creators[:5]:
        last = c.get("lastName", "") or c.get("name", "")
        if last:
            authors.append(last)
    return "; ".join(authors)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-queue",  required=True)
    parser.add_argument("--maybe-queue", required=True)
    parser.add_argument("--output",      required=True)
    args = parser.parse_args()

    print(f"Fetching Phase 2 Keep Queue ({args.keep_queue})...")
    keep_items = get_all_items(args.keep_queue)
    print(f"  {len(keep_items)} items")

    print(f"Fetching Phase 2 Maybe Queue ({args.maybe_queue})...")
    maybe_items = get_all_items(args.maybe_queue)
    print(f"  {len(maybe_items)} items")

    # Merge, deduplicate, track source queue
    seen = {}
    for item in keep_items:
        k = item["key"]
        if k not in seen:
            seen[k] = ("keep_queue", item)

    for item in maybe_items:
        k = item["key"]
        if k not in seen:
            seen[k] = ("maybe_queue", item)
        else:
            # In both queues — note it
            seen[k] = ("both_queues", seen[k][1])

    print(f"Total unique items: {len(seen)}")
    in_both = sum(1 for q, _ in seen.values() if q == "both_queues")
    if in_both:
        print(f"  Items in both queues: {in_both}")

    # Write output
    fieldnames = ["item_key", "title", "abstract", "authors", "year",
                  "item_type", "sources", "source_queue"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key, (source_queue, item) in seen.items():
            d = item.get("data", {})
            tags = [t.get("tag", "") for t in d.get("tags", [])]
            sources = "|".join(sorted(
                t.replace("source:", "")
                for t in tags if t.startswith("source:")
            ))
            writer.writerow({
                "item_key":    key,
                "title":       d.get("title", ""),
                "abstract":    extract_abstract(item),
                "authors":     extract_authors(item),
                "year":        (d.get("date", "") or "")[:4],
                "item_type":   d.get("itemType", ""),
                "sources":     sources,
                "source_queue": source_queue,
            })

    print(f"Written to {args.output}")

if __name__ == "__main__":
    main()
