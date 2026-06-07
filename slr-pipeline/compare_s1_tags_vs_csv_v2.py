#!/usr/bin/env python3
"""
compare_s1_tags_vs_csv_v2.py   (READ-ONLY)

Compares the Pass-1 decision implied by each item's s1:* tags against the
decision recorded in the original Pass-1 screening CSVs, to decide which is
the authoritative ground truth for restoring Pass-1 per-source membership.

Writes NOTHING to Zotero.

Two CSV formats handled:
  NON-SSRN (headered): item_key,title,abstract,authors,year,item_type,source,
                       claude_decision,human_decision,...,rationale,...
     union = human_decision if present else claude_decision
     source column is pipe-delimited (e.g. "arxiv|coursework|ieee")
  SSRN (headerless):   item_key,decision,theme,title,authors,year,url,rationale,abstract...
     union = decision ; source = ssrn

Usage:
  python3 compare_s1_tags_vs_csv_v2.py \
      --nonssrn ~/slr/nonssrn-decisions-2026-05-25.csv \
      --ssrn    ~/slr/ssrn-decisions-2026-05-25.csv
"""
import argparse, csv, json, os, sys, time, urllib.request
from collections import defaultdict, Counter

csv.field_size_limit(sys.maxsize)

def _load_env_file():
    """Project-scoped .env loader: $ZOTERO_ENV_FILE, else walk up from CWD to
    repo root for .env. Never overwrites already-set env vars."""
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

KEY = os.environ.get("VCSLR_ZOTERO_READ_KEY") or os.environ.get("ZOTERO_API_KEY", "")  # VCSLR read key (env / project .env)
BASE = "https://api.zotero.org/groups/" + os.environ.get("VCSLR_ZOTERO_LIBRARY_ID", "6505702")

