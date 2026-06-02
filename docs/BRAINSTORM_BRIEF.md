# Oversight System — Brainstorming Brief

*A self-contained briefing for ideation. Hand this to a fresh model (e.g. the Claude app) that has no access to the repo. It summarizes what the system is, what's built vs. designed, the decisions behind it, and the open questions worth brainstorming.*

**Date:** 2026-06-02 · **Status legend:** ✅ implemented · 🔧 designed, not yet built

---

## 1. The problem & the thesis

"Vibe coding" — building software by prompting AI — generates code far faster than humans can carefully review it, and AI-generated code **fails differently** from human code: plausible-but-wrong logic, hallucinated APIs, security antipatterns that *look* correct, and PRs large enough to overwhelm a reviewer's context. Reviewing everything exhaustively doesn't scale; trusting blindly is reckless.

**The thesis: route human attention by risk.** Make the oversight signal *visible and stratified* so a human reviews the ~10% that matters line-by-line and spot-checks the rest. The mechanism is a system of **checks and balances across multiple independent AIs**, escalating to a human as risk rises.

This work is simultaneously (a) a real tool that bootstraps the methodology into any project, (b) a living experiment governed by its own rules, and (c) the empirical substrate for a doctoral research program (a systematic literature review + practitioner study) on scaling human oversight of AI-assisted development.

---

## 2. Two layers of oversight

**Layer 1 — Self-flagging (single agent). ✅** The authoring AI flags its *own* work. Every non-trivial change ships with: a **risk classification**, **human-review flags** (which lines need eyes and *why*), a **confidence declaration**, **hallucination-surface warnings** (flag version-sensitive/undocumented APIs), and a **blast-radius note** for destructive ops. The framing: "a senior engineer who flags their own work," not a code dispenser.

**Layer 2 — Independent review (multiple agents). 🔧 built, barely exercised.** Self-flagging has a blind spot — an AI is bad at catching its *own* class of mistakes. So a second layer brings **independent reviewers from different vendors** to scrutinize the author's work, scaled by risk, culminating in a human gate. This is the multi-agent **panel** (§5).

The two compose: author self-flags → independent reviewers scrutinize → human decides.

---

## 3. The AIs and why cross-vendor

The point is **decorrelated judgement** — an AI reviewing its own family tends to ratify its own mistakes.

| AI | Subscription | Driven via | Role |
|---|---|---|---|
| **Claude** (Opus/Sonnet/Haiku) | Claude Max (20×) | `claude` CLI | **Author** (Opus), **triage** (Haiku), **arbiter** (Sonnet) |
| **OpenAI** | ChatGPT Pro | `codex` CLI | Independent reviewer / adversary (security, red-team) |
| **Google** | Gemini Pro | `agy` (Antigravity CLI) | Independent reviewer (correctness, whole-repo/architecture lens) |
| **GitHub Copilot** | Copilot Pro | GitHub-native PR review | **Always-on baseline** on *every* PR, in CI |

**Constraints that shape the whole design:**
- These are **app/subscription logins, not API keys.** To use the quota already paid for, each reviewer runs through its subscription-authenticated CLI via interactive browser OAuth — which **CI runners can't hold**. → The cross-vendor panel runs **locally** and posts findings to the PR; CI handles deterministic gates + Copilot's native review.
- **Opus is the author, so no Claude model casts an independent review** (same-vendor judgement correlates errors). Sonnet is the *arbiter* (synthesis), never an independent vote. The independent votes are cross-vendor (`agy`/`codex`).
- **Quota-aware allocation:** spend abundant Claude Max quota on high-frequency roles (author/triage/arbiter); reserve scarce ChatGPT Pro reasoning for high-risk + adversarial passes; use Antigravity's large context for breadth.

---

## 4. Agent roles (separation of powers)

Roles are defined first; models are assigned to roles.

| Role | What it does | Model |
|---|---|---|
| **Author** | Generates code; self-flags (Layer 1). | Opus |
| **Triage** | Scores risk. Deterministic rules set a floor; the author can *raise* but not *lower* it. | rules + Haiku |
| **Reviewer(s)** | Independent critique, each with a *lens*: correctness, security, maintainability, spec-conformance. Count scales with risk. | `agy`, `codex`, Copilot |
| **Adversary / red-team** | Actively tries to *break* the change. | `codex` (or `agy`) |
| **IP / provenance** | Checks intellectual-property exposure (NEW — §7). | `ipcheck` (local) |
| **Arbiter** | Reconciles conflicting reviews into one verdict; dedups; loops back or escalates. (Synthesis, *not* an independent check.) | Sonnet |
| **Human** | Sets policy; final gate at HIGH/CRITICAL; spot-checks the rest. | You |

---

## 5. The risk model & the panel

Risk is the dial controlling scrutiny:

