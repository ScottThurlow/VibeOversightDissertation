# Setup Guide

How to install and maintain this bootstrap repo on a new machine.

---

## Prerequisites

| Tool | Required | Purpose |
|---|---|---|
| `git` | Yes | Clone and manage repos |
| `bash` 3.2+ | Yes | Run the bootstrap scripts |
| `curl` | Yes | GitHub API calls (branch protection) |
| `gh` CLI | Recommended | Token auth fallback, repo creation |
| `GH_TOKEN` env var | For branch protection | GitHub personal access token |
| Node 22 + agent CLIs (`claude`, `codex`, `gemini`) | For the multi-agent panel | Installed by `scripts/setup_clis.sh` — see below |

macOS and Linux satisfy all of these by default except `gh`. Ubuntu 24 (including Faberix) has `curl` and `bash` pre-installed.

**Installing `gh` CLI:**
```bash
# macOS
brew install gh

# Ubuntu / Debian
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
  https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh

gh auth login   # follow prompts — browser or token
```

**Installing the agent CLIs (oversight panel):**

The multi-agent review panel runs the agent CLIs locally via your *subscriptions*
(Claude Max, ChatGPT Pro, Gemini Pro) — not API keys. The repo-independent
`setup_clis.sh` installs them, drives browser sign-in, and smoke-tests each:

```bash
./scripts/setup_clis.sh            # install -> auth -> smoke -> doctor
./scripts/setup_clis.sh doctor     # status only, no changes
```

It installs ONLY oversight tooling (the agent CLIs + Node runtime + `gh`) — never
project frameworks or libraries; each project installs those separately.

**GitHub token scopes needed for branch protection:**
The token needs either:
- Classic token: `repo` scope
- Fine-grained token: `Contents` (read) + `Pull requests` (read/write) + `Administration` (read/write) on the target repo

---

## Installation

### Step 1 — Clone the repo

```bash
# macOS / Linux / Faberix — clone to ~/code/
git clone https://github.com/ScottThurlow/VibeOversightDissertation \
  ~/code/VibeOversightDissertation
```

The bootstrap script references its own directory to find templates, so
the clone path needs to be stable across sessions. `~/code/` is recommended
for consistency across machines.

### Step 2 — Make scripts executable

```bash
chmod +x ~/code/VibeOversightDissertation/scripts/setup_oversight.sh
chmod +x ~/code/VibeOversightDissertation/templates/capture_prompt.sh
chmod +x ~/code/VibeOversightDissertation/templates/prompt_audit.sh
```

### Step 3 — Optional: add shell alias

```bash
# Add to ~/.bashrc or ~/.zshrc
alias setup-oversight="$HOME/code/VibeOversightDissertation/scripts/setup_oversight.sh"
```

Then reload:
```bash
source ~/.bashrc   # or ~/.zshrc
```

Now you can run `setup-oversight /path/to/repo` from anywhere.

### Step 4 — Bootstrap the repo against itself

The first thing to do after cloning is apply the oversight protocol to the
repo itself — it is both the tool and the first example of itself in use:

```bash
cd ~/code/VibeOversightDissertation
./scripts/setup_oversight.sh . --skip-commit
git add .
git commit -m "Bootstrap oversight protocol onto itself"
```

```bash
# Option A: gh CLI (recommended — token refreshes automatically)
gh auth login

# Option B: environment variable (add to ~/.bashrc or ~/.zshrc)
export GH_TOKEN=<your-personal-access-token>
```

The bootstrap script tries `GH_TOKEN` first, then falls back to `gh auth token`.
If neither is available, branch protection is skipped with a warning — all
other steps still complete.

---

## Bootstrapping a Target Repo

```bash
# Dry run first — no changes made
setup-oversight /path/to/repo --dry-run

# Full bootstrap
setup-oversight /path/to/repo

# Already-configured repo — safe to re-run, existing files are skipped
setup-oversight /path/to/repo

# Force overwrite all files (e.g. after a protocol update)
setup-oversight /path/to/repo --force

# Update only AGENTS.md across repos (after protocol revision)
setup-oversight /path/to/repo --update-agents

# Stage files but write your own commit message
setup-oversight /path/to/repo --skip-commit

# Skip GitHub API steps (no remote yet, or no token)
setup-oversight /path/to/repo --skip-github
```

---

## Directory Layout

```
VibeOversightDissertation/
│
├── README.md                    ← project overview and research context
├── SETUP.md                     ← this file
├── LICENSE.md                   ← CC BY-NC 4.0, Copyright © 2026 Scott Thurlow
│
├── scripts/
│   ├── setup_oversight.sh       ← bootstrap the protocol into a target repo
│   └── setup_clis.sh            ← install the agent CLIs on a machine (repo-independent)
│
└── templates/                   ← files installed into target repos
    ├── AGENTS.md                ← governance protocol for Claude Code
    ├── capture_prompt.sh        ← scaffold prompt artifact files
    └── prompt_audit.sh          ← query git-based audit trail
```

