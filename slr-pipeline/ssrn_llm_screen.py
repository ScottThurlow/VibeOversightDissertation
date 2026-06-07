#!/usr/bin/env python3
"""
SSRN bulk-screening via Claude Code SDK (uses your Max subscription).

Usage:
    cd ~/slr/ssrn
    python3 ssrn_llm_screen.py

Output:
    decisions.csv        - audit trail of every decision (keep + maybe + discard)
    state.json           - resume checkpoint (re-run to continue)
    progress.log         - human-readable progress
    decisions.jsonl      - structured decisions (all of them, keep + discard)

The script reads SSRN Queue items from Zotero (read-only), passes title+abstract to
Claude via `claude -p`, gets a structured JSON decision, and logs to CSV.
NO ZOTERO WRITES. The morning workflow is to review the CSV and bulk-apply.
"""
import json, urllib.request, urllib.error, subprocess, sys, time, csv, os, random

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
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================
ZOTERO_API_KEY = os.environ.get("VCSLR_ZOTERO_READ_KEY") or os.environ.get("ZOTERO_API_KEY", "")  # VCSLR read key (env / project .env)
LIB = os.environ.get("VCSLR_ZOTERO_LIBRARY_ID", "6505702")
BASE = f"https://api.zotero.org/groups/{LIB}"
QUEUE_COLLECTION = "DXPF25DB"

WORKDIR = os.path.expanduser("~/slr/ssrn")
CSV_PATH = f"{WORKDIR}/decisions.csv"
STATE_PATH = f"{WORKDIR}/state.json"
LOG_PATH = f"{WORKDIR}/progress.log"
DECISIONS_PATH = f"{WORKDIR}/decisions.jsonl"

# How long to wait between Claude calls (rate-limit politeness)
CLAUDE_RATE_LIMIT_SEC = 30.0
ZOTERO_RATE_LIMIT_SEC = 0.3

# Checkpoint state every N items
CHECKPOINT_EVERY = 1

# Model selection (Sonnet for cost; Haiku is even cheaper but might miss nuance)
CLAUDE_MODEL = "sonnet"  # 'sonnet' / 'opus' / 'haiku' — claude CLI accepts shortnames

# ============================================================
# SCREENING RUBRIC
# ============================================================
RUBRIC = """You are screening academic papers for a systematic literature review (SLR) on:
"How organizations manage risk from AI-generated code and 'vibe coding', particularly the
challenge of scalable human oversight when AI dramatically increases code volume."

Your job: read the title and abstract, output ONE of three decisions:
  - "discard"     → clearly off-topic, no transferable contribution
  - "maybe"       → uncertain or peripheral, leave for human reviewer
  - "keep"        → relevant or potentially relevant

DISCARD if the paper is purely about ANY of these (and lacks any oversight/governance angle):
  - K-12 / pedagogy of AI tools (classroom use of ChatGPT, AI literacy for students, cheating detection in education)
  - Autonomous weapons systems specifically (lethal autonomous weapons, drone swarms, military AI hardware)
  - Voting / elections / political campaigns specifically
  - Narrow clinical AI applications (cancer detection, retinopathy, single-disease diagnosis) WITHOUT a governance lens
  - Pure ML/technical papers (new architectures, benchmarks, hyperparameter tuning, ablation studies) with no oversight angle
  - Algorithmic trading / high-frequency trading / quantitative finance specifically
  - Marketing/advertising/recommender system technical work without governance
  - AI as a writing aid for academic papers (LLM as co-author essays — but DETECTION-AT-SCALE methodology is KEEP)
  - Single-author vendor whitepapers without methodology

KEEP regardless of domain if the paper is about ANY of these:
  - Vibe coding / AI code generation / Copilot / LLM-based coding tools
  - Human oversight, scalable oversight, human-in-the-loop, meaningful human control
  - AI governance frameworks, AI risk management, AI auditing, accountability
  - EU AI Act, NIST AI RMF, GDPR Article 22, AI regulation/compliance
  - Organizational adoption of AI at scale (case studies, empirical studies)
  - AI alignment, AI safety, RLHF as governance mechanism
  - Code review research generally (capacity, fatigue, scalability)
  - Methodology for detecting AI output at scale (transferable to detecting AI-generated code)
  - Responsibility gap, legal liability for AI systems

MAYBE for borderline cases — when a paper is in a discard category but has SOME governance/oversight/regulatory angle that makes it potentially transferable.

DEFAULT TO MAYBE when uncertain. Only "discard" when clearly off-topic.

Output ONLY a single JSON object on one line, no other text:
{"decision":"keep|maybe|discard","category":"category-tag-or-null","rationale":"one sentence explaining why"}

The category tag should be one of: K12pedagogy, WeaponsSpecific, VotingDemocracy, ClinicalNarrow, PureML, FinanceTrading, MarketingAds, AISciWriting, VendorWhitepaper, OffTopicOther — or null for keep/maybe.
"""

