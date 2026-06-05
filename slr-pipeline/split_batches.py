#!/usr/bin/env python3
"""
Split a CSV file into batches preserving the header in each batch.

Output files are named: batch_001.csv, batch_002.csv, etc.

Usage:
    # Simple (outputs alongside input file, 50 rows/batch):
    python3 split_batches.py input.csv

    # With options:
    python3 split_batches.py input.csv --output-dir ~/slr/pass2/batches/sonnet --batch-size 50
    python3 split_batches.py input.csv --output-dir ~/slr/pass2/batches/opus   --batch-size 20
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
import os
import sys

DEFAULT_BATCH_SIZE = 50

def split_csv(input_path, output_dir=None, batch_size=DEFAULT_BATCH_SIZE):
    if not os.path.exists(input_path):
        print(f"ERROR: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    else:
        output_dir = os.path.dirname(os.path.abspath(input_path))

    with open(input_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    total = len(rows)
    num_batches = (total + batch_size - 1) // batch_size

    print(f"Input:      {input_path}")
    print(f"Output dir: {output_dir}")
    print(f"Rows:       {total}")
    print(f"Batches:    {num_batches} (size {batch_size})")
    print()

    for i in range(num_batches):
        batch_rows = rows[i * batch_size:(i + 1) * batch_size]
        out_path = os.path.join(output_dir, f"batch_{i+1:03d}.csv")
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(batch_rows)
        print(f"  {out_path}  ({len(batch_rows)} rows)")

    print(f"\nDone. {num_batches} files written.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="Input CSV file")
    parser.add_argument("--output-dir", default=None,
                        help="Directory for output batch files (default: same dir as input)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Rows per batch (default: {DEFAULT_BATCH_SIZE})")
    args = parser.parse_args()
    split_csv(args.input, args.output_dir, args.batch_size)
