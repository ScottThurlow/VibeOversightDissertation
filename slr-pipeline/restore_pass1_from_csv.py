#!/usr/bin/env python3
"""
restore_pass1_from_csv.py

Restores Pass-1 per-source screening state (collection membership + s1:* tags)
from the original Pass-1 screening CSVs, which are treated as ground truth.

GROUND TRUTH
  non-SSRN (headered): cols ... item_key, ..., source(6), claude_decision(7),
                       human_decision(8), ...
       union = human_decision if present else claude_decision
       source = col 6, pipe-delimited (e.g. "arxiv|coursework|ieee")
  SSRN (headerless):   item_key(0), decision(1), ...
       union = decision ; source = ssrn

WHAT IT DOES (per item, for EACH source it belongs to):
  * compute union decision (human>claude; ssrn single)
  * ensure item is in that source's 01-Keep / 02-Maybe / 03-Discard per union
  * remove item from the OTHER two decision buckets in that source
  * preserve Imports, Phase 2, and every non-screening collection
  * reconcile s1:* tags to mirror the CSV exactly:
        - write s1:claude:<dec> (always, from CSV)
        - write s1:human:<dec>  (only when CSV has a human decision)
        - remove any other s1:* tag
        - leave s2:*, source:*, theme:*, etc. untouched
  * SKIP items currently in 04-Superseded (deliberate dedup state)
  * never touches naimi-chapters (not present in CSVs)

SAFETY
  * dry-run by default; writes only with --apply
  * writes proposed_pass1_restore.csv for review
  * uses read-only key unless --apply (then requires ZOTERO_WRITE_KEY env)

USAGE
  # dry run
  python3 restore_pass1_from_csv.py \
      --nonssrn ~/slr/nonssrn-decisions-2026-05-25.csv \
      --ssrn    ~/slr/ssrn-decisions-2026-05-25.csv

  # apply (after Zotero backup!)
  ZOTERO_WRITE_KEY=XXXX python3 restore_pass1_from_csv.py \
      --nonssrn ... --ssrn ... --apply
"""
import argparse, csv, json, os, sys, time, urllib.request, urllib.error
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

READ_KEY  = os.environ.get("ZOTERO_API_KEY", "")
WRITE_KEY = os.environ.get("ZOTERO_WRITE_KEY", "")
BASE = "https://api.zotero.org/groups/6505702"

SOURCE_PARENTS = {
    "ieee":"7XHWH8NM","scopus":"2RWBC7QH","wos":"E7AS4HD4","arxiv":"YK2CHQLN",
    "acm":"G4IIYGV6","practitioner":"7FL4M8HN","coursework":"IF299TAY",
    "cao":"GP3U9EX8","naimi-references":"ZXIXRWKG","naimi-chapters":"DIDV7BKH",
    "ssrn":"F9A9883N",
}
# naimi-chapters intentionally excluded from restore (separate stream, not in CSVs)
RESTORE_SOURCES = {k for k in SOURCE_PARENTS if k != "naimi-chapters"}

SRC_ALIAS = {
    "ieee":"ieee","scopus":"scopus","wos":"wos","arxiv":"arxiv","acm":"acm",
    "coursework":"coursework","practitioner":"practitioner","cao":"cao",
    "naimi-references":"naimi-references","ssrn":"ssrn",
    # "naimi-book"/"naimi-chapters" deliberately NOT mapped -> skipped
}
BUCKET_NAME = {"keep":"01-Keep","maybe":"02-Maybe","discard":"03-Discard"}
DECISION_BUCKETS = ("01-Keep","02-Maybe","03-Discard")

def api_key(write=False): return WRITE_KEY if write else READ_KEY

def zget(path):
    req=urllib.request.Request(f"{BASE}{path}",
        headers={"Zotero-API-Key":READ_KEY,"Zotero-API-Version":"3"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read()), r.headers

def zget_item(key):
    req=urllib.request.Request(f"{BASE}/items/{key}",
        headers={"Zotero-API-Key":READ_KEY,"Zotero-API-Version":"3"})
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read())

