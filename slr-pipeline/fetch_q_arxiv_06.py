#!/usr/bin/env python3
"""
Fetch arXiv results for Q-arXiv-06 (multi-agent adversarial oversight) and
create matching Zotero items in collection "Q-arXiv-06".

Query: (abs:"multi-agent" OR abs:"adversarial agent" OR abs:"LLM-as-judge"
        OR abs:"verifier agent" OR abs:"critic agent" OR abs:"agentic")
       AND (abs:"code review" OR abs:"code generation" OR abs:"AI-generated code")
       AND (abs:"human oversight" OR abs:"human-in-the-loop"
        OR abs:"scalable oversight" OR abs:"review")

Approx 118 results expected. NO client-side dedup — Zotero's built-in dedup
will be run after import.

Usage:
    cd ~/slr/arxiv-q06
    python3 fetch_q_arxiv_06.py              # dry-run: fetch only, no Zotero writes
    python3 fetch_q_arxiv_06.py --apply      # create Zotero items

Output:
    arxiv_results.json    — full arXiv fetch results (cached for resume)
    state.json            — resume checkpoint for Zotero creation
    create_plan.csv       — what would be created (dry-run) or was created (apply)
    fetch.log             — execution log
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
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
ZOTERO_API_KEY_RO = os.environ.get("VCSLR_ZOTERO_READ_KEY") or os.environ.get("ZOTERO_API_KEY", "")  # VCSLR read key (env / project .env)
ZOTERO_API_KEY_RW = os.environ.get("VCSLR_ZOTERO_WRITE_KEY") or os.environ.get("ZOTERO_WRITE_KEY", "")  # VCSLR write key (inline at --apply)
LIB = os.environ.get("VCSLR_ZOTERO_LIBRARY_ID", "6505702")
ZOTERO_BASE = f"https://api.zotero.org/groups/{LIB}"

TARGET_COLLECTION_NAME = "Q-arXiv-06"

ARXIV_QUERY = (
    '(abs:"multi-agent" OR abs:"adversarial agent" OR abs:"LLM-as-judge" '
    'OR abs:"verifier agent" OR abs:"critic agent" OR abs:"agentic") '
    'AND (abs:"code review" OR abs:"code generation" OR abs:"AI-generated code") '
    'AND (abs:"human oversight" OR abs:"human-in-the-loop" '
    'OR abs:"scalable oversight" OR abs:"review")'
)

ARXIV_BASE = "http://export.arxiv.org/api/query"
ARXIV_PAGE_SIZE = 50
ARXIV_RATE_LIMIT_SEC = 3.0   # arXiv API requests >=3s apart

ZOTERO_RATE_LIMIT_SEC = 0.3
ZOTERO_CREATE_BATCH_SIZE = 25  # POST up to 50; we use 25 to keep payloads safe

RESULTS_FILE = "arxiv_results.json"
STATE_FILE   = "state.json"
PLAN_CSV     = "create_plan.csv"
LOG_FILE     = "fetch.log"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ============================================================
# ATOMIC WRITES
# ============================================================
def save_json(path, obj):
    tmp = path + ".tmp"
    bak = path + ".bak"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        try:
            os.replace(path, bak)
        except OSError:
            pass
    os.replace(tmp, path)

def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        bak = path + ".bak"
        if os.path.exists(bak):
            log(f"  {path} unreadable ({e}); falling back to {bak}")
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

# ============================================================
# ARXIV FETCH
# ============================================================
def arxiv_fetch_page(start, max_results):
    params = {
        "search_query": ARXIV_QUERY,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "VibeCodingSLR/1.0 (research)")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            wait = min(60, 2 ** attempt) + 1
            log(f"  arXiv fetch error: {e}; retry in {wait}s (attempt {attempt+1}/5)")
            time.sleep(wait)
    return None

def parse_arxiv_entries(xml_text):
    """Parse Atom XML; return (total_results, list_of_entry_dicts)."""
    root = ET.fromstring(xml_text)
    total_el = root.find("opensearch:totalResults", NS)
    total = int(total_el.text) if total_el is not None and total_el.text else 0
    entries = []
    for e in root.findall("atom:entry", NS):
        id_el = e.find("atom:id", NS)
        arxiv_url = id_el.text.strip() if id_el is not None else ""
        m = re.match(r"https?://arxiv\.org/abs/(.+?)(v\d+)?$", arxiv_url)
        arxiv_id = m.group(1) if m else arxiv_url
        version = (m.group(2) or "").lstrip("v") if m else ""
        
        title_el = e.find("atom:title", NS)
        title = " ".join(title_el.text.split()) if title_el is not None and title_el.text else ""
        
        summary_el = e.find("atom:summary", NS)
        abstract = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
        abstract = re.sub(r"\s+", " ", abstract).strip()
        
        published_el = e.find("atom:published", NS)
        published = published_el.text if published_el is not None else ""
        date = published[:10] if published else ""
        
        authors = []
        for au in e.findall("atom:author", NS):
            name_el = au.find("atom:name", NS)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())
        
        doi = ""
        doi_el = e.find("arxiv:doi", NS)
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip()
        
        primary_cat = ""
        pc_el = e.find("arxiv:primary_category", NS)
        if pc_el is not None:
            primary_cat = pc_el.get("term", "")
        
        url_html = arxiv_url
        url_pdf = ""
        for link in e.findall("atom:link", NS):
            rel = link.get("rel", "")
            href = link.get("href", "")
            title_attr = link.get("title", "")
            if title_attr == "pdf":
                url_pdf = href
            elif rel == "alternate":
                url_html = href
        
        entries.append({
            "arxiv_id": arxiv_id,
            "version": version,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "date": date,
            "doi": doi,
            "primary_category": primary_cat,
            "url_html": url_html,
            "url_pdf": url_pdf,
        })
    return total, entries

def fetch_all_arxiv():
    """Fetch all arXiv results, paginating. Cache to RESULTS_FILE for resume."""
    cached = load_json(RESULTS_FILE)
    if cached:
        log(f"Loaded {len(cached['entries'])} entries from cache (total expected: {cached['total']})")
        if len(cached["entries"]) >= cached["total"]:
            log("  Fetch complete per cache; skipping arXiv re-fetch.")
            return cached["entries"]
        else:
            log("  Cache incomplete; resuming fetch.")
            entries = cached["entries"]
            total = cached["total"]
            start = len(entries)
    else:
        log("Starting arXiv fetch...")
        entries = []
        total = None
        start = 0
    
    while True:
        log(f"  Fetching start={start}, page_size={ARXIV_PAGE_SIZE}...")
        xml_text = arxiv_fetch_page(start, ARXIV_PAGE_SIZE)
        if xml_text is None:
            log("  Fetch failed; stopping. Re-run to resume.")
            sys.exit(2)
        
        page_total, page_entries = parse_arxiv_entries(xml_text)
        if total is None:
            total = page_total
            log(f"  Total results reported by arXiv: {total}")
        if not page_entries:
            log("  Empty page; assuming end of results.")
            break
        
        # Dedup only against entries already fetched in THIS run (in case arXiv returns
        # overlapping pages). NOT dedup against Zotero — that's deferred to client.
        existing_ids = {e["arxiv_id"] for e in entries}
        new_entries = [e for e in page_entries if e["arxiv_id"] not in existing_ids]
        entries.extend(new_entries)
        log(f"  Page returned {len(page_entries)} ({len(new_entries)} new); total now {len(entries)}/{total}")
        
        save_json(RESULTS_FILE, {"total": total, "entries": entries,
                                  "fetched_at": datetime.now(timezone.utc).isoformat()})
        
        if len(entries) >= total or len(page_entries) < ARXIV_PAGE_SIZE:
            break
        
        start += ARXIV_PAGE_SIZE
        time.sleep(ARXIV_RATE_LIMIT_SEC)
    
    log(f"arXiv fetch done: {len(entries)} entries")
    return entries

# ============================================================
# ZOTERO API
# ============================================================
def zot_request(method, path, body=None, api_key=None, headers=None, retries=8):
    url = f"{ZOTERO_BASE}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Zotero-API-Key", api_key or ZOTERO_API_KEY_RO)
            req.add_header("Zotero-API-Version", "3")
            if data is not None:
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
                wait = min(60, 2 ** attempt) + 1
                log(f"  Zotero HTTP {e.code} on {method} {path}; retry in {wait}s")
                time.sleep(wait)
                continue
            return False, f"HTTP {e.code}: {err_body}", {}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < retries - 1:
                wait = min(60, 2 ** attempt) + 1
                log(f"  Network error on {method} {path}: {e}; retry in {wait}s")
                time.sleep(wait)
                continue
            return False, str(e), {}
    return False, "max retries", {}

def find_collection_by_name(name):
    log(f"Looking up collection by name: {name!r}")
    start = 0
    matches = []
    while True:
        ok, data, _ = zot_request("GET", f"/collections?limit=100&start={start}")
        if not ok:
            log(f"  ERROR scanning collections: {data}")
            return None
        if not data:
            break
        for c in data:
            if c.get("data", {}).get("name", "") == name:
                matches.append(c["key"])
        if len(data) < 100:
            break
        start += 100
        time.sleep(ZOTERO_RATE_LIMIT_SEC)
    if not matches:
        log(f"  Collection {name!r} not found")
        return None
    if len(matches) > 1:
        log(f"  WARNING: {len(matches)} collections share that name; using first: {matches[0]}")
    log(f"  Found: {matches[0]}")
    return matches[0]

# ============================================================
# ZOTERO ITEM CONSTRUCTION
# ============================================================
def build_zotero_item(entry, collection_key):
    """Build a Zotero 'preprint' item dict for an arXiv entry."""
    creators = []
    for name in entry["authors"]:
        if "," in name:
            parts = [p.strip() for p in name.split(",", 1)]
            last = parts[0]
            first = parts[1] if len(parts) > 1 else ""
        else:
            tokens = name.split()
            if len(tokens) >= 2:
                last = tokens[-1]
                first = " ".join(tokens[:-1])
            else:
                last = name
                first = ""
        creators.append({
            "creatorType": "author",
            "firstName": first,
            "lastName": last,
        })
    
    item = {
        "itemType": "preprint",
        "title": entry["title"],
        "creators": creators,
        "abstractNote": entry["abstract"],
        "date": entry["date"],
        "repository": "arXiv",
        "archiveID": f"arXiv:{entry['arxiv_id']}",
        "url": entry["url_html"],
        "DOI": entry["doi"],
        "extra": (f"primaryCategory: {entry['primary_category']}\nversion: v{entry['version']}"
                  if entry["version"]
                  else f"primaryCategory: {entry['primary_category']}"),
        "collections": [collection_key],
        "tags": [],
    }
    return item

# ============================================================
# WRITE PLAN CSV
# ============================================================
def write_plan_csv(to_create):
    with open(PLAN_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["action", "arxiv_id", "title", "date", "doi", "url"])
        for e in to_create:
            w.writerow(["CREATE", e["arxiv_id"], e["title"][:200], e["date"], e["doi"], e["url_html"]])

# ============================================================
# CREATE ITEMS IN BATCHES
# ============================================================
def create_items(to_create, collection_key, api_key):
    log(f"\nCreating {len(to_create)} items in Zotero...")
    state = load_json(STATE_FILE) or {"created_arxiv_ids": []}
    created = set(state["created_arxiv_ids"])
    remaining = [e for e in to_create if e["arxiv_id"] not in created]
    log(f"  Already created in prior script run: {len(created)}; remaining: {len(remaining)}")
    
    successes = 0
    failures = []
    for batch_start in range(0, len(remaining), ZOTERO_CREATE_BATCH_SIZE):
        batch = remaining[batch_start:batch_start + ZOTERO_CREATE_BATCH_SIZE]
        items = [build_zotero_item(e, collection_key) for e in batch]
        ok, resp, _ = zot_request("POST", "/items", body=items, api_key=api_key)
        if not ok:
            log(f"  BATCH FAILED ({batch_start}): {resp}")
            failures.append((batch_start, str(resp)[:500]))
            break
        
        succ = resp.get("successful", {})
        fail = resp.get("failed", {})
        for idx_str in succ:
            idx = int(idx_str)
            arxiv_id = batch[idx]["arxiv_id"]
            created.add(arxiv_id)
            successes += 1
        for idx_str, fail_data in fail.items():
            idx = int(idx_str)
            arxiv_id = batch[idx]["arxiv_id"]
            failures.append((arxiv_id, fail_data))
            log(f"  FAIL {arxiv_id}: {fail_data}")
        
        state["created_arxiv_ids"] = sorted(created)
        save_json(STATE_FILE, state)
        log(f"  Batch {batch_start//ZOTERO_CREATE_BATCH_SIZE + 1}: success+={len(succ)}, fail+={len(fail)}; total created={successes}")
        time.sleep(ZOTERO_RATE_LIMIT_SEC)
    
    log(f"\nCreate complete. Successes: {successes}, Failures: {len(failures)}")
    if failures:
        log("Failures:")
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
                        help="Actually create items in Zotero. Default is dry-run.")
    args = parser.parse_args()
    
    log(f"=== Q-arXiv-06 fetch + create ===")
    log(f"Mode: {'APPLY (writes to Zotero)' if args.apply else 'DRY-RUN (no writes)'}")
    log(f"Note: Client-side dedup will be run in Zotero after import; no API-side dedup performed.")
    
    # Step 1: Fetch from arXiv (cached)
    entries = fetch_all_arxiv()
    log(f"\nFetched {len(entries)} total arXiv entries")
    
    # Step 2: Resolve target collection
    coll_key = find_collection_by_name(TARGET_COLLECTION_NAME)
    if coll_key is None:
        log(f"FATAL: target collection {TARGET_COLLECTION_NAME!r} not found in Zotero. Create it first.")
        sys.exit(1)
    
    log(f"\n=== PLAN ===")
    log(f"  Fetched from arXiv: {len(entries)}")
    log(f"  To create in {TARGET_COLLECTION_NAME}: {len(entries)} (no dedup; Zotero will handle post-import)")
    
    write_plan_csv(entries)
    log(f"  Plan written to {PLAN_CSV}")
    
    log(f"\nFirst 5 items planned for creation:")
    for e in entries[:5]:
        log(f"  {e['arxiv_id']} ({e['date']}): {e['title'][:80]}")
    
    if not args.apply:
        log(f"\nDRY-RUN complete. Review {PLAN_CSV} and re-run with --apply to create.")
        return
    
    if not entries:
        log("\nNothing to create. Done.")
        return
    
    # Step 3: Create
    successes, failures = create_items(entries, coll_key, ZOTERO_API_KEY_RW)
    log(f"\n=== DONE ===")
    log(f"Created: {successes} items in {TARGET_COLLECTION_NAME}")
    log(f"Failures: {len(failures)}")
    log(f"\nNext step: Run Zotero client-side dedup on the library.")

if __name__ == "__main__":
    main()
