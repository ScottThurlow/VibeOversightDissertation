# SLR Pipeline — Claude Code Context
*Vibe Coding Governance Dissertation — Scott Thurlow*
*Last updated: 2026-06-07*

---

## 0. Resuming Sessions

**This file auto-loads** when Claude Code starts from the `slr/` directory. No manual load needed.

**To resume a prior session:**
```
/resume          # lists recent sessions by timestamp — pick the most recent SLR session
```

**Chat history archive:** Every session appends a timestamped turn marker to
`methodology/chat-history/YYYY-MM-DD_auto.md` via the Stop hook in `.claude/settings.json`.
Check there for a running log of what was done each day.

**If starting fresh:** This file is the canonical state. Read it top-to-bottom before asking
what to do next — §13 (Immediate Next Steps) is always current.

---

## 1. Project Overview

Doctoral dissertation (Engineering Management, Purdue) investigating how organizations recognize
and manage risks from AI-generated / vibe-coded code, with focus on **scaling human oversight**
as code volume outpaces traditional governance (manual code review). Working practitioner at
Microsoft.

**Theoretical framing:** Cleanroom statistical QC (Cobb & Mills) + lean jidoka (Ohno) → route
code to human review only when risk warrants it, rather than exhaustive inspection.
Original theoretical contribution.

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

> **STANDING RULE: Before ANY major Zotero write — always ask Scott to export/backup via
> Zotero desktop first (File → Export Library, BibTeX or RDF + Files).**

```bash
# Primary SLR Zotero library — library 6505702
# Credentials loaded automatically from slr/.env
ZOTERO_API_KEY_READONLY=dJUvw2FFn2XEdgXbIaURcKcz
ZOTERO_API_KEY_READWRITE=1PWe3RlONpS38OtM5fFpPliz   # same key works for 6505702
ZOTERO_GROUP_ID=6505702
ZOTERO_LIBRARY_TYPE=group

# Semantic Scholar — key PENDING (applied for; rate limit 1 req/sec unauthenticated)
# Exa — key in slr/.env, MCP server registered (mcp__exa__web_search_exa works)

# Credentials dir (Faberix): ~/.config/claude-zotero/.env  (stale — use slr/.env)
```

**Zotero client:** `python3 zotero_client.py <subcommand>` from `slr/` — loads `.env` automatically.
.env path bug fixed 2026-06-07 (was `.parent.parent`, now `.parent`).

---

## 5. Zotero Library Structure — Library 6505702

### Phase 2 collection keys

| Path | Key | Items |
|------|-----|-------|
| Phase 2 / Phase 1-01-Keep / 00-Queue | `JFHGBVLY` | 0 (empty — apply complete) |
| Phase 2 / Phase 1-01-Keep / 01-Keep | `3D8XR6AP` | 923 |
| Phase 2 / Phase 1-01-Keep / 02-Maybe | `5VHKIH5W` | 11 |
| Phase 2 / Phase 1-01-Keep / 03-Discard | `9A2LGHUT` | 1025 |
| Phase 2 / Phase 1-02-Maybe / 00-Queue | `JUDYQCPU` | 0 (empty — apply complete) |
| Phase 2 / Phase 1-02-Maybe / 01-Keep | `ZB6R4G9H` | 59 |
| Phase 2 / Phase 1-02-Maybe / 02-Maybe | `LR6EXWQB` | 75 |
| Phase 2 / Phase 1-02-Maybe / 03-Discard | `TA8JUISM` | 1900 |

**Total Phase 2 keeps: 982** (923 + 59)