# ============================================================
# ZOTERO API
# ============================================================
def zot_get(path, retries=5):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{BASE}{path}")
            req.add_header("Zotero-API-Key", ZOTERO_API_KEY)
            req.add_header("Zotero-API-Version", "3")
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read()), {k.lower(): v for k, v in r.headers.items()}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = 2 ** attempt + random.uniform(0, 1)
                log(f"  Zotero HTTP {e.code}, retry in {wait:.1f}s")
                time.sleep(wait)
                continue
            last_err = f"HTTP {e.code}"
        except Exception as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
    return None, {"error": last_err}

# ============================================================
# CLAUDE SDK CALL
# ============================================================
def call_claude(title, abstract):
    """
    Call `claude -p` headless mode with the screening rubric + item content.
    Returns dict with decision/category/rationale, or None on failure.
    """
    item_text = f"TITLE: {title}\n\nABSTRACT: {abstract or '(no abstract)'}"
    prompt = f"{RUBRIC}\n\nNow screen this item:\n\n{item_text}"
    
    # Use claude CLI in headless mode with bare output
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", CLAUDE_MODEL, "--output-format", "text"],
            capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return None, "claude-timeout"
    except FileNotFoundError:
        return None, "claude-not-found"
    
    if result.returncode != 0:
        stderr_lower = result.stderr.lower() if result.stderr else ""
        # Detect rate-limit errors and signal them distinctly so caller can back off
        rate_limit_signals = ["rate limit", "rate-limit", "rate_limit", "429",
                              "too many requests", "usage limit", "quota",
                              "claude usage limit", "approaching usage limit",
                              "5-hour", "5 hour"]
        if any(sig in stderr_lower for sig in rate_limit_signals):
            return None, f"RATE_LIMIT: {result.stderr[:300]}"
        return None, f"claude-rc-{result.returncode}: {result.stderr[:200]}"
    
    raw = result.stdout.strip()
    # Try to extract a JSON object — claude might output extra text
    # Find first { and last } to bracket the JSON
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            obj = json.loads(raw[start:end+1])
            return obj, None
        return None, f"no-json-found: {raw[:200]}"
    except json.JSONDecodeError as e:
        return None, f"json-error: {e} :: raw={raw[:200]}"

# ============================================================
# LOGGING
# ============================================================
def log(msg):
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def init_csv():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="") as f:
            csv.writer(f).writerow([
                "item_key", "decision", "category", "title", "authors", "year", "url",
                "rationale", "abstract"
            ])

def append_csv(row):
    with open(CSV_PATH, "a", newline="") as f:
        csv.writer(f).writerow(row)

def append_decisions(d):
    with open(DECISIONS_PATH, "a") as f:
        f.write(json.dumps(d) + "\n")

def load_state():
    if os.path.exists(STATE_PATH):
        return json.load(open(STATE_PATH))
    return {"all_keys": None, "processed": [], "discarded": 0, "kept": 0, "maybe": 0, "errors": 0}

def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)

# ============================================================
# QUEUE FETCH
# ============================================================
def get_queue_items():
    """Fetch all Queue items. Returns list of (key, title, abstract, authors, year, url)."""
    log("Fetching Queue items from Zotero...")
    items = []
    start = 0
    while True:
        data, hdrs = zot_get(f"/collections/{QUEUE_COLLECTION}/items/top?limit=100&start={start}")
        if data is None:
            log(f"  Zotero fetch failed at offset {start}: {hdrs.get('error','?')}")
            break
        if not data:
            break
        for it in data:
            d = it.get("data", {})
            creators = d.get("creators", [])
            authors = "; ".join(
                (c.get("lastName", "") or c.get("name", "")) for c in creators[:5]
            )
            year = (d.get("date", "") or "")[:4]
            items.append({
                "key": it["key"],
                "title": d.get("title", ""),
                "abstract": d.get("abstractNote", ""),
                "authors": authors,
                "year": year,
                "url": d.get("url", ""),
            })
        if len(data) < 100:
            break
        start += 100
        time.sleep(ZOTERO_RATE_LIMIT_SEC)
    return items

