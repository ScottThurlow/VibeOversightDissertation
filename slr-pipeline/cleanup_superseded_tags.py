#!/usr/bin/env python3
"""
Cleanup script: apply superseded-relationship tags using 00-Dups as the work list.

Reads items from the live 00-Dups collection, clusters them by title similarity
(Jaccard >= 0.90), identifies canonical per venue hierarchy, then:

  Canonical (winner):
    - Adds source:* tags from ALL siblings (union of cluster sources)
    - Does NOT touch s1:human:* decision tags (handled by apply_stage1_tags.py)

  Superseded (loser):
    - Adds superseded-by:<canonical_key> tag
    - Adds source:* tags from its own memberships (provenance)
    - Does NOT add s1:human:* decision tags
    - If it ALREADY HAS an s1:human:* tag: adds review:superseded-has-decision
      tag and logs it to flagged_superseded.csv for manual review

Dry-run by default. Pass --apply to write tags.

Output:
    superseded_tag_plan.csv     — full plan of what tags would be added
    flagged_superseded.csv      — items that are superseded but have a human decision tag
    cleanup.log                 — execution log

Usage:
    python3 cleanup_superseded_tags.py
    python3 cleanup_superseded_tags.py --apply
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

DUPS_COLLECTION_NAME = "00-Dups"
TITLE_THRESHOLD = 0.90

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

# ItemType venue hierarchy: lower index = higher tier = canonical
VENUE_HIERARCHY = [
    "journalArticle",
    "conferencePaper",
    "bookSection",
    "book",
    "preprint",
    "thesis",
    "report",
    "webpage",
]

def venue_rank(item_type):
    try:
        return VENUE_HIERARCHY.index(item_type)
    except ValueError:
        return 999

# ============================================================
# LOGGING
# ============================================================
LOG_FILE = "cleanup.log"

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
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = min(60, 2 ** attempt) + random.uniform(0, 1)
                log(f"  HTTP {e.code} on {method} {path}; retry in {wait:.1f}s")
                time.sleep(wait)
                continue
            return False, f"HTTP {e.code}: {err_body}", {}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries - 1:
                wait = min(60, 2 ** attempt) + random.uniform(0, 1)
                log(f"  Network error: {e}; retry in {wait:.1f}s")
                time.sleep(wait)
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

def find_live_collection(name):
    """Find a non-deleted collection by exact name."""
    log(f"Looking up live collection {name!r}...")
    start = 0
    matches = []
    while True:
        ok, data, _ = zot_request("GET", f"/collections?limit=100&start={start}")
        if not ok or not data:
            break
        for c in data:
            d = c.get("data", {})
            if d.get("name") == name and not d.get("deleted"):
                matches.append(c["key"])
        if len(data) < 100:
            break
        start += 100
        time.sleep(RATE_LIMIT_SEC)
    if not matches:
        log(f"  ERROR: collection {name!r} not found")
        return None
    if len(matches) > 1:
        log(f"  WARNING: {len(matches)} live collections share that name; using {matches[0]}")
    log(f"  Found: {matches[0]}")
    return matches[0]

def get_item_fresh(item_key):
    """Fetch a single item fresh from the API (for version + current tags)."""
    ok, data, _ = zot_request("GET", f"/items/{item_key}")
    return data if ok else None

# ============================================================
# SOURCE MEMBERSHIP LOOKUP
# ============================================================
def build_source_map():
    """
    Return dict: collection_key -> source_short
    for every decision-bucket and queue collection under each screening parent.
    """
    log("Building collection→source map...")
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
    coll_to_source = {}

    for c in all_colls:
        chain = []
        cur = c
        while cur:
            chain.append(cur)
            if cur["key"] in parent_to_source:
                coll_to_source[c["key"]] = parent_to_source[cur["key"]]
                break
            if not cur.get("parent"):
                break
            cur = by_key.get(cur.get("data", {}).get("parentCollection", ""))
            if not cur:
                break

    log(f"  Mapped {len(coll_to_source)} collections to sources")
    return coll_to_source

def item_sources(item, coll_to_source):
    """Return set of source short-names for an item based on its collection memberships."""
    sources = set()
    for col_key in item.get("data", {}).get("collections", []):
        src = coll_to_source.get(col_key)
        if src:
            sources.add(src)
    return sources

# ============================================================
# TITLE NORMALIZATION & CLUSTERING
# ============================================================
def normalize_title(t):
    if not t:
        return ""
    t = t.lower()
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def title_tokens(t):
    return {tok for tok in normalize_title(t).split() if len(tok) >= 3}

def jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

def cluster_items(items, threshold):
    keys = [it["key"] for it in items]
    tokens = {it["key"]: title_tokens(it.get("data", {}).get("title", "")) for it in items}
    items_by_key = {it["key"]: it for it in items}

    parent = {k: k for k in keys}
    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    n = len(keys)
    matches = 0
    for i in range(n):
        ti = tokens[keys[i]]
        if not ti:
            continue
        for j in range(i + 1, n):
            tj = tokens[keys[j]]
            if not tj or len(ti & tj) < 2:
                continue
            if jaccard(ti, tj) >= threshold:
                union(keys[i], keys[j])
                matches += 1

    log(f"  Clustering: {n} items, {matches} matched pairs")

    cluster_map = defaultdict(list)
    for k in keys:
        cluster_map[find(k)].append(items_by_key[k])

    # Sort within each cluster by venue rank, then year desc
    result = []
    for members in cluster_map.values():
        members.sort(key=lambda it: (
            venue_rank(it.get("data", {}).get("itemType", "")),
            -int((it.get("data", {}).get("date", "") or "")[:4])
            if (it.get("data", {}).get("date", "") or "")[:4].isdigit() else 0
        ))
        result.append(members)
    result.sort(key=lambda c: -len(c))
    return result

# ============================================================
# TAG PLAN
# ============================================================
def build_plan(clusters, coll_to_source):
    """
    For each cluster, build the list of tag additions needed.
    Returns:
      plan: list of {key, title, role, canonical_key, tags_to_add, current_tags,
                     has_human_decision, flagged}
    """
    plan = []
    flagged = []

    for cluster in clusters:
        if len(cluster) < 2:
            # Singleton in 00-Dups — skip with a note
            log(f"  SINGLETON in cluster: {cluster[0]['key']} — skipping")
            continue

        canonical = cluster[0]
        canonical_key = canonical["key"]
        superseded = cluster[1:]

        # Collect all sources across the entire cluster
        cluster_sources = set()
        for it in cluster:
            cluster_sources |= item_sources(it, coll_to_source)

        # ---- CANONICAL ----
        canon_data = canonical.get("data", {})
        canon_current_tags = {t.get("tag", "") for t in canon_data.get("tags", [])}
        # Add source tags from ALL siblings
        canon_source_tags = {f"source:{s}" for s in cluster_sources}
        canon_new_tags = sorted(canon_source_tags - canon_current_tags)
        plan.append({
            "key": canonical_key,
            "title": canon_data.get("title", "")[:120],
            "role": "CANONICAL",
            "canonical_key": canonical_key,
            "current_tags": sorted(canon_current_tags),
            "tags_to_add": canon_new_tags,
            "has_human_decision": any(t.startswith("s1:human:") for t in canon_current_tags),
            "flagged": False,
        })

        # ---- SUPERSEDED ----
        for it in superseded:
            d = it.get("data", {})
            current_tags = {t.get("tag", "") for t in d.get("tags", [])}
            new_tags = set()

            # Source tags for its own memberships
            own_sources = item_sources(it, coll_to_source)
            for s in own_sources:
                new_tags.add(f"source:{s}")

            # superseded-by tag
            new_tags.add(f"superseded-by:{canonical_key}")

            # Check for existing human decision tag — flag if present
            human_tags = {t for t in current_tags if t.startswith("s1:human:")}
            is_flagged = bool(human_tags)
            if is_flagged:
                new_tags.add("review:superseded-has-decision")
                flagged.append({
                    "key": it["key"],
                    "title": d.get("title", "")[:120],
                    "canonical_key": canonical_key,
                    "canonical_title": canon_data.get("title", "")[:120],
                    "item_type": d.get("itemType", ""),
                    "canonical_type": canon_data.get("itemType", ""),
                    "human_tags": "|".join(sorted(human_tags)),
                    "sources": "|".join(sorted(own_sources)),
                })

            tags_to_add = sorted(new_tags - current_tags)
            plan.append({
                "key": it["key"],
                "title": d.get("title", "")[:120],
                "role": "SUPERSEDED",
                "canonical_key": canonical_key,
                "current_tags": sorted(current_tags),
                "tags_to_add": tags_to_add,
                "has_human_decision": is_flagged,
                "flagged": is_flagged,
            })

    return plan, flagged

# ============================================================
# WRITE CSVs
# ============================================================
def write_plan_csv(plan, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "title", "role", "canonical_key", "current_tags",
                    "tags_to_add", "has_human_decision", "flagged"])
        for p in plan:
            w.writerow([
                p["key"], p["title"], p["role"], p["canonical_key"],
                "|".join(p["current_tags"]),
                "|".join(p["tags_to_add"]),
                "yes" if p["has_human_decision"] else "",
                "yes" if p["flagged"] else "",
            ])

def write_flagged_csv(flagged, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "title", "item_type", "canonical_key", "canonical_title",
                    "canonical_type", "human_tags", "sources", "action_needed"])
        for item in flagged:
            w.writerow([
                item["key"], item["title"], item["item_type"],
                item["canonical_key"], item["canonical_title"],
                item["canonical_type"], item["human_tags"], item["sources"],
                "Review: superseded item has human decision tag — verify canonical is correct",
            ])

# ============================================================
# APPLY
# ============================================================
def apply_plan(plan, api_key):
    to_apply = [p for p in plan if p["tags_to_add"]]
    log(f"\nApplying tags to {len(to_apply)} items...")
    successes = 0
    failures = []

    for i, p in enumerate(to_apply, 1):
        # Re-fetch for current version and tags
        item = get_item_fresh(p["key"])
        if not item:
            log(f"  FAIL {p['key']}: fetch failed")
            failures.append((p["key"], "fetch failed"))
            continue

        version = item.get("version", 0)
        current_tags = {t.get("tag", "") for t in item.get("data", {}).get("tags", [])}
        all_tags = sorted(current_tags | set(p["tags_to_add"]))
        tag_objects = [{"tag": t} for t in all_tags]

        ok, resp, _ = zot_request(
            "PATCH", f"/items/{p['key']}",
            body={"tags": tag_objects},
            api_key=api_key,
            headers={"If-Unmodified-Since-Version": str(version)},
        )
        if ok:
            successes += 1
            if i % 25 == 0 or i == len(to_apply):
                log(f"  [{i}/{len(to_apply)}] success={successes} fail={len(failures)}")
        else:
            failures.append((p["key"], str(resp)[:200]))
            log(f"  FAIL {p['key']}: {resp}")
        time.sleep(RATE_LIMIT_SEC)

    log(f"\nApply complete. Successes: {successes}, Failures: {len(failures)}")
    if failures:
        log("First 10 failures:")
        for k, e in failures[:10]:
            log(f"  {k}: {e}")
    return successes, failures

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="Write tags via RW key. Default is dry-run.")
    parser.add_argument("--threshold", type=float, default=TITLE_THRESHOLD,
                        help=f"Title Jaccard similarity threshold (default {TITLE_THRESHOLD})")
    args = parser.parse_args()

    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    log("=== Superseded relationship tag cleanup ===")
    log(f"Mode: {'APPLY (writes)' if args.apply else 'DRY-RUN (no writes)'}")
    log(f"Title threshold: {args.threshold}")

    # Find 00-Dups
    dups_key = find_live_collection(DUPS_COLLECTION_NAME)
    if not dups_key:
        sys.exit(1)

    # Fetch items
    log(f"\nFetching items from {DUPS_COLLECTION_NAME}...")
    items = get_collection_items(dups_key)
    log(f"  {len(items)} items")

    # Build source map
    coll_to_source = build_source_map()

    # Cluster
    log(f"\nClustering by title similarity (threshold={args.threshold})...")
    clusters = cluster_items(items, args.threshold)
    multi = sum(1 for c in clusters if len(c) >= 2)
    singletons = sum(1 for c in clusters if len(c) == 1)
    log(f"  Multi-item clusters: {multi}")
    log(f"  Singletons (skipped): {singletons}")

    # Build plan
    log(f"\nBuilding tag plan...")
    plan, flagged = build_plan(clusters, coll_to_source)

    # Summary
    canonicals = [p for p in plan if p["role"] == "CANONICAL"]
    superseded = [p for p in plan if p["role"] == "SUPERSEDED"]
    needs_tags = [p for p in plan if p["tags_to_add"]]

    log(f"\n=== PLAN SUMMARY ===")
    log(f"Canonical items:              {len(canonicals)}")
    log(f"Superseded items:             {len(superseded)}")
    log(f"Items needing new tags:       {len(needs_tags)}")
    log(f"Total new tags to add:        {sum(len(p['tags_to_add']) for p in needs_tags)}")
    log(f"Flagged (superseded+decision):{len(flagged)}")

    # Write output files
    write_plan_csv(plan, "superseded_tag_plan.csv")
    log(f"\nWrote superseded_tag_plan.csv")

    write_flagged_csv(flagged, "flagged_superseded.csv")
    log(f"Wrote flagged_superseded.csv ({len(flagged)} items)")

    if flagged:
        log(f"\n⚠️  {len(flagged)} superseded items have existing s1:human:* tags — review flagged_superseded.csv")
        for f in flagged[:5]:
            log(f"  {f['key']}: {f['human_tags']} | {f['title'][:60]}")
        if len(flagged) > 5:
            log(f"  ... and {len(flagged)-5} more")

    if not args.apply:
        log(f"\nDRY-RUN complete. Review superseded_tag_plan.csv and flagged_superseded.csv.")
        log(f"Re-run with --apply to write tags.")
        return

    successes, failures = apply_plan(plan, ZOTERO_API_KEY_RW)
    log(f"\n=== DONE ===")
    log(f"Tagged: {successes} items")
    log(f"Failures: {len(failures)}")
    if flagged:
        log(f"⚠️  Review flagged_superseded.csv — {len(flagged)} superseded items had human decision tags")

if __name__ == "__main__":
    main()
