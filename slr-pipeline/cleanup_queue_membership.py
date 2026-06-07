#!/usr/bin/env python3
"""
One-time cleanup: remove items from 00-Queue that already belong to a
decision bucket (01-Keep, 02-Maybe, or 03-Discard) in the same source.

This fixes the side-effect of the original apply_screening_decisions.py run
which added items to decision buckets but did not remove them from 00-Queue.

Works across ALL sources (not just SSRN). Safe to run multiple times —
only removes Queue membership when a decision bucket membership also exists.

Usage:
    python3 cleanup_queue_membership.py              # dry-run
    python3 cleanup_queue_membership.py --apply      # write changes
    python3 cleanup_queue_membership.py --source ssrn --apply  # one source only
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
import json
import os
import sys
import time
import random
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
ZOTERO_API_KEY_RO = os.environ.get("VCSLR_ZOTERO_READ_KEY") or os.environ.get("ZOTERO_API_KEY", "")  # VCSLR read key (env / project .env)
ZOTERO_API_KEY_RW = os.environ.get("VCSLR_ZOTERO_WRITE_KEY") or os.environ.get("ZOTERO_WRITE_KEY", "")  # VCSLR write key (inline at --apply)
LIB = os.environ.get("VCSLR_ZOTERO_LIBRARY_ID", "6505702")
BASE = f"https://api.zotero.org/groups/{LIB}"
RATE_LIMIT_SEC = 0.3

SCREENING_PARENTS = {
    "ieee":             "7XHWH8NM",
    "scopus":           "2RWBC7QH",
    "wos":              "E7AS4HD4",
    "arxiv":            "YK2CHQLN",
    "acm":              "G4IIYGV6",
    "practitioner":     "7FL4M8HN",
    "coursework":       "IF299TAY",
    "cao":              "GP3U9EX8",
    "naimi-references": "ZXIXRWKG",
    "naimi-chapters":   "DIDV7BKH",
    "ssrn":             "F9A9883N",
}

DECISION_BUCKET_NAMES = {"01-Keep", "02-Maybe", "03-Discard"}
QUEUE_NAME = "00-Queue"

LOG_FILE = "cleanup_queue.log"

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ============================================================
# ZOTERO API
# ============================================================
def zot_request(method, path, body=None, api_key=None, headers=None, retries=8):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Zotero-API-Key", api_key or ZOTERO_API_KEY_RO)
            req.add_header("Zotero-API-Version", "3")
            if data:
                req.add_header("Content-Type", "application/json")
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=60) as r:
                body_text = r.read().decode("utf-8") if r.length != 0 else ""
                try:
                    return True, json.loads(body_text) if body_text else {}, dict(r.headers)
                except json.JSONDecodeError:
                    return True, body_text, dict(r.headers)
        except urllib.error.HTTPError as e:
            err = ""
            try: err = e.read().decode("utf-8", errors="replace")[:300]
            except: pass
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = min(60, 2 ** attempt) + random.uniform(0, 1)
                log(f"  HTTP {e.code}; retry in {wait:.1f}s")
                time.sleep(wait)
                continue
            return False, f"HTTP {e.code}: {err}", {}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(min(30, 2 ** attempt))
                continue
            return False, str(e), {}
    return False, "max retries", {}

def get_collection_items(coll_key):
    items = []
    start = 0
    while True:
        ok, data, _ = zot_request("GET",
            f"/collections/{coll_key}/items/top?limit=100&start={start}")
        if not ok or not data:
            break
        items.extend(data)
        if len(data) < 100:
            break
        start += 100
        time.sleep(RATE_LIMIT_SEC)
    return items

# ============================================================
# BUILD BUCKET MAP
# ============================================================
def build_bucket_map(source_filter=None):
    log("Scanning collections...")
    all_colls = []
    start = 0
    while True:
        ok, data, _ = zot_request("GET", f"/collections?limit=100&start={start}")
        if not ok or not data:
            break
        all_colls.extend(data)
        if len(data) < 100:
            break
        start += 100
        time.sleep(RATE_LIMIT_SEC)

    by_key = {c["key"]: c for c in all_colls}
    by_parent = defaultdict(list)
    for c in all_colls:
        p = c.get("data", {}).get("parentCollection", "")
        if p:
            by_parent[p].append(c["key"])

    # source -> {bucket_name -> coll_key}
    source_buckets = {}
    sources_to_process = SCREENING_PARENTS
    if source_filter:
        sources_to_process = {k: v for k, v in SCREENING_PARENTS.items()
                              if k in source_filter}

    for src, parent_key in sources_to_process.items():
        buckets = {}
        for child_key in by_parent.get(parent_key, []):
            name = by_key[child_key].get("data", {}).get("name", "").strip()
            if name in DECISION_BUCKET_NAMES or name == QUEUE_NAME:
                buckets[name] = child_key
        if buckets:
            source_buckets[src] = buckets
            log(f"  {src}: {buckets}")

    return source_buckets

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes. Default is dry-run.")
    parser.add_argument("--source", nargs="+",
                        help="Limit to specific source(s) e.g. --source ssrn ieee")
    args = parser.parse_args()

    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    log("=== cleanup_queue_membership.py ===")
    log(f"Mode:   {'APPLY (writes)' if args.apply else 'DRY-RUN (no writes)'}")
    log(f"Sources: {args.source or 'ALL'}")

    source_buckets = build_bucket_map(args.source)

    total_to_fix = 0
    total_fixed = 0
    total_errors = 0

    for src, buckets in source_buckets.items():
        queue_key = buckets.get(QUEUE_NAME)
        if not queue_key:
            log(f"\n{src}: no 00-Queue collection — skipping")
            continue

        decision_keys = {buckets[b] for b in DECISION_BUCKET_NAMES if b in buckets}
        if not decision_keys:
            log(f"\n{src}: no decision bucket collections found — skipping")
            continue

        log(f"\n=== {src.upper()} ===")
        log(f"  Queue: {queue_key}")
        log(f"  Decision buckets: {decision_keys}")

        # Fetch all items in Queue
        log(f"  Fetching Queue items...")
        queue_items = get_collection_items(queue_key)
        log(f"  Queue items: {len(queue_items)}")

        # Find items that also belong to a decision bucket
        to_fix = []
        for item in queue_items:
            item_colls = set(item.get("data", {}).get("collections", []))
            if item_colls & decision_keys:
                # This item is in both Queue AND a decision bucket — fix it
                to_fix.append({
                    "key": item["key"],
                    "version": item.get("version", 0),
                    "collections": item_colls,
                    "title": item.get("data", {}).get("title", "")[:60],
                })

        log(f"  Items to remove from Queue: {len(to_fix)}")
        total_to_fix += len(to_fix)

        if not to_fix:
            log(f"  ✓ {src} Queue is clean")
            continue

        # Show sample
        for item in to_fix[:5]:
            log(f"  {item['key']}: {item['title']}")
        if len(to_fix) > 5:
            log(f"  ... and {len(to_fix) - 5} more")

        if not args.apply:
            continue

        # Apply — remove Queue collection from each item
        log(f"  Applying {len(to_fix)} fixes...")
        src_fixed = 0
        src_errors = 0

        for i, item in enumerate(to_fix, 1):
            new_colls = sorted(item["collections"] - {queue_key})
            ok, resp, _ = zot_request(
                "PATCH", f"/items/{item['key']}",
                body={"collections": new_colls},
                api_key=ZOTERO_API_KEY_RW,
                headers={"If-Unmodified-Since-Version": str(item["version"])},
            )
            if ok:
                src_fixed += 1
            else:
                log(f"  FAIL {item['key']}: {resp}")
                src_errors += 1
            time.sleep(RATE_LIMIT_SEC)

            if i % 100 == 0 or i == len(to_fix):
                log(f"  [{i}/{len(to_fix)}] fixed={src_fixed} errors={src_errors}")

        total_fixed += src_fixed
        total_errors += src_errors
        log(f"  {src}: fixed={src_fixed} errors={src_errors}")

    log(f"\n=== SUMMARY ===")
    log(f"Total items needing fix: {total_to_fix}")
    if args.apply:
        log(f"Total fixed:             {total_fixed}")
        log(f"Total errors:            {total_errors}")
    else:
        log(f"DRY-RUN — re-run with --apply to write changes")

if __name__ == "__main__":
    main()
