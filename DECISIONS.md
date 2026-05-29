# Decision Log — the History of the System

A running, dated record of the design decisions behind this oversight system and *why* they were made. This is the committed, versioned counterpart to the session memory — "the history of the system." It complements [`METHODOLOGY.md`](METHODOLOGY.md) (what the system *is*) by recording *how and why we got here*.

> Convention: newest sections at the bottom. Each decision notes the rationale, and a status where relevant: **✅ implemented**, 🔧 **designed/planned**.

---

## 2026-05-28 — Foundations

### D1. Purpose: scale human oversight of vibe coding
The system exists to make AI-code oversight **scale**: route human attention by risk rather than reviewing everything or trusting blindly. Mechanism: checks and balances across multiple, independent AIs, escalating to a human as risk rises.

### D2. VibeOversightDissertation is the master; apps are learning vehicles
This repo is the **system** and its single source of truth. Real apps (`tutelare`, `bt-parkshare`) are both deliverables *and* sandboxes that exercise the methodology; lessons learned here inform the system. Tooling is proven in an app context, then promoted into this repo. The apps own their own history; **this repo owns the history of the system.**

### D3. Two layers of oversight
- **Layer 1 — self-flagging (single agent)** ✅: the author AI flags its own work per [`AGENTS.md`](AGENTS.md) (risk tier, human-review flags, confidence, hallucination warnings, blast radius).
- **Layer 2 — independent review (multiple agents)** 🔧: cross-vendor reviewers check the author's work, scaled by risk, ending in a human gate. Rationale: an AI is poor at catching its *own* class of mistakes — independence decorrelates errors.

### D4. The AIs and why cross-vendor
- Claude (Max 20×): Opus = author; Haiku = triage/cheap review; Sonnet = arbiter.
- OpenAI (ChatGPT Pro) via `codex`: independent reviewer / adversary at high risk.
- Google (Gemini Pro) via `agy` (Antigravity): independent cross-vendor reviewer + breadth lens.
- GitHub Copilot (free): supplemental native PR review at medium risk and up.

Rule: **Opus authors, so Opus never reviews its own output.** At the highest risk the *independent* votes must be cross-vendor; same-vendor Claude tiers assist but don't count as the independent check.

### D5. Subscriptions, not API → the panel runs locally
Max / ChatGPT Pro / Gemini Pro are **app/CLI subscriptions, not API keys.** To use the quota we pay for, each reviewer runs through its subscription-authenticated CLI. Those CLIs auth interactively (browser OAuth on the local machine), which CI can't hold — so the cross-vendor panel runs from a **local** command and posts findings to the PR, while CI handles deterministic gates + Copilot. Rejected: paying metered API to run the panel in CI (double-pays the subscriptions).

### D6. Risk model and the scrutiny dial
Risk levels LOW / MEDIUM / HIGH / CRITICAL (per `AGENTS.md`) set how much scrutiny a change gets (self-flag/spot-check → cross-vendor reviewer + Copilot → security lens + line-by-line → adversary + blast radius + mandatory human). A **deterministic floor** (path globs, dep-manifest changes, diff size, coverage) the author can *raise* but can only *lower* with a second agent's or the human's concurrence.

### D7. Pipeline ordering — cheap and deterministic first
prompt → author + self-flag → capture prompt artifact (MEDIUM+) → commit w/ provenance trailers → PR → cheap deterministic gates → triage → expensive gates (risk-gated) → AI panel (local, posts to PR) → arbiter → human gate (conversation-resolution enforced) → merge → archive. Rationale: never spend an expensive reviewer on something a linter would reject.

### D8. Prompts as source code
Prompts = the "C source", generated code = the "compiled artifact"; the prompt should regenerate the code. Unlike a normal build, **both** are committed/versioned (the analogy governs provenance, not VCS policy). 🔧 A finer-grained append-only **raw** turn log + regenerable **summaries** + a **watermark** (resumable across sessions) is designed, not built.

### D9. Bootstrap scope — oversight tooling only
The bootstrap installs only what the oversight system needs (agent CLIs, their Node runtime, `gh`) — never project frameworks/libraries. Those stay with each project's own setup. Keeps the bootstrap portable and repo-independent.

### D10. Two distinct bootstraps
- `setup_oversight.sh` ✅ — bootstraps the protocol **into a repo** (AGENTS.md, CODEOWNERS, PR template, permissions, capture/audit, branch protection).
- `setup_clis.sh` ✅ — repo-**independent machine** bootstrap of the agent CLIs (install/auth/smoke/doctor). "Drop it in any repo, run it, it just works."

### D11. Antigravity migration
Google is retiring the Gemini CLI (consumer shutoff **2026-06-18**) in favor of the Antigravity CLI (`agy`). `setup_clis.sh` installs `agy` via Google's official installer (native Go binary, no Node). Auth is a **device-code flow** (`agy` has no `auth` subcommand; first interactive run triggers Google Sign-In); `-p/--print` verified for headless smoke.

### D12. PR policy — comments must be resolved to merge
`required_review_thread_resolution` enabled on protected `main` (in addition to ≥1 approval). This is what turns panel findings into review threads a human must address before merge — the human-attention routing mechanism.

### D13. Worked example — correct escalation on `curl | bash`
The agent tried to run the `agy` installer (`curl … | bash`); the repo's own `.claude/settings.json` policy **blocked** it and escalated to the human, who reviewed the (checksum-verified, user-scoped, no-sudo) installer and decided: **trust the vendor, keep autoupdate on for security patches.** A clean demonstration of a deterministic gate routing a genuine trust decision to a human, with the AI informing — not replacing — the call.

### D14. History/memory split
Oversight-**system** history lives with this repo (its session memory + this `DECISIONS.md`); **app** repos keep only app/user memory. Rationale: session memory is keyed by working directory, so the system's design history must live where the system is developed, for continuity.

---

## Open / pending

- **Multi-agent panel (`run_panel.sh`)** 🔧 — next to build. 4 design decisions pending confirmation (leans): whole-PR diff + size-cap→chunk; arbiter summary comment always + line-level threads at HIGH/CRITICAL; manual trigger first (hook later); best-effort findings-JSON extraction (add re-prompt-on-failure if flaky).
- **Raw archive + watermark** 🔧 — the append-only turn log + regenerable summaries (D8).
- `.antigravitycli/` into `setup_oversight.sh`'s emitted `.gitignore`; Windows support in `setup_clis.sh`.