def zpatch_item(key, version, payload):
    data=json.dumps(payload).encode()
    req=urllib.request.Request(f"{BASE}/items/{key}", data=data, method="PATCH",
        headers={"Zotero-API-Key":WRITE_KEY,"Zotero-API-Version":"3",
                 "Content-Type":"application/json",
                 "If-Unmodified-Since-Version":str(version)})
    with urllib.request.urlopen(req,timeout=60) as r:
        return r.status

def norm(d):
    if d is None: return ""
    d=str(d).strip().lower()
    return {"keep":"keep","maybe":"maybe","discard":"discard",
            "dsicard":"discard","discrad":"discard"}.get(d,"")

# ---------- load ground truth ----------
def load_nonssrn(path):
    out={}
    with open(path,newline="",encoding="utf-8") as f:
        rd=csv.reader(f); next(rd)  # header
        for r in rd:
            if len(r)<9: continue
            k=r[0].strip()
            claude=norm(r[7]); human=norm(r[8])
            union=human or claude
            if not union: continue
            srcs={SRC_ALIAS[t.strip().lower()] for t in r[6].split("|")
                  if t.strip().lower() in SRC_ALIAS}
            out[k]={"union":union,"sources":srcs,"human":human,"claude":claude}
    return out

def load_validator_sheets(ssrn_xlsx, nonssrn_xls):
    """Return {item_key: {'chatgpt':dec, 'gemini':dec}} merged across both
    workbooks' chatgpt/gemini sheets. Each sheet is (item_key, decision)."""
    import openpyxl, xlrd
    out=defaultdict(dict)
    # SSRN xlsx
    wb=openpyxl.load_workbook(ssrn_xlsx, read_only=True, data_only=True)
    for screener in ("chatgpt","gemini"):
        if screener not in wb.sheetnames: continue
        first=True
        for r in wb[screener].iter_rows(values_only=True):
            if first: first=False; continue
            if not r or not r[0]: continue
            k=str(r[0]).strip(); dec=norm(r[1] if len(r)>1 else "")
            if dec: out[k][screener]=dec
    # non-SSRN .xls (optional)
    if not nonssrn_xls:
        return out
    wb2=xlrd.open_workbook(nonssrn_xls)
    for screener in ("chatgpt","gemini"):
        if screener not in wb2.sheet_names(): continue
        sh=wb2.sheet_by_name(screener)
        for ridx in range(1, sh.nrows):
            k=str(sh.cell_value(ridx,0)).strip()
            dec=norm(sh.cell_value(ridx,1) if sh.ncols>1 else "")
            if k and dec: out[k][screener]=dec
    return out

def load_ssrn_xlsx(path):
    """Read ssrn-decisions.xlsx 'decisions' sheet.
    cols: item_key(0), decision/claude(1), ... human_decision(10).
    union = human if present else claude. norm() handles 'dsicard' typo."""
    import openpyxl
    out={}
    wb=openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws=wb["decisions"]
    first=True
    for r in ws.iter_rows(values_only=True):
        if first:  # header
            first=False; continue
        if not r or not r[0]: continue
        k=str(r[0]).strip()
        claude=norm(r[1] if len(r)>1 else "")
        human =norm(r[10] if len(r)>10 else "")
        if not (claude or human): continue
        out[k]={"union": human or claude, "sources":{"ssrn"},
                "human":human, "claude":claude}
    return out

