# SLR Pipeline — Claude Code Context Brief
*Vibe Coding Governance Dissertation — Scott Thurlow*
*Last updated: 2026-06-07*

---

## 1. Project Overview

Doctoral dissertation (Engineering Management, Purdue) investigating how organizations recognize and manage risks from AI-generated / vibe-coded code, with focus on **scaling human oversight** as code volume outpaces traditional governance (manual code review). Working practitioner at Microsoft.

**Theoretical framing:** Cleanroom statistical QC (Cobb & Mills) + lean jidoka (Ohno) → route code to human review only when risk warrants it, rather than exhaustive inspection. Original theoretical contribution.

**Target deliverables:**
- Standalone SLR paper (publication requirement; target: ICSE SEIP, EASE, HICSS)
- Dissertation with mixed-methods empirical phase (practitioner survey + semi-structured interviews)
- Prototype multi-agent AI code-review pipeline (oversight system demo)

---

## 2. Dissertation Committee

| Member | Institution | Role/Expertise |
|--------|-------------|----------------|
| Paul J. Thomas (chair) | Purdue | IT systems, project mgmt, cybersecurity education |
| Linda Naimi | Purdue | Tech law, IP, ethics, GenAI legal/ethical implications; editing *The Alignment Imperative* (Palgrave) |
| Hancheng Cao | Emory Goizueta | Computational social science, AI in software dev teams |
| Kyubyung Kang | Purdue | ML and AI governance in safety-critical domains |
| David Pistrui | Purdue | Organizational transformation, Industry 4.0 |

> **Note:** Markus Langer is a corpus author, NOT a committee member.

---

## 3. Machines & Environment

| Machine | Role |
|---------|------|
| BabyBlackDragon | Mac VM — primary dev |
| Faberix | Ubuntu workstation — long-running jobs |

- Long-running scripts: `nohup` on Faberix with timestamped logs and `.pid` files; monitor with `tail -f`
- Editor preference: `vi` (not nano)
- Scripts saved to permanent locations (not `/tmp`)

---

## 4. Credentials & Keys

> **STANDING RULE: Before ANY major Zotero write — always ask Scott to export/backup via Zotero desktop first (File → Export Library, BibTeX or RDF + Files).**

```bash
# Zotero
ZOTERO_API_KEY=8WlPHb1s8qw4PxDt7BsBlwDG        # READ ONLY
ZOTERO_WRITE_KEY=<retrieve from ~/.bashrc on Faberix>  # WRITE — use only when authorized; swap back after
ZOTERO_LIBRARY_ID=6505702
ZOTERO_LIBRARY_TYPE=group

# Credentials dir (Faberix)
~/.config/claude-zotero/.env

# Semantic Scholar, Exa, etc. — retrieve from ~/.bashrc or .env on Faberix
```

---

## 5. Zotero Library Structure

### Collection keys — Phase 2

| Parent | Sub-collection | Key |
|--------|---------------|-----|
| Phase 2 / Phase 1-01-Keep (`XBHC4AKC`) | 00-Queue | `JFHGBVLY` |
| | 01-Keep | `3D8XR6AP` |
| | 02-Maybe | `5VHKIH5W` |
| | 03-Discard | `9A2LGHUT` |
| Phase 2 / Phase 1-02-Maybe (`SKM5JKL5`) | 00-Queue | `JUDYQCPU` |
| | 01-Keep | `ZB6R4G9H` |
| | 02-Maybe | `LR6EXWQB` |
| | 03-Discard | `TA8JUISM` |

### Invariants
- Items **never** move out of `01-Imports` collections — import membership is permanent provenance.
- `04-Superseded` items are logical duplicates Zotero couldn't auto-merge; **skip in all restore/apply operations**. Surviving sibling carries the decision.
- Post-write integrity check: `Queue ∩ Keep == 0` and `Queue ∩ Discard == 0`
- `parentCollection: false` (not `None`) for top-level collection checks in Python

### Zotero API patterns
```python
# PATCH: fetch version first, pass as header
headers["If-Unmodified-Since-Version"] = item_version
request.method = "PATCH"

# Batch fetch
GET /items?itemKey=A,B,C&limit=100&include=data

# Child notes
POST /items  body=[{"itemType":"note","parentItem":key,"note":"<html>","tags":[...]}]

# Rate limits
# 429 → honor Retry-After header
# 503 under load → retry with 2-3s backoff
# Total-Results header → lowercase "total-results" in Python urllib

# Collection names: /collections?limit=100 (keys only from /items/{key}/collections)
```