def zget(path):
    req = urllib.request.Request(f"{BASE}{path}",
        headers={"Zotero-API-Key": KEY, "Zotero-API-Version": "3"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())

SOURCE_PARENTS = {
    "ieee":"7XHWH8NM","scopus":"2RWBC7QH","wos":"E7AS4HD4","arxiv":"YK2CHQLN",
    "acm":"G4IIYGV6","practitioner":"7FL4M8HN","coursework":"IF299TAY",
    "cao":"GP3U9EX8","naimi-references":"ZXIXRWKG","naimi-chapters":"DIDV7BKH",
    "ssrn":"F9A9883N",
}
# map CSV source tokens -> our source keys
SRC_ALIAS = {
    "ieee":"ieee","scopus":"scopus","wos":"wos","arxiv":"arxiv","acm":"acm",
    "coursework":"coursework","practitioner":"practitioner","cao":"cao",
    "naimi-references":"naimi-references","naimi-book":"naimi-chapters",
    "naimi-chapters":"naimi-chapters","ssrn":"ssrn",
}
BUCKETS = {"01-Keep":"keep","02-Maybe":"maybe","03-Discard":"discard"}

def norm(d):
    if not d: return ""
    d=d.strip().lower()
    return {"keep":"keep","maybe":"maybe","discard":"discard"}.get(d,"")

def load_nonssrn(path):
    """item_key -> {'union':dec, 'sources':set(...), 'human':dec, 'claude':dec}"""
    out={}
    with open(path,newline="",encoding="utf-8") as f:
        rd=csv.reader(f)
        header=next(rd)  # skip header
        for r in rd:
            if len(r)<9: continue
            k=r[0].strip()
            claude=norm(r[7]); human=norm(r[8])
            union= human or claude
            srcs=set()
            for tok in r[6].split("|"):
                tok=tok.strip().lower()
                if tok in SRC_ALIAS: srcs.add(SRC_ALIAS[tok])
            out[k]={"union":union,"sources":srcs,"human":human,"claude":claude}
    return out

def load_ssrn(path):
    """item_key -> {'union':dec, 'sources':{'ssrn'}}"""
    out={}
    with open(path,newline="",encoding="utf-8") as f:
        rd=csv.reader(f)
        for r in rd:
            if len(r)<2: continue
            k=r[0].strip()
            dec=norm(r[1])
            if not dec: continue
            out[k]={"union":dec,"sources":{"ssrn"},"human":"","claude":dec}
    return out

def fetch_all_collections():
    colls=[]; start=0
    while True:
        d=zget(f"/collections?limit=100&start={start}")
        colls+=d
        if len(d)<100: break
        start+=100; time.sleep(0.2)
    return colls

def fetch_bucket(coll_key):
    out=[]; start=0
    while True:
        items=zget(f"/collections/{coll_key}/items/top?limit=100&start={start}&include=data")
        if not items: break
        for it in items:
            tags={t['tag'] for t in it['data'].get('tags',[]) if t['tag'].startswith('s1:')}
            out.append((it['key'],tags))
        if len(items)<100: break
        start+=100; time.sleep(0.15)
    return out

def tag_union(tags):
    def dec_for(s):
        for d in ("keep","maybe","discard"):
            if f"s1:{s}:{d}" in tags: return d
        return ""
    return dec_for("human") or dec_for("claude") or ""

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--nonssrn",required=True)
    ap.add_argument("--ssrn",required=True)
    args=ap.parse_args()

    csv_map=load_nonssrn(args.nonssrn)
    ssrn_map=load_ssrn(args.ssrn)
    print(f"non-SSRN rows: {len(csv_map)}   SSRN rows: {len(ssrn_map)}")
    # merge (no key overlap expected)
    merged=dict(csv_map); merged.update(ssrn_map)
    print(f"merged unique keys: {len(merged)}")
    print("non-SSRN union dist:", Counter(v['union'] for v in csv_map.values()))
    print("SSRN union dist:    ", Counter(v['union'] for v in ssrn_map.values()))
    print("non-SSRN human-present:", sum(1 for v in csv_map.values() if v['human']))
    print()

    colls=fetch_all_collections()
    by_parent=defaultdict(list); name_of={}
    for c in colls:
        name_of[c['key']]=c['data']['name'].strip()
        p=c['data'].get('parentCollection')
        if p: by_parent[p].append(c['key'])

    print(f"{'source':<18}{'bucket':<11}{'n':>6}  tag=csv  tag!=csv  tagmiss  csvmiss")
    print("-"*74)
    g=Counter(); samples=[]
    for src,parent in SOURCE_PARENTS.items():
        for child in by_parent.get(parent,[]):
            bn=name_of[child]
            if bn not in BUCKETS: continue
            items=fetch_bucket(child)
            eq=ne=tmiss=cmiss=0
            for key,tags in items:
                tu=tag_union(tags)
                rec=merged.get(key)
                cu=rec['union'] if rec else ""
                if not tu: tmiss+=1
                if not cu: cmiss+=1
                if tu and cu:
                    if tu==cu: eq+=1
                    else:
                        ne+=1
                        if len(samples)<20:
                            samples.append((src,bn,key,f"tag={tu}",f"csv={cu}"))
            print(f"{src:<18}{bn:<11}{len(items):>6}  {eq:>6}  {ne:>7}  {tmiss:>7}  {cmiss:>7}")
            g['n']+=len(items); g['eq']+=eq; g['ne']+=ne; g['tmiss']+=tmiss; g['cmiss']+=cmiss
    print("-"*74)
    print(f"{'TOTAL':<29}{g['n']:>6}  {g['eq']:>6}  {g['ne']:>7}  {g['tmiss']:>7}  {g['cmiss']:>7}")
    print("\n=== Interpretation ===")
    print(f"  tags == csv:            {g['eq']}")
    print(f"  tags != csv:            {g['ne']}")
    print(f"  in bucket, no s1 tag:   {g['tmiss']}")
    print(f"  in bucket, not in CSV:  {g['cmiss']}")
    if samples:
        print("\n  Sample disagreements:")
        for s in samples: print("   ",s)
    print("\nReminder: current bucket membership is post-recovery, NOT ground truth.")
    print("We are only judging whether tags and CSV agree on the decision.")

if __name__=="__main__":
    main()
