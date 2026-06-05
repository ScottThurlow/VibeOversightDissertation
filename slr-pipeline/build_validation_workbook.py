#!/usr/bin/env python3
"""
Build cross-model validation workbook from non-SSRN screening output.

Reads decisions.csv from the non_ssrn_llm_screen.py run, enriches each row
with the human screening decision from Zotero (s1:human:* tags), and adds
empty columns for ChatGPT and Gemini validation passes.

Output: validation_workbook.csv with columns:
  item_key, title, abstract, authors, year, item_type, sources,
  claude_decision, human_decision, chatgpt_decision, gemini_decision, rationale

human_decision is populated from s1:human:* tags in Zotero.
Items in 00-Queue (not yet human-screened) will have human_decision blank.
chatgpt_decision and gemini_decision are always blank — fill after validation runs.

Usage:
    python3 build_validation_workbook.py --input decisions.csv
    python3 build_validation_workbook.py --input decisions.csv --output validation_workbook.csv
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
import sys
import time
import random
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
ZOTERO_API_KEY_RO = os.environ.get("ZOTERO_API_KEY", "")  # from env / project .env
LIB = "6505702"
BASE = f"https://api.zotero.org/groups/{LIB}"
RATE_LIMIT_SEC = 0.3
BATCH_SIZE = 50  # items to fetch per Zotero API call

LOG_FILE = "build_workbook.log"

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
def zot_get(path, retries=8):
    import random as _random
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{BASE}{path}")
            req.add_header("Zotero-API-Key", ZOTERO_API_KEY_RO)
            req.add_header("Zotero-API-Version", "3")
            with urllib.request.urlopen(req, timeout=60) as r:
                return True, json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = min(60, 2 ** attempt) + _random.uniform(0, 1)
                log(f"  HTTP {e.code} on {path}; retry in {wait:.1f}s")
                time.sleep(wait)
                continue
            return False, f"HTTP {e.code}"
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return False, str(e)
    return False, "max retries"

def fetch_items_by_keys(keys):
    """
    Fetch Zotero items in batches by key.
    Returns dict: item_key -> item data dict.
    """
    result = {}
    total = len(keys)
    log(f"Fetching {total} items from Zotero in batches of {BATCH_SIZE}...")

    for i in range(0, total, BATCH_SIZE):
        batch = keys[i:i + BATCH_SIZE]
        key_param = ",".join(batch)
        ok, data = zot_get(f"/items?itemKey={key_param}&limit={BATCH_SIZE}")
        if not ok:
            log(f"  ERROR fetching batch at {i}: {data}")
            continue
        for item in data:
            k = item["key"]
            result[k] = item
        if (i // BATCH_SIZE + 1) % 10 == 0 or i + BATCH_SIZE >= total:
            log(f"  Fetched {min(i + BATCH_SIZE, total)}/{total}")
        time.sleep(RATE_LIMIT_SEC)

    log(f"  Successfully fetched: {len(result)} of {total}")
    return result

# ============================================================
# EXTRACT FIELDS FROM ZOTERO ITEM
# ============================================================
def extract_human_decision(item):
    """Extract s1:human:* tag value (keep/maybe/discard) or blank if none."""
    tags = [t.get("tag", "") for t in item.get("data", {}).get("tags", [])]
    for tag in tags:
        if tag.startswith("s1:human:"):
            return tag.replace("s1:human:", "").strip()
    return ""

def extract_sources(item):
    """Extract source:* tags as pipe-separated string."""
    tags = [t.get("tag", "") for t in item.get("data", {}).get("tags", [])]
    sources = [t.replace("source:", "") for t in tags if t.startswith("source:")]
    return "|".join(sorted(sources))

def extract_item_type(item):
    return item.get("data", {}).get("itemType", "")

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

def extract_year(item):
    return (item.get("data", {}).get("date", "") or "")[:4]

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True,
                        help="decisions.csv from non_ssrn_llm_screen.py")
    parser.add_argument("--output", default="validation_workbook.csv",
                        help="Output CSV path (default: validation_workbook.csv)")
    args = parser.parse_args()

    log(f"=== Build validation workbook ===")
    log(f"Input:  {args.input}")
    log(f"Output: {args.output}")

    # ---- Read decisions.csv ----
    log(f"\nReading {args.input}...")
    decisions = {}  # item_key -> row dict
    with open(args.input, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("item_key", "").strip()
            if key:
                decisions[key] = row
    log(f"  {len(decisions)} items in decisions.csv")

    # ---- Fetch Zotero metadata ----
    all_keys = list(decisions.keys())
    zotero_items = fetch_items_by_keys(all_keys)

    # ---- Build output rows ----
    log(f"\nBuilding output rows...")
    output_rows = []
    missing_from_zotero = []
    has_human_decision = 0
    no_human_decision = 0

    for key, dec_row in decisions.items():
        zitem = zotero_items.get(key)
        if zitem is None:
            missing_from_zotero.append(key)
            # Still include the row — use data from decisions.csv
            human_dec = ""
            item_type = ""
            sources = ""
            abstract = dec_row.get("abstract", "")
            authors = dec_row.get("authors", "")
            year = dec_row.get("year", "")
        else:
            human_dec = extract_human_decision(zitem)
            item_type = extract_item_type(zitem)
            sources = extract_sources(zitem)
            abstract = extract_abstract(zitem) or dec_row.get("abstract", "")
            authors = extract_authors(zitem) or dec_row.get("authors", "")
            year = extract_year(zitem) or dec_row.get("year", "")

        if human_dec:
            has_human_decision += 1
        else:
            no_human_decision += 1

        output_rows.append({
            "item_key":           key,
            "title":              dec_row.get("title", ""),
            "abstract":           abstract,
            "authors":            authors,
            "year":               year,
            "item_type":          item_type,
            "sources":            sources,
            "claude_decision":    dec_row.get("decision", "").lower().strip(),
            "human_decision":     human_dec,
            "chatgpt_decision":   "",
            "gemini_decision":    "",
            "rationale":          dec_row.get("rationale", ""),
        })

    log(f"\n=== SUMMARY ===")
    log(f"Total rows: {len(output_rows)}")
    log(f"With human_decision populated: {has_human_decision}")
    log(f"Without human_decision (in queue or not tagged): {no_human_decision}")
    log(f"Not found in Zotero: {len(missing_from_zotero)}")
    if missing_from_zotero:
        log(f"  First 10 missing: {missing_from_zotero[:10]}")

    # Decision distribution
    from collections import Counter
    claude_dist = Counter(r["claude_decision"] for r in output_rows)
    human_dist = Counter(r["human_decision"] for r in output_rows if r["human_decision"])
    log(f"\nClaude decision distribution: {dict(claude_dist)}")
    log(f"Human decision distribution:  {dict(human_dist)}")

    # ---- Write output ----
    fieldnames = [
        "item_key", "title", "abstract", "authors", "year", "item_type",
        "sources", "claude_decision", "human_decision",
        "chatgpt_decision", "gemini_decision", "rationale",
    ]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    log(f"\nWrote {len(output_rows)} rows to {args.output}")
    log(f"\nNext steps:")
    log(f"  1. Randomly sample 500 rows for ChatGPT/Gemini validation")
    log(f"  2. Add 100 rows where human_decision is populated (your manual judgements)")
    log(f"  3. Run those through ChatGPT and Gemini per the validation prompt")
    log(f"  4. Fill chatgpt_decision and gemini_decision columns")
    log(f"  5. Use apply_csv_decisions.py (zotero-bulk-tagging skill) to import results back to Zotero")

if __name__ == "__main__":
    main()