---

## 6. SLR Pipeline State

### Pass 1 — COMPLETE ✅
Fully restored from ground-truth CSVs:
- `nonssrn-decisions-2026-05-25.csv` (cols: item_key, source pipe-delimited, claude_decision col 7, human_decision col 8)
- `ssrn-decisions.xlsx` (decisions sheet: claude col 1, human col 10 — **xlsx mandatory**, csv export drops human column)

Restore script: `restore_pass1_from_csv.py`
Apply result: `applied=2890`, `apply_errors=0`, `fetch_failed=79` (SSRN merge-orphan 404s, benign), `skipped_superseded=30`

**Union rule:** human decision wins over claude for collection placement. All four screeners recorded as `s1:*` tags.

### Phase 2 Collection Population — IN PROGRESS ⏳
Script: `apply_phase2.py`
Routes `queue_export.csv` (3,993 items) into 8 Phase 2 collections by `source_queue × union_decision`.
- Hard guards: no modification of Pass 1 SCREENING_PARENTS keys
- Delta-containment: only PHASE2_ALL keys touched
- Pacing: 0.25s inter-item + 429 Retry-After backoff
- **Pending: dry-run summary review → --apply run**

### Key SLR files on Faberix
```
~/slr/                          # SLR working directory
~/slr/ssrn/                     # SSRN outputs
nonssrn-decisions-2026-05-25.csv
ssrn-decisions.xlsx             # XLSX mandatory
queue_export.csv                # 3,993 items, source_queue column
human_decisions.csv             # 39 human escalation decisions
apply_all.csv                   # Combined apply input
```

### GitHub Repo
`~/code/VibeOversightDissertation`
Branch: `slr-tools`; pipeline scripts in `slr-pipeline/`
License: CC BY-NC 4.0 © 2026 Scott Thurlow

---

## 7. Query Log Summary

Queries organized into 6 thematic categories. All filtered to **2020+**.

| Category | Query IDs |
|----------|-----------|
| AI Code Risk & Security | Q1–5 |
| AI Code Quality & Debt | Q6–7 |
| Human Oversight & Capacity | Q8–11 (+ 7 new pending below) |
| Org Governance & Policy | Q12–15 |
| Org Risk Recognition | Q16 |
| Tool-Specific | Q17–22 |

### 7 Pending AI House panel queries (run after Phase 2 apply)
| ID | Topic |
|----|-------|
| Q-IEX-23 | Multi-agent adversarial oversight |
| Q-ACM-07 | Multi-agent adversarial oversight |
| Q-SCO-06 | Multi-agent adversarial oversight |
| Q-arXiv-06 | Multi-agent adversarial oversight |
| Q-SCO-07 | Prompts-as-artifact, governance framing |
| Q-IEX-24 | Prompts-as-artifact, technical reproducibility |
| Q-ACM-08 | Prompts-as-artifact, technical reproducibility |

> Screening prompts **UNCHANGED** — these are vocabulary additions, not criteria changes.
> After Pass 1: spot-check Discard pile from Q-SCO-07/Q-IEX-24/Q-ACM-08 for prompt-versioning items.

### Agentic SDLC back-fill cluster (run after AI House queries)
"Agentic SDLC" / "ADLC" — emerging grey-lit term (CodeRabbit, Sonar, Cisco Outshift, Thoughtworks, PwC, asdlc.io). Phrase-lock spelled-out forms; ADLC alone is noisy. Maps to Human Oversight + Org Governance RQs.

### Deferred / contingent
- Google Scholar searches and terminology probe queries (Q-SSRN-10, Q-WoS-04, Q-GS-17) — contingent on SSRN coverage adequacy

---

## 8. Screening Rules & Classification

### Pass 1 (title/abstract)
- Recall-favoring; Pass 2 applies operationalizability filter
- 73% Pass-2 rejection rate is **by design**

### Pass 2 rubric (final)
**Keep if operationalizable:**
- **T1 (Core):** vibe coding; code review scalability; AI code risk+measurement; org governance; developer oversight; LLM-as-judge/adversarial agents as oversight trigger
- **T2 (Context):** human oversight; AI governance+DevSecOps; regulatory org implementation; legal liability org response; scalable oversight any pipeline stage
- Default-to-keep; maybe = thin abstract only

