# VibeOversightDissertation

**Bootstrap tooling for AI-assisted development governance.**

This repository is a research artifact developed as part of doctoral research at Purdue University on the challenge of scaling human oversight of AI-generated code — the "vibe coding" phenomenon in which AI dramatically increases code volume while traditional governance mechanisms like manual code review struggle to keep up.

The tooling here is simultaneously:
1. A practical governance protocol for any AI-assisted software project
2. A living experiment instantiating the theoretical constructs under study
3. A citable artifact for the dissertation and associated publications

---

## The Problem

AI coding tools (GitHub Copilot, Claude Code, Cursor, and others) have fundamentally changed the economics of code production. A developer can generate in minutes what previously took hours. The bottleneck has shifted from *writing* code to *reviewing and governing* it.

Empirical evidence is emerging that this shift introduces real risk:
- AI-generated code is ~1.7× more likely to contain issues than human-authored code (CodeRabbit, 2024)
- The 2024 DORA research found that every 25% increase in GenAI adoption correlates with 7% worse software delivery stability (Kim & Yegge, 2025)
- Pull requests are growing larger and more complex, overwhelming reviewers' capacity to provide meaningful oversight

The research question: **how do organizations recognize and manage this risk, and what mechanisms allow human oversight to scale without sacrificing quality?**

---

## The Protocol

`AGENTS.md` — installed into each target repository — instructs Claude Code to behave as a governance-aware engineering partner rather than a code dispenser. It instantiates six theoretical constructs:

| Construct | Mechanism |
|---|---|
| **Jidoka** (lean stop-and-signal) | Human Review Required flags halt the flow and surface defects before they propagate |
| **Statistical quality control** | Risk tiers create a sampling frame — CRITICAL items get 100% review, LOW items get spot-checked |
| **Signal detection theory** | Confidence declarations calibrate the human reviewer's prior before they read the code |
| **Automation bias mitigation** | Explicit uncertainty and hallucination-surface flags counteract trust in fluent AI output |
| **Prompts-as-artifact** | `prompts/` directory + git trailers create durable, queryable generation provenance |
| **Blast radius containment** | Pre-assessment before destructive operations mirrors lean's andon cord |

---

## Repository Contents

```
templates/
  AGENTS.md                    ← governance protocol (install in target repo root)
  capture_prompt.sh            ← scaffold a prompt artifact after MEDIUM+ generation
  prompt_audit.sh              ← query the git-based prompt audit trail
scripts/
  setup_oversight.sh           ← bootstrap script — applies protocol to any git repo
```

---

## Quick Start

```bash
# Clone this repo
git clone https://github.com/ScottThurlow/VibeOversightDissertation ~/code/VibeOversightDissertation
cd ~/code/VibeOversightDissertation

# Bootstrap any target repo (dry run first)
./scripts/setup_oversight.sh /path/to/your/repo --dry-run
./scripts/setup_oversight.sh /path/to/your/repo

# Bootstrap with GitHub branch protection (requires GH_TOKEN or gh CLI)
export GH_TOKEN=<your-token>
./scripts/setup_oversight.sh /path/to/your/repo
```

### What gets installed in the target repo

| File | Purpose |
|---|---|
| `AGENTS.md` | Stable governance protocol — Claude Code reads this at session start |
| `.github/CODEOWNERS` | Owner approval required on all files before merge |
| `.github/pull_request_template.md` | PR checklist tied to the oversight protocol |
| `scripts/capture_prompt.sh` | Scaffold prompt artifacts after MEDIUM+ generation |
| `scripts/prompt_audit.sh` | Query AI provenance via git log |
| `prompts/README.md` | Prompt artifacts directory |

GitHub branch protection on `main` is applied via API: 1 CODEOWNER review required, stale review dismissal, last-push approval, force pushes blocked.

---

## The Governance Workflow

### During a Claude Code session

Claude Code reads `AGENTS.md` at session start and activates the protocol automatically. For every non-trivial code generation it:

1. Classifies risk: `LOW | MEDIUM | HIGH | CRITICAL`
2. Flags specific lines for human review (MEDIUM and above)
3. Declares confidence with honest uncertainty
4. Warns on hallucination surfaces (version-sensitive APIs, platform features)
5. Assesses blast radius before destructive operations

### Capturing prompt artifacts

After any MEDIUM+ generation:

```bash
./scripts/capture_prompt.sh src/auth/middleware.ts "JWT validation with refresh rotation"
# → creates prompts/auth/middleware.md with metadata template
# → prints git commit trailer block to copy
```

### Querying the audit trail

```bash
./scripts/prompt_audit.sh --stats     # overview: commits, risk distribution, review status
./scripts/prompt_audit.sh --pending   # artifacts awaiting human review
./scripts/prompt_audit.sh --risk HIGH # all HIGH risk commits
```

### Git commit convention

Every AI-assisted commit carries trailers:

```
Implement auth middleware

Prompt-Artifact: prompts/auth/middleware.md
AI-Model: claude-sonnet-4-6
AI-Risk: HIGH
```

This makes AI provenance queryable across the entire project history:
```bash
git log --grep="Prompt-Artifact:" --oneline
```

---

## Research Context

This tooling is developed as part of a doctoral dissertation in Engineering Management at Purdue University. The dissertation examines how organizations recognize and manage risk from AI-generated code, with particular focus on the challenge of scaling human oversight when AI dramatically increases code volume.

**Theoretical framing:** The protocol draws on Cobb & Mills (1990) cleanroom statistical quality control, Ohno (1988) lean manufacturing jidoka, Parasuraman's levels of automation, and the EU AI Act Article 14 meaningful human control requirements.

**Empirical phase:** Following the systematic literature review, a mixed-methods study (survey + practitioner interviews) will examine how large tech organizations, startups, and regulated enterprises differ in their AI code governance practices. The prompts-as-artifact and risk-tiered review mechanisms in this repo are among the constructs to be investigated.

**Publications:** A conference paper based on the systematic literature review is targeting ICSE SEIP, EASE, or HICSS. Updates will be linked here.

---

## Updating the Protocol

When `AGENTS.md` is revised:

1. Update `templates/AGENTS.md` in this repo and commit
2. Re-run `setup_oversight.sh --update-agents` in each target repo — touches only `AGENTS.md`, nothing else

---

## License and Attribution

Copyright © 2026 Scott Thurlow

This work is licensed under [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/).

You are free to share and adapt this material for non-commercial purposes with appropriate attribution. See `LICENSE.md` for full terms.

**Attribution format for academic use:**
> Thurlow, S. (2026). *VibeOversightDissertation: Bootstrap tooling for AI-assisted development governance* [Software]. GitHub. https://github.com/ScottThurlow/VibeOversightDissertation

---

*Developed as part of doctoral research at Purdue University. The research does not represent the views of any employer past or present.*
