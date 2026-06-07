#!/usr/bin/env python3
"""
compare_s1_tags_vs_csv.py  (READ-ONLY)

Compares the s1:* screening tags currently on Zotero items against the
original Pass 1 screening CSV, to decide which is the authoritative ground
truth for restoring Pass 1 per-source collection membership.

Does NOT write anything to Zotero.

Usage:
    python3 compare_s1_tags_vs_csv.py --csv /path/to/pass1_decisions.csv

The CSV is expected to have at least:
    item_key, <some decision column(s)>
Common shapes this handles:
    - item_key, human_decision, claude_decision
    - item_key, screener, decision
    - item_key, decision            (single column)
The script auto-detects columns and reports what it found.
"""
import argparse, csv, json, os, sys, time, urllib.request

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
from collections import defaultdict, Counter

KEY = os.environ.get("VCSLR_ZOTERO_READ_KEY") or os.environ.get("ZOTERO_API_KEY", "")  # VCSLR read key (env / project .env)
BASE = "https://api.zotero.org/groups/" + os.environ.get("VCSLR_ZOTERO_LIBRARY_ID", "6505702")

def zget(path):
    req = urllib.request.Request(f"{BASE}{path}",
        headers={"Zotero-API-Key": KEY, "Zotero-API-Version": "3"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

# --- Pass 1 source parent collections ---
SOURCE_PARENTS = {
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
BUCKETS = {"01-Keep": "keep", "02-Maybe": "maybe", "03-Discard": "discard"}

def norm(d):
    if not d: return ""
    d = d.strip().lower()
    return {"keep":"keep","maybe":"maybe","discard":"discard",
            "k":"keep","m":"maybe","d":"discard"}.get(d, d)

def load_csv(path):
    """Return dict item_key -> {'human':dec, 'claude':dec} (any may be missing)."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"!! CSV {path} is empty"); sys.exit(1)
    cols = [c.strip() for c in rows[0].keys()]
    print(f"CSV columns: {cols}")
    print(f"CSV rows: {len(rows)}")

    keycol = next((c for c in cols if c.lower() in
                   ("item_key","itemkey","key")), None)
    if not keycol:
        print("!! No item_key column found"); sys.exit(1)

    out = defaultdict(dict)
    # Shape A: explicit human_decision / claude_decision columns
    hcol = next((c for c in cols if c.lower() in ("human_decision","human")), None)
    ccol = next((c for c in cols if c.lower() in ("claude_decision","claude","sonnet_decision","decision_claude")), None)
    # Shape B: screener + decision columns
    scol = next((c for c in cols if c.lower() in ("screener","coder","model")), None)
    dcol = next((c for c in cols if c.lower() in ("decision","final_decision","label")), None)

    if hcol or ccol:
        for r in rows:
            k = r[keycol].strip()
            if hcol and norm(r.get(hcol)): out[k]["human"] = norm(r[hcol])
            if ccol and norm(r.get(ccol)): out[k]["claude"] = norm(r[ccol])
        print(f"Detected shape: explicit columns (human={hcol}, claude={ccol})")
    elif scol and dcol:
        for r in rows:
            k = r[keycol].strip()
            who = r[scol].strip().lower()
            who = "human" if "human" in who else ("claude" if ("claude" in who or "sonnet" in who) else who)
            out[k][who] = norm(r[dcol])
        print(f"Detected shape: screener/decision long form ({scol}/{dcol})")
    elif dcol:
        for r in rows:
            out[r[keycol].strip()]["decision"] = norm(r[dcol])
        print(f"Detected shape: single decision column ({dcol})")
    else:
        print("!! Could not detect decision columns; here's a sample row:")
        print(rows[0]); sys.exit(1)
    return out

def csv_union(rec):
    """Union decision from a CSV record: human > claude > decision."""
    if "human" in rec and rec["human"]: return rec["human"]
    if "claude" in rec and rec["claude"]: return rec["claude"]
    if "decision" in rec and rec["decision"]: return rec["decision"]
    return ""

def fetch_all_collections():
    colls=[]; start=0
    while True:
        d=zget(f"/collections?limit=100&start={start}")
        colls+=d
        if len(d)<100: break
        start+=100
        time.sleep(0.2)
    return colls

def fetch_bucket_items_with_tags(coll_key):
    """Return list of (item_key, set_of_s1_tags) for top items in a collection."""
    out=[]; start=0
    while True:
        items=zget(f"/collections/{coll_key}/items/top?limit=100&start={start}&include=data")
        if not items: break
        for it in items:
            tags={t['tag'] for t in it['data'].get('tags',[]) if t['tag'].startswith('s1:')}
            out.append((it['key'], tags))
        if len(items)<100: break
        start+=100
        time.sleep(0.15)
    return out

def tag_union(tags):
    """Derive union decision from s1: tags. human > claude."""
    def dec_for(screener):
        for d in ("keep","maybe","discard"):
            if f"s1:{screener}:{d}" in tags: return d
        return ""
    return dec_for("human") or dec_for("claude") or ""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to original Pass 1 screening CSV")
    ap.add_argument("--limit-sources", default="", help="comma list to restrict (e.g. ieee,scopus)")
    args=ap.parse_args()

    csv_data = load_csv(args.csv)
    csv_union_map = {k: csv_union(v) for k,v in csv_data.items()}
    print(f"\nCSV union decision distribution: {Counter(csv_union_map.values())}\n")

    colls = fetch_all_collections()
    by_parent=defaultdict(list)
    name_of={}
    for c in colls:
        name_of[c['key']]=c['data']['name'].strip()
        p=c['data'].get('parentCollection')
        if p: by_parent[p].append(c['key'])

    only = set(s.strip() for s in args.limit_sources.split(",") if s.strip())

    # For each source, walk its 3 decision buckets, collect (item, current_bucket, tag_union, csv_union)
    print(f"{'source':<18}{'bucket':<11}{'n':>6}  tag=csv  tag!=csv  tag_missing  csv_missing")
    print("-"*78)
    grand = Counter()
    mismatch_samples=[]
    for src, parent in SOURCE_PARENTS.items():
        if only and src not in only: continue
        for child in by_parent.get(parent, []):
            bname=name_of[child]
            if bname not in BUCKETS: continue
            cur_dec=BUCKETS[bname]
            items=fetch_bucket_items_with_tags(child)
            n=len(items)
            tag_eq_csv=tag_ne_csv=tag_missing=csv_missing=0
            for key,tags in items:
                tu=tag_union(tags)
                cu=csv_union_map.get(key,"")
                if not tu: tag_missing+=1
                if not cu: csv_missing+=1
                if tu and cu:
                    if tu==cu: tag_eq_csv+=1
                    else:
                        tag_ne_csv+=1
                        if len(mismatch_samples)<15:
                            mismatch_samples.append((src,bname,key,f"tag={tu}",f"csv={cu}"))
            print(f"{src:<18}{bname:<11}{n:>6}  {tag_eq_csv:>6}  {tag_ne_csv:>7}  {tag_missing:>10}  {csv_missing:>10}")
            grand['n']+=n; grand['eq']+=tag_eq_csv; grand['ne']+=tag_ne_csv
            grand['tagmiss']+=tag_missing; grand['csvmiss']+=csv_missing
    print("-"*78)
    print(f"{'TOTAL':<18}{'':<11}{grand['n']:>6}  {grand['eq']:>6}  {grand['ne']:>7}  {grand['tagmiss']:>10}  {grand['csvmiss']:>10}")

    print("\n=== Interpretation ===")
    print(f"  Items where s1 tags AND csv agree:      {grand['eq']}")
    print(f"  Items where they DISAGREE:              {grand['ne']}")
    print(f"  Items in a bucket but missing s1 tag:   {grand['tagmiss']}")
    print(f"  Items in a bucket but missing from CSV: {grand['csvmiss']}")
    if mismatch_samples:
        print("\n  Sample disagreements (source, bucket, key, tag, csv):")
        for s in mismatch_samples: print("   ", s)
    print("\nNote: current bucket membership is post-corruption/post-recovery and")
    print("is NOT the ground truth — we only compare tags vs CSV here.")

if __name__=="__main__":
    main()