# ============================================================
# MAIN
# ============================================================
def main():
    os.makedirs(WORKDIR, exist_ok=True)
    # Append PID so we can identify and kill stale instances
    with open(os.path.join(WORKDIR, "pid.txt"), "a") as f:
        f.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
    init_csv()

    state = load_state()
    if state["all_keys"] is None:
        items = get_queue_items()
        state["all_keys"] = [it["key"] for it in items]
        # Cache items inline in state so we don't re-fetch on resume
        state["items_cache"] = {it["key"]: it for it in items}
        save_state(state)
        log(f"  Queue size: {len(items)}")
    else:
        log(f"Resuming with {len(state['all_keys'])} total items, {len(state['processed'])} already processed")

    items_cache = state.get("items_cache", {})
    processed_set = set(state["processed"])

    t_start = time.time()
    consecutive_errors = 0
    
    for i, k in enumerate(state["all_keys"]):
        if k in processed_set:
            continue
        
        item = items_cache.get(k)
        if not item:
            # Re-fetch single item if cache missing
            data, _ = zot_get(f"/items/{k}")
            if not data:
                log(f"[{i+1}] {k} fetch failed")
                state["errors"] += 1
                continue
            d = data["data"]
            creators = d.get("creators", [])
            item = {
                "key": k,
                "title": d.get("title", ""),
                "abstract": d.get("abstractNote", ""),
                "authors": "; ".join((c.get("lastName", "") or c.get("name", "")) for c in creators[:5]),
                "year": (d.get("date", "") or "")[:4],
                "url": d.get("url", ""),
            }

        # Call Claude
        time.sleep(CLAUDE_RATE_LIMIT_SEC)
        decision, err = call_claude(item["title"], item["abstract"])
        
        if decision is None:
            log(f"[{i+1}/{len(state['all_keys'])}] {k} CLAUDE ERROR: {err}")
            state["errors"] += 1
            consecutive_errors += 1
            # Special handling for rate limits: long backoff, don't count toward consecutive_errors
            if err and err.startswith("RATE_LIMIT"):
                consecutive_errors -= 1  # don't penalize for rate-limit
                # Save state before sleep so we can be killed cleanly
                save_state(state)
                # Try increasing backoff: 5min, then 15min, then 30min, then 60min
                rl_backoff_attempts = state.get("rl_backoff_attempts", 0)
                wait_sec = [300, 900, 1800, 3600][min(rl_backoff_attempts, 3)]
                log(f"  RATE LIMIT detected. Sleeping {wait_sec//60} minutes before retrying...")
                time.sleep(wait_sec)
                state["rl_backoff_attempts"] = rl_backoff_attempts + 1
                # Don't mark as processed; will retry this same item
                continue
            else:
                # Reset backoff counter on non-rate-limit errors
                state["rl_backoff_attempts"] = 0
            if consecutive_errors >= 5:
                log(f"  5 consecutive non-rate-limit errors — pausing 60s")
                time.sleep(60)
                consecutive_errors = 0
            continue
        consecutive_errors = 0
        state["rl_backoff_attempts"] = 0  # reset rate-limit backoff on any success
        
        # Validate decision shape
        d_val = decision.get("decision", "").lower()
        if d_val not in ("keep", "maybe", "discard"):
            log(f"[{i+1}] {k} INVALID DECISION: {decision}")
            state["errors"] += 1
            continue
        
        category = decision.get("category") or ""
        rationale = decision.get("rationale", "")[:300]
        
        # Log ALL decisions to CSV with full abstract
        if d_val == "discard":
            state["discarded"] += 1
        elif d_val == "maybe":
            state["maybe"] += 1
        else:
            state["kept"] += 1

        append_csv([
            k, d_val, category, item["title"], item["authors"], item["year"],
            item["url"], rationale, item["abstract"] or ""
        ])
        
        append_decisions({
            "key": k,
            "decision": d_val,
            "category": category,
            "rationale": rationale,
            "title": item["title"][:120],
        })
        
        state["processed"].append(k)
        
        # Save state after every call (cheap at this pace; avoids reprocessing on crash)
        save_state(state)
        # Log progress every 10 items
        if len(state["processed"]) % 10 == 0:
            elapsed = time.time() - t_start
            done = len(state["processed"]) - len(processed_set)
            rate = done / elapsed if elapsed > 0 else 0
            remaining = len(state["all_keys"]) - len(state["processed"])
            eta_min = (remaining / rate) / 60 if rate > 0 else 0
            log(f"  [{len(state['processed'])}/{len(state['all_keys'])}] discard={state['discarded']} maybe={state['maybe']} keep={state['kept']} err={state['errors']} rate={rate:.2f}/s eta={eta_min:.0f}min")
    
    save_state(state)
    log(f"\n=== DONE ===")
    log(f"Total processed: {len(state['processed'])}")
    log(f"Discarded: {state['discarded']}")
    log(f"Maybe: {state['maybe']}")
    log(f"Kept: {state['kept']}")
    log(f"Errors: {state['errors']}")
    log(f"\nCSV: {CSV_PATH}")
    log(f"Decisions: {DECISIONS_PATH}")

if __name__ == "__main__":
    main()