| Level | Criteria | Scrutiny (escalating) |
|---|---|---|
| **LOW** | Pure UI/styling, no logic/data/external calls | Self-flag; deterministic gates; **Copilot baseline (auto, all PRs)**; **random red-team audit (SQC sample)**. Panel otherwise skipped. |
| **MEDIUM** | Business logic, data transforms, state, routing | + prompt artifact; **panel runs**: ≥1 cross-vendor reviewer (`agy`, correctness) + IP agent; human reviews flagged items. |
| **HIGH** | Auth, input handling, persistence, external APIs | + security lens (`codex`) + **always-on adversary pass** (`codex`); human reviews line-by-line. |
| **CRITICAL** | XSS/CSRF/injection, PII, payments, destructive ops | same roster + **blast-radius required** + **mandatory human approval**. |

**Who assigns risk:** a deterministic floor (file-path globs like `auth/**`, `**/migrations/**`; dependency-manifest changes; diff size) that the author can raise freely but lower only with a second agent's or the human's concurrence. Haiku confirms or raises it; never below the floor.

**Random red-team audit (Statistical Quality Control).** The adversary pass is always-on at HIGH+; below that, a *salted-deterministic random sample* of LOW/MEDIUM PRs also gets one. This audits the auto-pass lane (catching mis-triaged changes) and yields an **escaped-defect rate** — the empirical signal for whether the tier thresholds are calibrated. Selection = `SHA256(head_sha + secret_salt) mod 100 < tier_rate`: reproducible (an auditor with the salt can prove a PR was/wasn't sampled) and non-gameable (the salt is secret).

**The panel** ([`run_panel.sh`], local): `TRIAGE` (Haiku) → `REVIEWERS` (cross-vendor fan-out, each with a lens, diff chunked if large) → `ARBITER` (Sonnet dedups → one verdict) → `POST` (one **line-level thread per finding** + one summary comment). Threads are the mechanism: under branch protection, **each thread must be resolved before merge** — that's how human attention gets routed.

---

## 6. The pipeline (prompt → merge)

Cheap/deterministic checks first (fail fast); expensive AI/human review only where risk warrants.

```
1. PROMPT           Author prompted. The prompt is a first-class artifact (§8).        ✅
2. AUTHOR+SELF-FLAG Opus generates, classifies risk, flags review, states confidence.  ✅ Layer 1
3. CAPTURE          MEDIUM+: capture_prompt.sh records the prompt in prompts/.          ✅
4. COMMIT           Provenance trailers: Prompt-Artifact / AI-Model / AI-Risk.          ✅
5. PR               main protected: ≥1 approval + all threads resolved before merge.    ✅
6. CHEAP GATES      (CI) lint, types, build, tests, secret scan, dep audit.             🔧 per-project
7. TRIAGE           Final risk level.                                                   🔧 run_panel.sh
8. EXPENSIVE GATES  Gated by risk: e2e, coverage, mutation testing.                     🔧
9. AI PANEL         Cross-vendor reviewers (local), each a lens; adversary at HIGH+.    🔧 run_panel.sh
10. ARBITER         Synthesizes → verdict; requests changes or escalates.               🔧 run_panel.sh
11. HUMAN GATE      Mandatory at HIGH/CRITICAL; thread-resolution forces each finding.   ✅ gate / 🔧 panel
12. MERGE→ARCHIVE   Raw review logs archived; summaries regenerable.                     🔧
```

---

## 7. Prompts as source code

A defining principle: **prompts are treated like source.** The prompt is the "C source"; the generated code is the "compiled artifact." You should be able to *regenerate* the code from the prompt. Unlike a normal build, **both** the prompt and the generated code are committed and versioned. `prompts/` mirrors `src/`, one artifact per MEDIUM+ file. AI provenance becomes queryable: `git log --grep="Prompt-Artifact:"`. (A finer-grained append-only raw turn log + regenerable summaries + a watermark is 🔧 designed, not built.)

This doubles as an **IP defense** (see below): code regenerable from a spec that never said "copy library X" is documentary clean-room provenance.

---

## 8. IP / provenance — the newest piece (just added)

Vibe coding introduces an **intellectual-property risk** the panel didn't cover: an LLM can emit code that is a near-verbatim lift of copyrighted training data, drag **copyleft (GPL/AGPL) or unknown-license** code into a proprietary tree, or strip the attribution permissive licenses require.

The key insight: **IP exposure is invisible to every other lens.** Correctness/security/maintainability all read code for *defects* — IP-tainted code can be perfectly correct and secure. Worse, the cleaner and more idiomatic the output, the *more* likely it was regurgitated rather than synthesized. So IP is a **risk axis orthogonal to the LOW→CRITICAL severity tier**, not a sub-case of it (a LOW pure-styling change can still be a verbatim copy).

**What we built (v0):** an `ipcheck` agent — a **local built-in** function (not a vendor CLI), wired into the panel as a peer reviewer (lens `ip`) on every run, emitting the same findings schema so it flows through the existing arbiter→thread machinery. It ships as a **deliberate placeholder** ("start stupid — says it's ok"): it performs no analysis yet and returns a clean verdict, but the panel summary **explicitly states that a clean result is NOT an IP clearance** (so a no-op can't masquerade as a green light).

**Growth path** (each step keeps the same interface, so only the function changes):
1. Deterministic license gate — flag changed dependency manifests + vendored files whose license is copyleft/unknown (scancode / license-checker).
2. Attribution check — permissive-licensed code copied without its notice.
3. Regurgitation lens — similarity/LLM pass flagging snippets that look lifted.

**Stance:** the pipeline *surfaces* IP exposure and routes it to a human (and specifically counsel) — it does **not adjudicate**. It is not legal advice.

---

## 9. Key decisions made (the "why")

- **D3** Two layers (self-flag + independent panel).
- **D4/D5** Cross-vendor for decorrelation; subscriptions-not-APIs → panel runs **locally**, posts to the PR.
- **D8** Prompts as source code (committed, versioned, queryable provenance).
- **D12** Merge requires all PR threads resolved → the thread *is* the feedback mechanism.
- **D13** Worked example: the repo's own policy blocked a `curl | bash` installer and **escalated to the human**, who made an explicit trust decision. The methodology working as intended.
- **D15** Panel design: whole-diff (cap→chunk); thread-per-finding + summary; manual trigger first; best-effort JSON I/O.
- **D16** Copilot is the always-on baseline floor on *every* PR (incl. LOW).
- **D17** Random red-team audit (SQC) of lower-tier PRs → escaped-defect-rate metric.
- **D18** Red-team is always-on at HIGH+ (not CRITICAL-only) → clean monotonic scrutiny ladder.
- **D19** IP/provenance as a first-class orthogonal agent (`ipcheck`), shipped as a transparent placeholder.

---

## 10. Honest state of things

- The panel has been run on a live PR **once** (PR #3). It gated the PR — *and* the red-team found a **real prompt-injection hole in the panel itself**: the panel feeds untrusted PR-diff text into reviewer LLMs, so a malicious diff could inject instructions. **This is unfixed.**
- The arbiter produced some **false positives**, and **line-anchoring** (mapping a finding to an exact diff line for the thread) is fuzzy — both need tuning.
- Steps 6, 8, 12 (cheap gates, expensive gates, archive) are largely 🔧.
- The IP agent is a no-op stub.

---

## 11. Open threads worth brainstorming

**A. The feedback loop — closed-loop fix→reverify.** Today the loop is *human-gated*: findings post as threads, threads block merge, a human drives the fix and re-runs the panel. The docs aspire to "arbiter loops back to author," but **no automated author-fix-reverify cycle exists.** If we build one, four invariants seem non-negotiable:
1. The **author fixes but never re-certifies** — re-review must stay independent/cross-vendor.
2. **Bounded** — cap rounds; non-convergence → human escalation (an andon cord / stop-the-line construct).
3. **Tier-gated** — auto-resolve low-tier only; tier1/HIGH+ always reaches a human.
4. **Fixes keep provenance and stay visible** — commits, not silently-closed threads (else automation bias).
   *Brainstorm:* Is a closed loop worth it, or does human-gated resolution capture most of the value? How do you bound oscillation? What's the right convergence metric?

**B. Making the IP agent real.** Which growth step first — the deterministic license gate (tractable, low-noise) or the regurgitation lens (hard, noisy, but the headline risk)? How do you set a similarity threshold that surfaces suspicion without drowning in false positives? Can the prompt-as-source artifact be operationalized as an actual IP defense?

**C. The panel's own attack surface.** It ingests untrusted PR content into reviewer LLMs (prompt injection, found live on PR #3). How do you harden a review panel against adversarial diffs without lobotomizing it?

**D. Calibration & metrics.** The escaped-defect rate is the headline metric. What else proves the thesis ("risk-stratified flagging scales oversight")? How do you measure reviewer *decorrelation* empirically? How do you detect when an AI reviewer is rubber-stamping?

**E. Trigger & ergonomics.** The panel is a manual local command (subscriptions can't run in CI). What's the least-friction trigger (git hook? `gh` alias? post-push)? How do you keep local AI spend predictable?

**F. The research framing.** Which constructs map cleanly — Jidoka (stop-and-signal), statistical quality control (the sampling frame), signal detection theory (confidence as prior-calibration), automation-bias mitigation? Where does the analogy strain?

---

## 12. Pointers (in-repo, for the human)

`AGENTS.md` (the authoritative single-agent protocol) · `METHODOLOGY.md` (end-to-end explainer) · `DECISIONS.md` (full decision log D1–D19) · `scripts/run_panel.sh` (the panel) · `scripts/setup_clis.sh` + `setup_oversight.sh` (machine + repo bootstraps) · `scripts/capture_prompt.sh` + `prompt_audit.sh` (provenance tooling).