### Screening classification rules
- Documents authored by Scott → always **Discard** (unless explicitly noted otherwise)
- Purdue Brightspace URLs → always **Discard**
- SSRN: any mention of human oversight, AI governance, code/software, EU AI Act, NIST AI RMF, org adoption, or scalable oversight → **automatic keep**

### Cross-model validation notes
- **Gemini Flash is unreliable** — ~98% hallucinated item keys in non-SSRN runs; only re-prompted batches returned valid keys. **Use Gemini Advanced, not Flash.**
- Two verification samples per pass:
  1. **Trust check** — stratified 20/category, unblinded, gating pre-apply (≤5% disagree→apply; 5–15%→apply+document; ≥15%→stop)
  2. **Methodology validation** — random N=100, **BLINDED**, for Cohen's κ (κ=0.79 on last pass)

### IRB positionality note
Pre-existing relationship with Aravind Bala (CTO, SeekOut) — anonymized in Zotero as "senior practitioner / CTO at different org in HR-tech sector" pending permission. Relevant for IRB protocol when interview phase begins.

---

## 9. Claude Code Skills (installed at `~/.claude/skills/`)

| Skill | Notes |
|-------|-------|
| `zotero` | stdlib-only |
| `zotero-slr-dedup` | stdlib-only |
| `arxiv-zotero-import` | stdlib-only |
| `zotero-bulk-tagging` | requires openpyxl |
| `claude-skill-installer` | |
| `slr-project-init` | |
| `slr-pipeline-patterns` | defensive coding patterns |

Share path on Faberix: `~/jukebox/scott/slr/claude-skills/`
Reinstall: `python3 ~/.claude/skills/claude-skill-installer/scripts/install.py . --force`

---

## 10. Pipeline Defensive Coding Patterns (`slr-pipeline-patterns` skill)

1. **None-guard:** `(x or "")` not `.get(k,"")`
2. **Batch globs anchored:** `batch_[0-9][0-9][0-9].csv` not `batch_*.csv`
3. **One checkpoint key per batch**
4. **Header-anchored CSV extraction** with fence-line guard
5. **`csv.DictReader` length** not `wc -l` for row counts
6. **Sleep between batches** + check exit codes before checkpoint set
7. **Item-key hallucination validation** after every model response
8. **`_out` cleanup verification** before phase rerun

---

## 11. Known Bugs / Deferred Fixes

| Item | Details |
|------|---------|
| `cleanup_superseded_tags.py` date tiebreaker | Compares strings; year-only dates ("2026") incorrectly lose to year-month ("2026-02"). Fix: pad year-only to "YYYY-01" before comparing. Fix before next dedup run. |
| `slr-pipeline-observability` | Planned skill: real-time progress summary, prominent failure surfacing, None-value validation before Counter ops |

---

## 12. Oversight System Prototype

Multi-agent AI code-review pipeline (dissertation sample substrate).

| Vendor | Role |
|--------|------|
| Claude | Author / triage / arbiter |
| Codex | Adversary / security |
| Gemini / agy | Correctness / architecture / performance |
| Copilot | CI baseline |

**Core principle:** Same vendor never reviews its own code (decorrelation).
Runs locally via subscription CLIs (not API keys). Posts findings to PRs.
See repo: `AGENTS.md`, `FLOW.md`, `BRAINSTORM_BRIEF.md`

---

## 13. Immediate Next Steps (in order)

1. Review `apply_phase2.py` dry-run summary → run `--apply`
2. Run 7 AI House panel queries (Q-IEX-23 through Q-ACM-08)
3. Run Gemini + GPT-4o screening passes on new query results
4. Run Agentic SDLC back-fill query cluster
5. Spot-check Discard pile from Q-SCO-07/Q-IEX-24/Q-ACM-08 for prompt-versioning items
6. Fix `cleanup_superseded_tags.py` date tiebreaker before next dedup run

---

## 14. Methods Chapter Documentation Needed

- Post-meeting restructure: governance/policy elevated to **separate top-level RQ**; sub-RQs broadened and made less leading (per Thomas 2026-05-01 meeting)
- Document 2026-05-21 methodological decision: screening criteria unchanged for AI House queries; rationale = recall-risk mitigation via spot-check
- Document Pass 2 trust check results (κ=0.79) and human escalation review
- Positionality disclosure for Aravind Bala (see §8 above)