**What lives where after bootstrapping a target repo:**
```
<target-repo>/
├── AGENTS.md                            ← from templates/AGENTS.md
├── .github/
│   ├── CODEOWNERS                       ← generated with detected owner handle
│   └── pull_request_template.md         ← PR oversight checklist
├── scripts/
│   ├── capture_prompt.sh                ← from templates/capture_prompt.sh
│   └── prompt_audit.sh                  ← from templates/prompt_audit.sh
└── prompts/
    └── README.md                        ← prompt artifacts live here
```

---

## Permission Policy

The bootstrap installs `.claude/settings.json` with a risk-tiered permission
policy that eliminates low-value prompts while preserving meaningful oversight
gates.

| Category | Behavior |
|---|---|
| All file reads | Auto-approved |
| Writes to `src/`, `styles/`, `public/`, `content/`, `prompts/`, `tests/` | Auto-approved |
| Common file types (`.ts`, `.tsx`, `.astro`, `.md`, `.json`, `.css`) | Auto-approved |
| `git add`, `git commit`, `git diff`, `git status`, `git log` | Auto-approved |
| `gh pr create`, `gh pr view`, `gh pr list` | Auto-approved |
| `npm/pnpm/yarn` commands | Auto-approved |
| `git push` | **Prompts** |
| Config file writes, `.github/` changes | **Prompts** |
| `git push --force`, `git reset --hard` | **Blocked** |
| `gh pr merge`, `gh repo delete` | **Blocked** |
| `rm -rf`, `rm -f` | **Blocked** |
| Writes to `.env*`, secrets, credentials | **Blocked** |
| `sudo`, `curl | bash` | **Blocked** |
| Database destructive commands | **Blocked** |

**The research rationale:** Undifferentiated permission prompts on every action
cause automation bias — humans click through without reading. Risk-tiered gating
routes human attention only to actions with real consequences, which is the
oversight scaling mechanism under study in the dissertation.

### Machine-local overrides

For trusted local development sessions where you want to remove even the
remaining prompts, create a gitignored local override:

```bash
cat > .claude/settings.local.json << 'EOF'
{
  "dangerouslySkipPermissions": true
}
EOF
```

`settings.local.json` is in `.gitignore` — it applies only on your machine
and is never committed. The committed `settings.json` policy remains the
repo-level governance standard.

**Note:** `dangerouslySkipPermissions` disables all execution gates. Use only
during active local development sessions where you are watching the output.
AGENTS.md self-flagging (Human Review Required, risk classification) remains
active regardless — the oversight moves from execution gates to conversation
output.

When the protocol is revised (new risk categories, updated constructs,
additional framework-specific warnings, etc.):

```bash
# Pull latest from GitHub
cd ~/code/VibeOversightDissertation
git pull

# Propagate AGENTS.md update to each target repo
setup-oversight ~/code/tutelare --update-agents
setup-oversight ~/code/other-repo --update-agents
```

`--update-agents` touches only `AGENTS.md` in the target repo — scripts,
CODEOWNERS, PR template, settings.json, and prompts directory are left unchanged.

---

## Multi-Machine Setup

This repo is used on both Mac (primary development) and Faberix (research
workstation). Clone to the same path on each machine for consistency:

```bash
# On each machine:
git clone https://github.com/ScottThurlow/VibeOversightDissertation \
  ~/code/VibeOversightDissertation
chmod +x ~/code/VibeOversightDissertation/scripts/setup_oversight.sh
```

Add the alias to `~/.bashrc` or `~/.zshrc` on each machine:
```bash
alias setup-oversight="$HOME/code/VibeOversightDissertation/scripts/setup_oversight.sh"
```

---

## Troubleshooting

**Branch protection fails with "Not Found" or 403:**
- Confirm the repo exists on GitHub and has at least one commit pushed
- Verify `GH_TOKEN` has `repo` scope or fine-grained `Administration` permission
- Confirm you are the repo owner or have admin rights

**`setup_oversight.sh: command not found` after alias setup:**
- Run `source ~/.bashrc` (or `~/.zshrc`) to reload shell config
- Or call directly: `~/code/VibeOversightDissertation/scripts/setup_oversight.sh`

**CODEOWNERS shows `@OWNER` placeholder:**
- The script couldn't detect a GitHub remote at install time
- Edit `.github/CODEOWNERS` manually: replace `@OWNER` with your GitHub username (e.g. `@ScottThurlow`)
- Or push the repo to GitHub first, then re-run: `setup-oversight . --force`

**Claude Code doesn't pick up AGENTS.md:**
- Confirm `AGENTS.md` is in the repo root (not in `.claude/` or a subdirectory)
- Start a new Claude Code session — AGENTS.md is read at session start, not mid-session