# ---------- collection map ----------
def build_bucket_index():
    """Return: source -> {bucket_name -> coll_key},  and superseded coll keys set,
       and reverse map coll_key -> (source,bucket)."""
    colls=[]; start=0
    while True:
        data,_=zget(f"/collections?limit=100&start={start}")
        colls+=data
        if len(data)<100: break
        start+=100; time.sleep(0.15)
    name_of={c["key"]:c["data"]["name"].strip() for c in colls}
    by_parent=defaultdict(list)
    for c in colls:
        p=c["data"].get("parentCollection")
        if p: by_parent[p].append(c["key"])
    src_buckets=defaultdict(dict)      # source -> {bucket -> key}
    superseded=set()                   # all 04-Superseded keys (any source)
    rev={}                             # key -> (source,bucket)
    for src,parent in SOURCE_PARENTS.items():
        for child in by_parent.get(parent,[]):
            nm=name_of[child]
            if nm in DECISION_BUCKETS:
                src_buckets[src][nm]=child
                rev[child]=(src,nm)
            elif nm in ("04-Superseded","04-Superceded"):
                superseded.add(child)
    return src_buckets, superseded, rev, name_of

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--nonssrn",required=True)
    ap.add_argument("--ssrn",required=True,help="ssrn-decisions.xlsx (NOT the csv; xlsx has human_decision col)")
    ap.add_argument("--nonssrn-xls",default="",help="validation_workbook.xls with chatgpt/gemini sheets (non-SSRN validators)")
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--limit",type=int,default=0,help="process only N items (debug)")
    args=ap.parse_args()

    if args.apply and not WRITE_KEY:
        print("!! --apply requires ZOTERO_WRITE_KEY env var. Aborting."); sys.exit(1)
    if args.apply:
        print("⚠️  APPLY MODE: this writes to Zotero. Confirm you exported a backup")
        print("   (File → Export Library → Zotero RDF + Files) before proceeding.\n")

    gt=load_nonssrn(args.nonssrn); gt.update(load_ssrn_xlsx(args.ssrn))
    print(f"Ground-truth items: {len(gt)}")
    print("union dist:", Counter(v['union'] for v in gt.values()))

    # validator decisions (recorded as tags only; do NOT affect placement)
    validators = load_validator_sheets(args.ssrn, args.nonssrn_xls)
    n_cg=sum(1 for v in validators.values() if v.get("chatgpt"))
    n_gm=sum(1 for v in validators.values() if v.get("gemini"))
    print(f"validator coverage: chatgpt={n_cg}  gemini={n_gm}  (recorded as tags only)")

    src_buckets, superseded_keys, rev, name_of = build_bucket_index()
    # set of all decision-bucket keys we manage (for safe removal)
    managed_decision_keys=set()
    for s,bm in src_buckets.items():
        managed_decision_keys.update(bm.values())

    proposed=[]   # rows for review CSV
    stats=Counter()
    items=list(gt.items())
    if args.limit: items=items[:args.limit]

    for idx,(key,rec) in enumerate(items,1):
        if idx%200==0:
            print(f"  ...processed {idx}/{len(items)}  "
                  f"(changed={stats['items_changed']} skip_sup={stats['skipped_superseded']})",flush=True)
        union=rec["union"]
        target_sources={s for s in rec["sources"] if s in RESTORE_SOURCES}
        if not target_sources:
            stats["no_restore_source"]+=1
            continue
        try:
            it=zget_item(key)
        except urllib.error.HTTPError as e:
            stats["fetch_failed"]+=1
            proposed.append([key,union,"","ADD:-","DEL:-","","FETCH_FAILED_"+str(e.code)])
            continue
        data=it["data"]; version=it["version"]
        cur_colls=set(data.get("collections",[]))
        cur_tags=data.get("tags",[])

        # SKIP if currently in any 04-Superseded
        if cur_colls & superseded_keys:
            stats["skipped_superseded"]+=1
            proposed.append([key,union,"|".join(sorted(target_sources)),
                             "ADD:-","DEL:-","","SKIP_SUPERSEDED"])
            continue

        # ---- compute desired collection membership ----
        target_bucket_keys=set()
        for s in target_sources:
            bm=src_buckets.get(s,{})
            bk=bm.get(BUCKET_NAME[union])
            if bk: target_bucket_keys.add(bk)
        # other decision buckets in those sources, to remove from
        remove_bucket_keys=set()
        for s in target_sources:
            for bn,bk in src_buckets.get(s,{}).items():
                if bk not in target_bucket_keys:
                    remove_bucket_keys.add(bk)

        # new collection set:
        #  - keep everything that is NOT a managed decision bucket of THIS item's sources
        #    (preserves Imports, Phase 2, other-source buckets we don't manage here, etc.)
        #  - add the target bucket(s)
        #  - drop the remove bucket(s)
        new_colls=set(cur_colls)
        new_colls -= remove_bucket_keys
        new_colls |= target_bucket_keys

        coll_changed = (new_colls != cur_colls)

        # ---- compute desired s1 tags ----
        # Record ALL screeners that have a decision for this item, sourced
        # authoritatively from the workbooks. Tags RECORD what each screener
        # said; they do NOT affect placement (placement = union = human>claude,
        # computed above). We manage exactly these four screeners; any other
        # tag (source:*, theme:*, s2:*, etc.) is preserved untouched.
        MANAGED_SCREENERS = ("human", "claude", "chatgpt", "gemini")
        val = validators.get(key, {})
        desired_managed=set()
        if rec["claude"]:      desired_managed.add(f"s1:claude:{rec['claude']}")
        if rec["human"]:       desired_managed.add(f"s1:human:{rec['human']}")
        if val.get("chatgpt"): desired_managed.add(f"s1:chatgpt:{val['chatgpt']}")
        if val.get("gemini"):  desired_managed.add(f"s1:gemini:{val['gemini']}")
        def is_managed_s1(tag):
            return any(tag.startswith(f"s1:{s}:") for s in MANAGED_SCREENERS)
        cur_managed={t["tag"] for t in cur_tags if is_managed_s1(t["tag"])}
        preserved=[t for t in cur_tags if not is_managed_s1(t["tag"])]
        tags_changed = (cur_managed != desired_managed)
        new_tags = preserved + [{"tag":t} for t in sorted(desired_managed)]

        if not coll_changed and not tags_changed:
            stats["already_correct"]+=1
            continue

        stats["items_changed"]+=1
        if coll_changed: stats["coll_changed"]+=1
        if tags_changed: stats["tags_changed"]+=1

        adds=sorted(target_bucket_keys-cur_colls)
        dels=sorted(remove_bucket_keys & cur_colls)
        proposed.append([
            key, union, "|".join(sorted(target_sources)),
            "ADD:"+(",".join(adds) if adds else "-"),
            "DEL:"+(",".join(dels) if dels else "-"),
            ",".join(sorted(desired_managed)),
            "",  # note column (empty for normal rows)
        ])

        if args.apply:
            payload={}
            if coll_changed: payload["collections"]=sorted(new_colls)
            if tags_changed: payload["tags"]=new_tags
            try:
                st=zpatch_item(key,version,payload)
                if st==204: stats["applied"]+=1
                else: stats["apply_unexpected"]+=1
            except urllib.error.HTTPError as e:
                stats["apply_errors"]+=1
                proposed[-1].append(f"ERR{e.code}")
            time.sleep(0.05)

    # write review CSV
    outp="proposed_pass1_restore.csv"
    with open(outp,"w",newline="") as f:
        w=csv.writer(f)
        w.writerow(["item_key","union","sources","add","del","s1_tags","note"])
        for row in proposed: w.writerow(row)
    print(f"\nWrote {outp} ({len(proposed)} rows)")

    print("\n=== SUMMARY ===")
    for k in ["items_changed","coll_changed","tags_changed","already_correct",
              "skipped_superseded","no_restore_source","fetch_failed",
              "applied","apply_errors","apply_unexpected"]:
        print(f"  {k:<22}{stats[k]}")
    if not args.apply:
        print("\nDRY RUN — nothing written. Review proposed_pass1_restore.csv, then")
        print("re-run with --apply (and ZOTERO_WRITE_KEY set) after a Zotero backup.")

if __name__=="__main__":
    main()
