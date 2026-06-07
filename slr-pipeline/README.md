# SLR Pipeline — Vibe Coding Governance Systematic Literature Review

Reproducibility tooling for the SLR: query import, two-pass screening,
cross-source dedup, cross-model validation, and Zotero state reconciliation.
Zotero group library `6505702`.

## Credentials (project-scoped, VCSLR-prefixed)

No keys are stored in source. Each script loads a project-scoped `.env` by
walking up from the current directory to the repo root (or `$ZOTERO_ENV_FILE`).
Variable names are prefixed `VCSLR_` so multiple projects' keys never collide;
scripts read the `VCSLR_*` name first and fall back to the generic name if unset.

| Purpose      | Variable (preferred)      | Fallback            |
|--------------|---------------------------|---------------------|
| Read-only    | `VCSLR_ZOTERO_READ_KEY`   | `ZOTERO_API_KEY`    |
| Write        | `VCSLR_ZOTERO_WRITE_KEY`  | `ZOTERO_WRITE_KEY`  |
| Library ID   | `VCSLR_ZOTERO_LIBRARY_ID` | (defaults to 6505702) |

Copy `.env.example` to `.env` at the repo root, fill in the read key, `chmod 600`.
The read key suffices for diagnostics, dry runs, and reads. Prefer passing the
write key inline only at apply time so it never rests on disk:

```bash
VCSLR_ZOTERO_WRITE_KEY=xxxx python3 restore_pass1_from_csv.py ... --apply
```

## Scripts

### Screening (Pass 1)
- **`ssrn_llm_screen.py`** — Claude Sonnet screening of SSRN corpus (30s rate
  limit). Emits per-item decision + rationale.
- **`non_ssrn_llm_screen.py`** — same for IEEE/ACM/Scopus/WoS/arXiv/coursework.
- **`apply_stage1_tags.py`** — applies Pass-1 `s1:*` tags / source tags from
  collection membership and screening output.

### Query import / extraction
- **`fetch_q_arxiv_06.py`, `fetch_q_arxiv_07.py`** — arXiv API import for
  specific queries into Zotero collections.
- **`extract_non_ssrn.py`** — extracts/normalizes non-SSRN records for screening.

### Apply & reconciliation
- **`apply_screening_decisions.py`** — applies screening decisions to Zotero
  (collection placement + `s1:*` tag reconciliation; removes stale screener
  tags; union rule human > machine).
- **`restore_pass1_from_csv.py`** — restores Pass-1 per-source screening state
  (collections + `s1:*` tags) from the original ground truth. SSRN read from
  `ssrn-decisions.xlsx` (preserves the human-sampled decisions the csv dropped).
  Records all four screeners (human/claude/chatgpt/gemini) as tags; only
  human>claude affect placement. Skips `04-Superseded`; never touches
  naimi-chapters. Dry-run default; `--apply` gated on `ZOTERO_WRITE_KEY`.

### Dedup / cleanup
- **`cleanup_superseded_tags.py`** — superseded-duplicate handling
  (journal > conference > preprint). NOTE: known date-tiebreaker bug — pad
  year-only dates "YYYY" to "YYYY-01" before comparing; fix before next run.
- **`cleanup_queue_membership.py`** — removes items from 00-Queue once screened
  (walks theme sub-collections, e.g. SCOPUS).

### Phase 2 (post Pass-1-Keep tightening)
- **`export_phase2_queue.py`** — exports the Phase-2 input queue.
- **`split_batches.py`** — splits the queue into fixed-size screening batches.
- **`phase2_queue_sanity.py`** — sanity checks on the Phase-2 queue.

### Cross-model validation
- **`build_validation_workbook.py`** — builds the validator workbook (chatgpt /
  gemini sheets) for cross-model comparison and kappa.

### Diagnostics (read-only)
- **`compare_s1_tags_vs_csv.py`**, **`compare_s1_tags_vs_csv_v2.py`** — compare
  the decision implied by `s1:*` tags against the ground-truth CSV/xlsx per
  source bucket. v2 handles the non-SSRN union + SSRN xlsx formats.

## Data files

`*.csv`, `*.xlsx`, `*.xls`, `*.ris` are gitignored — they contain item
content/abstracts and live outside the repo. Record their location separately.

## Standing rule

Export a Zotero backup (desktop: File -> Export Library -> Zotero RDF, include
Files) before any `--apply` or bulk write.
