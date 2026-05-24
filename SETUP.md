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

**GitHub token scopes needed for branch protection:**
The token needs either:
- Classic token: `repo` scope
- Fine-grained token: `Contents` (read) + `Pull requests` (read/write) + `Administration` (read/write) on the target repo

---

## Installation

### Step 1 — Clone to a stable tools directory

```bash
# macOS
git clone https://github.com/sthurlow/VibeOversightDissertation \
  ~/tools/VibeOversightDissertation

# Linux / Faberix
git clone https://github.com/sthurlow/VibeOversightDissertation \
  ~/tools/VibeOversightDissertation
```

Keep it in `~/tools/` or similar — the bootstrap script references its own
location to find templates, so the path needs to be stable.

### Step 2 — Make scripts executable

```bash
chmod +x ~/tools/VibeOversightDissertation/scripts/setup_oversight.sh
chmod +x ~/tools/VibeOversightDissertation/templates/capture_prompt.sh
chmod +x ~/tools/VibeOversightDissertation/templates/prompt_audit.sh
```

### Step 3 — Optional: add to PATH

Add a convenience alias so you can call the bootstrap from anywhere:

```bash
# Add to ~/.bashrc or ~/.zshrc
export VIBE_OVERSIGHT="$HOME/tools/VibeOversightDissertation"
alias setup-oversight="$VIBE_OVERSIGHT/scripts/setup_oversight.sh"
```

Then reload:
```bash
source ~/.bashrc   # or ~/.zshrc
```

Now you can run `setup-oversight /path/to/repo` from anywhere.

### Step 4 — Configure GitHub token

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
│   └── setup_oversight.sh       ← main bootstrap script
│                                   run this against any target repo
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
additional Astro/framework-specific warnings, etc.):

```bash
# Pull latest from GitHub
cd ~/tools/VibeOversightDissertation
git pull

# Propagate AGENTS.md update to each target repo
setup-oversight ~/code/tutelare --update-agents
setup-oversight ~/code/other-repo --update-agents
# etc.
```

`--update-agents` touches only `AGENTS.md` in the target repo — scripts,
CODEOWNERS, PR template, and prompts directory are left unchanged.

---

## Multi-Machine Setup

This repo is installed on both Mac (primary development) and Faberix (research workstation). Repeat Steps 1–4 on each machine. The stable clone path (`~/tools/VibeOversightDissertation`) should be consistent across machines for predictability.

To update all machines after a protocol change:
```bash
# On each machine:
cd ~/tools/VibeOversightDissertation && git pull
```

---

## Troubleshooting

**Branch protection fails with "Not Found" or 403:**
- Confirm the repo exists on GitHub and has at least one commit pushed
- Verify `GH_TOKEN` has `repo` scope or fine-grained `Administration` permission
- Confirm you are the repo owner or have admin rights

**`setup_oversight.sh: command not found` after alias setup:**
- Run `source ~/.bashrc` (or `~/.zshrc`) to reload shell config
- Or call directly: `~/tools/VibeOversightDissertation/scripts/setup_oversight.sh`

**CODEOWNERS shows `@OWNER` placeholder:**
- The script couldn't detect a GitHub remote at install time
- Edit `.github/CODEOWNERS` manually: replace `@OWNER` with your GitHub username (e.g. `@sthurlow`)
- Or push the repo to GitHub first, then re-run: `setup-oversight . --force`

**Claude Code doesn't pick up AGENTS.md:**
- Confirm `AGENTS.md` is in the repo root (not in `.claude/` or a subdirectory)
- Start a new Claude Code session — AGENTS.md is read at session start, not mid-session
