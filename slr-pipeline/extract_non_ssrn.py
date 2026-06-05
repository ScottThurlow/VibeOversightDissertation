#!/usr/bin/env python3
"""
Extract non-SSRN screening items from Zotero for Claude screening.

Pulls all items from all four child buckets (00-Queue, 01-Keep, 02-Maybe, 03-Discard)
under each non-SSRN 02-Screening parent collection. Excludes any items in Superseded
collections. Deduplicates by item key (Zotero merge already handled cross-source dups).

Output: non_ssrn_items.csv with columns matching the SSRN screening input format:
  item_key, title, abstract, authors, year, url

State management:
- Survives session termination. Resume by re-running the script.
- state.json tracks: superseded keys, leaf collections to fetch, leaves completed,
  per-source counts, and the running set of item records collected.
- After each leaf collection completes, state.json is rewritten atomically.
- The output CSV is rewritten from in-memory state at each checkpoint, so the CSV
  is always consistent with what's been fetched so far.

Usage:
    cd ~/slr/non-ssrn
    nohup python3 extract_non_ssrn.py > run.log 2>&1 &
    # If interrupted, just re-run the same command. It will resume.

To force a fresh start:
    rm state.json
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
import urllib.error
import csv
import os
import sys
import time
import random
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
ZOTERO_API_KEY = os.environ.get("ZOTERO_API_KEY", "")  # from env / project .env
LIB = "6505702"
BASE = f"https://api.zotero.org/groups/{LIB}"

# 02-Screening parent collection keys for the 10 non-SSRN sources.
# The script fetches all four child buckets under each of these.
SCREENING_PARENTS = {
    "IEEE Xplore":                   "7XHWH8NM",
    "SCOPUS":                        "2RWBC7QH",
    "Web of Science":                "E7AS4HD4",
    "arXiv":                         "YK2CHQLN",
    "ACM":                           "G4IIYGV6",
    "Practitioner Network":          "7FL4M8HN",
    "Coursework":                    "IF299TAY",
    "Hancheng Cao":                  "GP3U9EX8",
    "Linda Naimi Book - References": "ZXIXRWKG",
    "Linda Naimi Book - Chapters":   "DIDV7BKH",
}

OUTPUT_CSV = "non_ssrn_items.csv"
STATE_FILE = "state.json"
LOG_FILE   = "extract.log"

ZOTERO_RATE_LIMIT_SEC = 0.3
CSV_FIELDS = ["item_key", "title", "abstract", "authors", "year", "url"]

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ============================================================
# STATE MANAGEMENT (atomic writes)
# ============================================================
def load_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # Corrupt state file (e.g. interrupted mid-write before atomic rename)
        # Try the .bak fallback if it exists.
        bak = STATE_FILE + ".bak"
        if os.path.exists(bak):
            log(f"  state.json unreadable ({e}); falling back to {bak}")
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e2:
                log(f"  Backup also unreadable ({e2}); starting fresh")
                return None
        log(f"  state.json unreadable ({e}); starting fresh")
        return None

def save_state(state):
    """Atomic write: write to .tmp, fsync, rename. Keep a .bak of the prior version."""
    tmp = STATE_FILE + ".tmp"
    bak = STATE_FILE + ".bak"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(STATE_FILE):
        try:
            os.replace(STATE_FILE, bak)
        except OSError:
            pass
    os.replace(tmp, STATE_FILE)

def write_csv(items_by_key):
    """Rewrite the output CSV from current in-memory state (atomic)."""
    tmp = OUTPUT_CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for key in sorted(items_by_key.keys()):
            writer.writerow(items_by_key[key])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, OUTPUT_CSV)

# ============================================================
# ZOTERO API
# ============================================================
def zot_get(path, retries=8):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{BASE}{path}")
            req.add_header("Zotero-API-Key", ZOTERO_API_KEY)
            req.add_header("Zotero-API-Version", "3")
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read()), {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = min(60, 2 ** attempt) + random.uniform(0, 1)
                log(f"  HTTP {e.code} on {path}, retry in {wait:.1f}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            last_err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries - 1:
                wait = min(60, 2 ** attempt) + random.uniform(0, 1)
                log(f"  Network error on {path}: {e}; retry in {wait:.1f}s")
                time.sleep(wait)
                continue
            last_err = str(e)
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
    return None, {"error": last_err}

# ============================================================
# COLLECTION DISCOVERY
# ============================================================
def get_subcollections(parent_key):
    """Return list of {key, name} for direct children of parent_key, or None on failure."""
    subs = []
    start = 0
    while True:
        data, hdrs = zot_get(f"/collections/{parent_key}/collections?limit=100&start={start}")
        if data is None:
            log(f"  ERROR fetching subcollections of {parent_key}: {hdrs.get('error','?')}")
            return None
        if not data:
            break
        for c in data:
            subs.append({
                "key": c["key"],
                "name": c.get("data", {}).get("name", ""),
            })
        if len(data) < 100:
            break
        start += 100
        time.sleep(ZOTERO_RATE_LIMIT_SEC)
    return subs

def get_collection_items(collection_key):
    """Return list of items (top-level only) in collection_key, or None on failure."""
    items = []
    start = 0
    while True:
        data, hdrs = zot_get(f"/collections/{collection_key}/items/top?limit=100&start={start}")
        if data is None:
            log(f"  ERROR fetching items of {collection_key}: {hdrs.get('error','?')}")
            return None
        if not data:
            break
        items.extend(data)
        if len(data) < 100:
            break
        start += 100
        time.sleep(ZOTERO_RATE_LIMIT_SEC)
    return items

# ============================================================
# SUPERSEDED FILTER
# ============================================================
def find_superseded_keys():
    """
    Return a set of collection keys whose name contains 'supersed' (case-insensitive),
    or None on API failure.
    """
    log("Scanning library for Superseded collections...")
    superseded = set()
    start = 0
    while True:
        data, hdrs = zot_get(f"/collections?limit=100&start={start}")
        if data is None:
            log(f"  ERROR scanning collections: {hdrs.get('error','?')}")
            return None
        if not data:
            break
        for c in data:
            name = c.get("data", {}).get("name", "")
            if "supersed" in name.lower():
                superseded.add(c["key"])
                log(f"  Superseded collection: {c['key']}  {name}")
        if len(data) < 100:
            break
        start += 100
        time.sleep(ZOTERO_RATE_LIMIT_SEC)
    log(f"  Found {len(superseded)} Superseded collection(s)")
    return superseded

# ============================================================
# ITEM EXTRACTION
# ============================================================
def extract_item_fields(item):
    """Extract the six SSRN-format fields from a Zotero item."""
    d = item.get("data", {})
    creators = d.get("creators", [])
    authors = "; ".join(
        (c.get("lastName", "") or c.get("name", "")) for c in creators[:5]
    )
    year = (d.get("date", "") or "")[:4]
    return {
        "item_key": item["key"],
        "title": d.get("title", "") or "",
        "abstract": d.get("abstractNote", "") or "",
        "authors": authors,
        "year": year,
        "url": d.get("url", "") or "",
    }

# ============================================================
# DISCOVERY PHASE (idempotent — runs once, cached in state)
# ============================================================
def discover_work(state):
    """
    Populate state with:
      - superseded_keys (sorted list)
      - leaves (list of [source_name, collection_key, collection_name])
    Skips if already populated. Returns True on success, False on API failure.
    """
    if "superseded_keys" not in state:
        keys = find_superseded_keys()
        if keys is None:
            return False
        state["superseded_keys"] = sorted(keys)
        save_state(state)
    
    if "leaves" not in state:
        log("\nGathering child collections under each 02-Screening parent...")
        superseded_set = set(state["superseded_keys"])
        leaves = []
        for source_name, parent_key in SCREENING_PARENTS.items():
            subs = get_subcollections(parent_key)
            if subs is None:
                return False
            log(f"  {source_name}: {len(subs)} child collection(s)")
            for sub in subs:
                if sub["key"] in superseded_set:
                    log(f"    SKIP (superseded): {sub['name']}")
                    continue
                leaves.append([source_name, sub["key"], sub["name"]])
            time.sleep(ZOTERO_RATE_LIMIT_SEC)
        state["leaves"] = leaves
        log(f"\nTotal leaf collections to fetch: {len(leaves)}")
        save_state(state)
    
    return True

# ============================================================
# MAIN
# ============================================================
def main():
    # PID file for visibility into running instances
    with open("pid.txt", "a") as f:
        f.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
    
    log(f"=== Extract started (pid {os.getpid()}) ===")
    log(f"Output:  {OUTPUT_CSV}")
    log(f"State:   {STATE_FILE}")
    log(f"Log:     {LOG_FILE}")
    
    # Load or initialize state
    state = load_state()
    if state is None:
        log("No prior state found. Starting fresh.")
        state = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_leaves": [],
            "items_by_key": {},
            "per_source_counts": {s: 0 for s in SCREENING_PARENTS},
            "excluded_superseded": 0,
        }
        save_state(state)
    else:
        log(f"Resuming. Started at: {state.get('started_at','?')}")
        log(f"  Items already collected: {len(state.get('items_by_key', {}))}")
        log(f"  Leaves already completed: {len(state.get('completed_leaves', []))}")
    
    # Discovery phase (idempotent)
    if not discover_work(state):
        log("Discovery failed; aborting. Re-run to retry.")
        sys.exit(1)
    
    superseded_set = set(state["superseded_keys"])
    completed = set(state["completed_leaves"])
    items_by_key = state["items_by_key"]
    per_source_counts = state["per_source_counts"]
    
    leaves = state["leaves"]
    remaining = [(s, k, n) for (s, k, n) in leaves if k not in completed]
    log(f"\nLeaves remaining: {len(remaining)} of {len(leaves)}")
    
    # Fetch loop
    for i, (source_name, coll_key, coll_name) in enumerate(remaining, 1):
        log(f"\n[{i}/{len(remaining)}] Fetching {source_name} / {coll_name} ({coll_key})...")
        items = get_collection_items(coll_key)
        if items is None:
            log(f"  Failed; will retry on next run. Stopping.")
            sys.exit(2)
        
        log(f"  {len(items)} items returned")
        new_in_leaf = 0
        for it in items:
            key = it["key"]
            
            # Item-level superseded check
            collections = it.get("data", {}).get("collections", [])
            if any(c in superseded_set for c in collections):
                state["excluded_superseded"] += 1
                continue
            
            if key not in items_by_key:
                items_by_key[key] = extract_item_fields(it)
                per_source_counts[source_name] = per_source_counts.get(source_name, 0) + 1
                new_in_leaf += 1
        
        log(f"  New unique items: {new_in_leaf}; running total: {len(items_by_key)}")
        
        # Mark complete and checkpoint
        completed.add(coll_key)
        state["completed_leaves"] = sorted(completed)
        state["items_by_key"] = items_by_key
        state["per_source_counts"] = per_source_counts
        save_state(state)
        write_csv(items_by_key)
        
        time.sleep(ZOTERO_RATE_LIMIT_SEC)
    
    # Done
    log(f"\n=== COMPLETE ===")
    log(f"Unique items extracted: {len(items_by_key)}")
    log(f"Items excluded due to superseded membership: {state['excluded_superseded']}")
    log(f"\nFirst-seen counts by source (cross-source dups credited to first source):")
    for s, n in per_source_counts.items():
        log(f"  {s}: {n}")
    log(f"\nWrote {len(items_by_key)} rows to {OUTPUT_CSV}")
    log(f"\nTo run a fresh extract: rm {STATE_FILE} {OUTPUT_CSV} && python3 {sys.argv[0]}")

if __name__ == "__main__":
    main()
