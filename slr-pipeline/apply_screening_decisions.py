#!/usr/bin/env python3
"""
Apply Stage 1 screening decisions from a validation workbook CSV/XLS to Zotero.

For each row in the input file:
  1. Determines the final Stage 1 decision using the union rule:
       - If human_decision is populated → use that
       - Otherwise → use claude_decision
  2. Updates the item's Zotero screening collection placement to match
     (moves between 00-Queue, 01-Keep, 02-Maybe, 03-Discard as needed)
  3. Applies s1:<screener>:<decision> tags for every screener column found
     (claude, human, chatgpt, gemini — all recorded regardless of reliability)

Superseded items: collection placement is NOT updated (item already resolved);
decision tags are still applied.

Conflict handling: if current Zotero placement disagrees with the human decision,
logs the conflict and applies the human decision.

Column auto-detection:
  - Any column whose name ends in '_decision' or equals 'decision' is treated
    as a screener column.
  - Screener name is inferred: 'decision' → 'claude', 'human_decision' → 'human', etc.
  - Columns with no populated values are skipped.

Usage:
    python3 apply_screening_decisions.py decisions.xlsx           # dry-run
    python3 apply_screening_decisions.py decisions.xlsx --apply   # commit
    python3 apply_screening_decisions.py validation_workbook.xls --apply

Output:
    apply_screening.log   — execution log
    conflicts.csv         — items where Zotero placement disagreed with human decision
    skipped.csv           — items not found in Zotero or otherwise skipped
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
import re
import sys
import time
import random
import urllib.request
import urllib.error
from datetime import datetime, timezone
from collections import defaultdict

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas required. Install with: pip install pandas openpyxl xlrd --break-system-packages")
    sys.exit(1)

# ============================================================
# CONFIG
# ============================================================
ZOTERO_API_KEY_RO = os.environ.get("ZOTERO_API_KEY", "")  # from env / project .env
ZOTERO_API_KEY_RW = os.environ.get("ZOTERO_WRITE_KEY", "")  # from env / project .env
LIB = "6505702"
BASE = f"https://api.zotero.org/groups/{LIB}"
RATE_LIMIT_SEC = 0.3

# 02-Screening parent collection keys per source
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

BUCKET_NAMES = {
    "keep":    "01-Keep",
    "maybe":   "02-Maybe",
    "discard": "03-Discard",
    "queue":   "00-Queue",
}
VALID_DECISIONS = {"keep", "maybe", "discard"}

LOG_FILE       = "apply_screening.log"
CONFLICTS_CSV  = "conflicts.csv"
SKIPPED_CSV    = "skipped.csv"

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

# ============================================================
# COLLECTION DISCOVERY
# ============================================================
def build_bucket_map():
    """
    Build a map: (source_short, bucket_name) -> collection_key
    e.g. ("ieee", "01-Keep") -> "ABCD1234"
    """
    log("Scanning collections to build bucket map...")
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

    parent_to_source = {pk: sk for sk, pk in SCREENING_PARENTS.items()}
    bucket_map = {}     # (source, bucket_name) -> coll_key
    coll_to_bucket = {} # collection_key -> (source, bucket_name)

    for src, parent_key in SCREENING_PARENTS.items():
        for child_key in by_parent.get(parent_key, []):
            child = by_key.get(child_key, {})
            cname = child.get("data", {}).get("name", "").strip()
            if cname in BUCKET_NAMES.values() or cname == "00-Queue":
                bucket_map[(src, cname)] = child_key
                coll_to_bucket[child_key] = (src, cname)
            # Also walk SCOPUS Queue theme sub-collections
            if cname == "00-Queue":
                for grandchild_key in by_parent.get(child_key, []):
                    coll_to_bucket[grandchild_key] = (src, "00-Queue")

    log(f"  Bucket map entries: {len(bucket_map)}")
    return bucket_map, coll_to_bucket

# ============================================================
# COLUMN AUTO-DETECTION
# ============================================================
def detect_screener_columns(df):
    """
    Find columns whose name ends in '_decision' or equals 'decision'.
    Returns dict: screener_name -> column_name
    e.g. {"claude": "decision", "human": "human_decision", "chatgpt": "chatgpt_decision"}
    """
    screeners = {}
    for col in df.columns:
        col_lower = col.strip().lower()
        if col_lower == "decision":
            screeners["claude"] = col
        elif col_lower.endswith("_decision"):
            screener = col_lower.replace("_decision", "").strip("_")
            screeners[screener] = col
    return screeners

def clean_decision(val):
    """Normalize a decision value to keep/maybe/discard or None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().lower()
    if s in VALID_DECISIONS:
        return s
    if s in ("", "nan", "none", "n/a"):
        return None
    return None