### Invariants
- Items **never** move out of `01-Imports` collections — import membership is permanent provenance.
- `04-Superseded` items are logical duplicates; **skip in all restore/apply operations**.
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
# Total-Results header → collection-specific count (not library total)
```

---

## 6. SLR Pipeline State

### Pass 1 — COMPLETE ✅
Fully restored from ground-truth CSVs:
- `nonssrn-decisions-2026-05-25.csv`
- `ssrn-decisions.xlsx` (**xlsx mandatory** — csv export drops human column)

`applied=2890`, `apply_errors=0`, `fetch_failed=79` (SSRN 404s, benign), `skipped_superseded=30`

**Union rule:** human decision wins over claude. All screeners recorded as `s1:*` tags.

### Phase 2 Collection Population — COMPLETE ✅
`apply_phase2.py` — all queues empty. 982 keeps in place.

Tag format: `s2:human:maybe`, `s2:human:keep`, etc.

### Phase 3 Full-Text Screening — PENDING ⏳

**Pipeline plan:**
1. Zotero desktop → Tools → Find Available PDF on collections `3D8XR6AP` + `ZB6R4G9H`
   (Purdue EZProxy configured; covers ACM, IEEE, Elsevier, Springer, Wiley)
2. AI full-text screening: Sonnet primary, escalate borderline to Opus
   - Same model hierarchy as Phase 1/2 (OpenAI/Gemini rejected — 2× over-permissive)
   - Abstract-only fallback for papers where PDF unavailable (conservative keep)
3. Write `s3:keep` / `s3:maybe` / `s3:discard` tags back to Zotero
4. Human trust-check sample (blinded, κ target)
5. **Target corpus: 100–200 papers** for single-reviewer data extraction
   (Claude Desktop estimated 400 as manageable; user considers this high)

**Phase 3 rubric:** NOT YET DRAFTED — draft before building screening script.

### Citation Chasing — PENDING (waiting on Phase 3 corpus) ⏳
- Chase from Phase 3 final corpus (~150–200 papers), not all 982
- Semantic Scholar MCP: `paper_citations` (forward) + `paper_references` (backward)
- De-dup against full corpus → screen new entrants through Pass 1 rubric
- **Semantic Scholar API key active** (added 2026-06-09; still 1 req/sec — sleep between calls)

---

## 7. Query Log

File: `slr/queries/Query Composition and Log.csv` — 52 queries total.

Queries organized into 7 thematic categories. All filtered to **2020+**.

| Category | Query IDs | Status |
|----------|-----------|--------|
| AI Code Risk & Security | Q-IEX-01–05 | ✅ Run |
| AI Code Quality & Debt | Q-IEX-06–07 | ✅ Run |
| Human Oversight & Capacity | Q-IEX-08–11, Q-ACM-02/04, Q-arXiv-02/05, Q-SCO-02/05, Q-ABI-02/05 | IEX ✅, others pending |
| Org Governance & Policy | Q-IEX-12–15, Q-ACM-01/03/05/06, Q-arXiv-01/03/04, Q-SCO-01/04, Q-ABI-01/04 | IEX ✅, others pending |
| Org Risk Recognition | Q-IEX-16, Q-SCO-03, Q-ABI-03 | IEX ✅, others pending |
| Tool-Specific | Q-IEX-17–22 | ✅ Run |
| Agentic SDLC Oversight | Q-IEX-25/26, Q-ACM-09/10, Q-SCO-08, Q-arXiv-07 | ⏳ Not run |

### Pending query runs (in priority order)
1. ACM-01 through ACM-10 (ACM Digital Library — not yet run)
2. arXiv-01 through arXiv-07
3. SCO-01 through SCO-08 (Scopus)
4. WoS-01 through WoS-03 (Web of Science — note: "Web pf Science" typo in CSV)
5. 7 AI House panel queries (Q-IEX-23/24, Q-ACM-07/08, Q-SCO-06/07, Q-arXiv-06):
   - Multi-agent adversarial oversight
   - Prompts-as-artifact, governance framing + reproducibility

### Agentic SDLC query rationale
"Agentic SDLC" is grey-lit / industry term (PwC, Thoughtworks, GitHub). Academic databases
use "LLM coding agents", "autonomous software engineering". Queries target the governance and
**scaling human oversight** angle specifically — not agent architecture. Risk-based code review
queries (Q-IEX-26, Q-ACM-10) capture the scaling mechanism literature.

---

## 8. Screening Rules & Classification

### Pass 1 (title/abstract)
- Recall-favoring; Pass 2 applies operationalizability filter
- 73% Pass-2 rejection rate is **by design**

### Pass 2 rubric (final)
**Keep if operationalizable:**
- **T1 (Core):** vibe coding; code review scalability; AI code risk+measurement; org governance;
  developer oversight; LLM-as-judge/adversarial agents as oversight trigger
- **T2 (Context):** human oversight; AI governance+DevSecOps; regulatory org implementation;
  legal liability org response; scalable oversight any pipeline stage
- Default-to-keep; maybe = thin abstract only

### Phase 3 rubric — NOT YET DRAFTED
Will be tighter than Phase 2 — full text available means stricter operationalizability.
Draft before building Phase 3 screening script.

### Screening classification rules
- Documents authored by Scott → always **Discard**
- Purdue Brightspace URLs → always **Discard**
- SSRN: any mention of human oversight, AI governance, code/software, EU AI Act, NIST AI RMF,
  org adoption, or scalable oversight → **automatic keep**

### Cross-model validation notes
- **Gemini Flash is unreliable** — ~98% hallucinated item keys; only re-prompted batches valid.
  **Use Gemini Advanced, not Flash.**
- **OpenAI and Gemini over-permissive** — kept ~2× what Claude + human kept. Use Claude only.
- Claude and human agreement: κ=0.79 (last blinded pass)
- Two verification samples per pass:
  1. **Trust check** — stratified 20/category, unblinded (≤5% disagree→apply; 5–15%→apply+document; ≥15%→stop)
  2. **Methodology validation** — random N=100, **BLINDED**, for Cohen's κ

### IRB positionality note
Pre-existing relationship with Aravind Bala (CTO, SeekOut) — anonymized in Zotero as
"senior practitioner / CTO at different org in HR-tech sector" pending permission.

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

1. **Draft Phase 3 full-text screening rubric** — needed before building screening script
2. **Zotero PDF batch fetch** — Tools → Find Available PDF on `3D8XR6AP` + `ZB6R4G9H`
   (run in Zotero desktop; Purdue EZProxy already configured)
3. **Run pending database queries** — ACM, arXiv, Scopus, WoS, AI House panel, Agentic SDLC cluster
4. **Build Phase 3 screening script** — after rubric drafted and PDFs available
5. **Citation chasing** — after Phase 3 final corpus identified; S2 key now active ✅
6. **Fix `cleanup_superseded_tags.py` date tiebreaker** before next dedup run

---

## 14. Methods Chapter Documentation Needed

- Post-meeting restructure: governance/policy elevated to **separate top-level RQ**;
  sub-RQs broadened and made less leading (per Thomas 2026-05-01 meeting)
- Document 2026-05-21 methodological decision: screening criteria unchanged for AI House
  queries; rationale = recall-risk mitigation via spot-check
- Document Pass 2 trust check results (κ=0.79) and human escalation review
- Positionality disclosure for Aravind Bala (see §8 above)