# ============================================================
# READ INPUT FILE
# ============================================================
def read_input(path):
    """Read CSV or XLS/XLSX, return DataFrame with item_key column."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".csv":
            df = pd.read_csv(path, encoding="utf-8-sig")
        elif ext in (".xlsx", ".xlsm"):
            df = pd.read_excel(path, engine="openpyxl")
        elif ext == ".xls":
            df = pd.read_excel(path, engine="xlrd")
        else:
            # Try CSV fallback
            df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as e:
        log(f"ERROR reading {path}: {e}")
        sys.exit(1)

    # Normalize column names (strip whitespace, BOM)
    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]

    # Find item_key column
    key_col = None
    for cand in ["item_key", "key", "zotero_key", "id", "item_id"]:
        if cand in df.columns:
            key_col = cand
            break
    if not key_col:
        log(f"ERROR: Cannot find item_key column. Columns: {list(df.columns)}")
        sys.exit(1)

    df = df.rename(columns={key_col: "item_key"})
    df["item_key"] = df["item_key"].astype(str).str.strip()
    # Drop rows with no key
    df = df[df["item_key"].str.len() == 8].copy()
    log(f"  Loaded {len(df)} rows with valid 8-char item keys from {path}")
    return df

# ============================================================
# MAIN PROCESSING
# ============================================================
def process(df, screeners, bucket_map, coll_to_bucket, apply_writes):
    """
    For each row: determine final decision, update Zotero collection,
    apply decision tags. Returns stats dict.
    """
    stats = {
        "processed": 0, "skipped": 0, "conflicts": 0,
        "collection_updates": 0, "tags_added": 0, "errors": 0,
        "superseded_skipped": 0,
    }
    conflicts = []
    skipped = []

    log(f"\nProcessing {len(df)} rows...")
    log(f"Screener columns detected: {screeners}")
    log(f"Union rule: human_decision > claude_decision")
    log(f"Mode: {'APPLY (writes)' if apply_writes else 'DRY-RUN (no writes)'}")
    log("")

    for idx, row in df.iterrows():
        item_key = row["item_key"]

        # --- Fetch current Zotero item ---
        ok, item, _ = zot_request("GET", f"/items/{item_key}")
        if not ok:
            log(f"  SKIP {item_key}: fetch failed ({item})")
            skipped.append({"item_key": item_key, "reason": f"fetch_failed: {item}"})
            stats["skipped"] += 1
            time.sleep(RATE_LIMIT_SEC)
            continue

        item_data = item.get("data", {})
        version = item.get("version", 0)
        current_tags = {t.get("tag", "") for t in item_data.get("tags", [])}
        current_collections = set(item_data.get("collections", []))
        title = item_data.get("title", "")[:80]

        # --- Check if superseded ---
        is_superseded = any(t.startswith("superseded-by:") for t in current_tags)

        # --- Gather all decisions from the row ---
        row_decisions = {}
        for screener, col in screeners.items():
            val = clean_decision(row.get(col))
            if val:
                row_decisions[screener] = val

        if not row_decisions:
            log(f"  SKIP {item_key}: no decisions found in row")
            skipped.append({"item_key": item_key, "reason": "no_decisions"})
            stats["skipped"] += 1
            continue

        # --- Union rule: human overrides claude ---
        final_decision = row_decisions.get("human") or row_decisions.get("claude")
        if not final_decision:
            # Fallback: use any available decision
            final_decision = next(iter(row_decisions.values()), None)
        if not final_decision:
            skipped.append({"item_key": item_key, "reason": "no_valid_final_decision"})
            stats["skipped"] += 1
            continue

        # --- Check current Zotero placement vs human decision ---
        if "human" in row_decisions:
            human_dec = row_decisions["human"]
            current_bucket_names = {
                coll_to_bucket.get(ck, (None, None))[1]
                for ck in current_collections
            }
            current_bucket_names = {b for b in current_bucket_names if b}
            expected_bucket = BUCKET_NAMES.get(human_dec)
            if expected_bucket and current_bucket_names and expected_bucket not in current_bucket_names:
                conflicts.append({
                    "item_key": item_key,
                    "title": title,
                    "human_decision": human_dec,
                    "current_buckets": "|".join(sorted(current_bucket_names)),
                    "applying": final_decision,
                })
                log(f"  CONFLICT {item_key}: Zotero has {current_bucket_names} but human={human_dec} → applying {final_decision}")
                stats["conflicts"] += 1

        # --- Compute new tags to add ---
        tags_to_add = set()
        for screener, decision in row_decisions.items():
            tag = f"s1:{screener}:{decision}"
            if tag not in current_tags:
                tags_to_add.add(tag)

        # --- Determine collection changes (skip if superseded) ---
        collections_to_add = set()
        collections_to_remove = set()

        if not is_superseded:
            target_bucket = BUCKET_NAMES.get(final_decision)
            if target_bucket:
                # For each source this item belongs to, ensure it's in the right bucket
                item_sources = set()
                for ck in current_collections:
                    src_bucket = coll_to_bucket.get(ck)
                    if src_bucket:
                        item_sources.add(src_bucket[0])

                for src in item_sources:
                    target_key = bucket_map.get((src, target_bucket))
                    if not target_key:
                        continue
                    # Check if already in target
                    if target_key in current_collections:
                        continue
                    collections_to_add.add(target_key)
                    # Remove from Queue and all other decision buckets in same source
                    queue_key = bucket_map.get((src, "00-Queue"))
                    if queue_key and queue_key in current_collections:
                        collections_to_remove.add(queue_key)
                    for bucket_name, bkey in [
                        (BUCKET_NAMES["keep"],    bucket_map.get((src, BUCKET_NAMES["keep"]))),
                        (BUCKET_NAMES["maybe"],   bucket_map.get((src, BUCKET_NAMES["maybe"]))),
                        (BUCKET_NAMES["discard"], bucket_map.get((src, BUCKET_NAMES["discard"]))),
                    ]:
                        if bkey and bkey in current_collections and bkey != target_key:
                            collections_to_remove.add(bkey)
        else:
            stats["superseded_skipped"] += 1

        # --- Log what would change ---
        if tags_to_add or collections_to_add or collections_to_remove:
            log(f"  {item_key} [{final_decision}]{' [SUPERSEDED-skip-coll]' if is_superseded else ''}")
            if tags_to_add:
                log(f"    + tags: {sorted(tags_to_add)}")
            if collections_to_add:
                log(f"    + collections: {sorted(collections_to_add)}")
            if collections_to_remove:
                log(f"    - collections: {sorted(collections_to_remove)}")

        # --- Apply if not dry-run ---
        if apply_writes and (tags_to_add or collections_to_add or collections_to_remove):
            new_tags = sorted(current_tags | tags_to_add)
            new_collections = sorted(
                (current_collections | collections_to_add) - collections_to_remove
            )
            patch = {}
            if tags_to_add:
                patch["tags"] = [{"tag": t} for t in new_tags]
            if collections_to_add or collections_to_remove:
                patch["collections"] = list(new_collections)

            ok, resp, _ = zot_request(
                "PATCH", f"/items/{item_key}",
                body=patch,
                api_key=ZOTERO_API_KEY_RW,
                headers={"If-Unmodified-Since-Version": str(version)},
            )
            if ok:
                stats["tags_added"] += len(tags_to_add)
                stats["collection_updates"] += 1 if (collections_to_add or collections_to_remove) else 0
            else:
                log(f"    PATCH FAILED: {resp}")
                stats["errors"] += 1

        stats["processed"] += 1
        time.sleep(RATE_LIMIT_SEC)

        if stats["processed"] % 50 == 0:
            log(f"  Progress: {stats['processed']}/{len(df)} rows — "
                f"updates={stats['collection_updates']} tags={stats['tags_added']} "
                f"conflicts={stats['conflicts']} errors={stats['errors']}")

    return stats, conflicts, skipped

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Input file (CSV, XLS, or XLSX)")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to Zotero. Default is dry-run.")
    args = parser.parse_args()

    # Reset log
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    log(f"=== apply_screening_decisions.py ===")
    log(f"Input: {args.input}")
    log(f"Mode:  {'APPLY (writes)' if args.apply else 'DRY-RUN (no writes)'}")

    # Read input
    df = read_input(args.input)

    # Detect screener columns
    screeners = detect_screener_columns(df)
    if not screeners:
        log("ERROR: No decision columns found. Expected columns like 'decision', 'human_decision', etc.")
        sys.exit(1)
    log(f"Detected screener columns: {screeners}")

    # Check union rule columns are present
    has_human  = "human"  in screeners
    has_claude = "claude" in screeners
    log(f"Union rule: human={'YES' if has_human else 'NO'}, claude={'YES' if has_claude else 'NO'}")

    # Build bucket map
    bucket_map, coll_to_bucket = build_bucket_map()

    # Process
    stats, conflicts, skipped = process(df, screeners, bucket_map, coll_to_bucket, args.apply)

    # Write CSVs
    if conflicts:
        with open(CONFLICTS_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["item_key", "title", "human_decision",
                                               "current_buckets", "applying"])
            w.writeheader()
            w.writerows(conflicts)
        log(f"Wrote {CONFLICTS_CSV} ({len(conflicts)} conflicts)")

    if skipped:
        with open(SKIPPED_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["item_key", "reason"])
            w.writeheader()
            w.writerows(skipped)
        log(f"Wrote {SKIPPED_CSV} ({len(skipped)} skipped)")

    log(f"\n=== SUMMARY ===")
    log(f"Rows processed:         {stats['processed']}")
    log(f"Collection updates:     {stats['collection_updates']}")
    log(f"Tags added:             {stats['tags_added']}")
    log(f"Conflicts detected:     {stats['conflicts']}")
    log(f"Superseded (coll skip): {stats['superseded_skipped']}")
    log(f"Skipped:                {stats['skipped']}")
    log(f"Errors:                 {stats['errors']}")

    if not args.apply:
        log(f"\nDRY-RUN complete. Re-run with --apply to write changes.")

if __name__ == "__main__":
    main()
