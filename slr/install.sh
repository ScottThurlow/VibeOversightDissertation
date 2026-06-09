#!/usr/bin/env bash
# install.sh — SLR pipeline machine setup
#
# Sets up a fresh macOS, Linux, or Windows (Git Bash) machine:
#   • Python deps (requests, python-dotenv, openpyxl)
#   • slr/.env file (interactive key entry)
#   • Claude Code MCP servers: exa, semantic-scholar
#   • Exa Claude plugin
#   • Verifies Stop hook is wired in slr/.claude/settings.json
#
# Usage (run from anywhere inside the repo):
#   bash slr/install.sh
#
# Rate limit note:
#   Semantic Scholar is 1 req/sec even with an API key.
#   Any citation-chasing script must sleep(1) between calls.

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
fail()    { echo -e "${RED}[fail]${RESET}  $*" >&2; exit 1; }
section() { echo -e "\n${BOLD}── $* ──────────────────────────────────────────────────${RESET}"; }
ask()     { echo -n -e "  ${CYAN}?${RESET} $1: "; }

# ── Locate slr/ root regardless of where script is called from ───────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(basename "$SCRIPT_DIR")" == "slr" ]]; then
  SLR_DIR="$SCRIPT_DIR"
elif [[ -d "$SCRIPT_DIR/slr" ]]; then
  SLR_DIR="$SCRIPT_DIR/slr"
else
  fail "Cannot find slr/ directory. Run this script from inside the repo."
fi

ENV_FILE="$SLR_DIR/.env"
SETTINGS_FILE="$SLR_DIR/.claude/settings.json"

# ── OS detection ─────────────────────────────────────────────────────────────

OS="unknown"
case "$OSTYPE" in
  darwin*)                        OS="macos"   ;;
  msys*|cygwin*|mingw*)           OS="windows" ;;  # Git Bash / MINGW
  linux*)
    grep -qi "ubuntu\|debian" /etc/os-release 2>/dev/null && OS="ubuntu" || OS="linux"
    ;;
esac

info "Detected OS: $OS (OSTYPE=$OSTYPE)"
[[ "$OS" == "unknown" ]] && warn "Unrecognised OS — continuing; some steps may need manual adjustment."

# ── Resolve python and pip commands ──────────────────────────────────────────
# Windows often has 'python' but not 'python3'; Linux/macOS have both.

PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null && "$cmd" -c "import sys; assert sys.version_info >= (3,9)" 2>/dev/null; then
    PYTHON="$cmd"; break
  fi
done
[[ -z "$PYTHON" ]] && fail "Python 3.9+ not found. Install from https://python.org"

PIP=""
for cmd in pip3 pip; do
  if command -v "$cmd" &>/dev/null; then
    PIP="$cmd"; break
  fi
done
if [[ -z "$PIP" ]]; then
  $PYTHON -m ensurepip --upgrade 2>/dev/null || fail "pip not found. Install pip manually."
  PIP="$PYTHON -m pip"
fi

# --break-system-packages: needed on Homebrew/Debian-managed Python; unknown flag on Windows pip
PIP_EXTRA=""
[[ "$OS" != "windows" ]] && PIP_EXTRA="--break-system-packages"

# ── Helper: read a key interactively, blank = skip ───────────────────────────

read_key() {
  local var="$1" prompt="$2" required="${3:-false}"
  ask "$prompt"
  read -r "$var"
  if [[ "$required" == "true" && -z "${!var}" ]]; then
    fail "$var is required."
  fi
}

# ── 1. Prerequisites ──────────────────────────────────────────────────────────

section "1. Prerequisites"

command -v claude &>/dev/null \
  || fail "'claude' CLI not found. Install Claude Code: https://claude.ai/download"
ok "claude: $(claude --version 2>/dev/null | head -1)"

ok "python: $($PYTHON --version)"
ok "pip: $($PIP --version | head -1)"

command -v curl &>/dev/null || fail "curl not found. Install curl and re-run."
ok "curl available"

if ! command -v uvx &>/dev/null; then
  info "uvx not found — installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin on all platforms (including Windows/Git Bash)
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uvx &>/dev/null \
    || fail "uvx still not found after install. Open a new terminal, add ~/.local/bin to PATH, and re-run."
fi
ok "uvx: $(uvx --version 2>/dev/null || echo 'ok')"

# ── 2. Python dependencies ────────────────────────────────────────────────────

section "2. Python dependencies"

# shellcheck disable=SC2086
$PIP install --quiet --user $PIP_EXTRA requests python-dotenv openpyxl
ok "requests, python-dotenv, openpyxl installed"

# ── 3. API keys ───────────────────────────────────────────────────────────────

section "3. API keys (press Enter to skip optional keys)"

echo
info "EXA  →  https://dashboard.exa.ai/api-keys"
read_key EXA_API_KEY "EXA_API_KEY (required)" true

echo
info "Semantic Scholar  →  https://www.semanticscholar.org/product/api"
info "Rate limit is 1 req/sec WITH OR WITHOUT a key."
read_key S2_KEY "SEMANTIC_SCHOLAR_API_KEY (optional, Enter to skip)" false

echo
info "Zotero  →  https://www.zotero.org/settings/keys"
info "Create two keys scoped to group library 6505702 — read-only and read-write."
read_key ZOT_RO  "ZOTERO_API_KEY_READONLY  (optional)" false
read_key ZOT_RW  "ZOTERO_API_KEY_READWRITE (optional)" false
read_key ZOT_GID "ZOTERO_GROUP_ID (default 6505702, Enter to accept)" false
ZOT_GID="${ZOT_GID:-6505702}"

# ── 4. Write slr/.env ─────────────────────────────────────────────────────────

section "4. slr/.env"

write_env() {
  cat > "$ENV_FILE" <<EOF
# SLR pipeline credentials — generated by install.sh
# DO NOT commit this file.

# Exa
EXA_API_KEY=${EXA_API_KEY}

# Semantic Scholar (1 req/sec limit even with a key — always sleep between calls)
SEMANTIC_SCHOLAR_API_KEY=${S2_KEY}

# Zotero
ZOTERO_API_KEY_READONLY=${ZOT_RO}
ZOTERO_API_KEY_READWRITE=${ZOT_RW}
ZOTERO_GROUP_ID=${ZOT_GID}
ZOTERO_USER_ID=
ZOTERO_LIBRARY_TYPE=group
ZOTERO_API_BASE_URL=https://api.zotero.org
EOF
}

if [[ -f "$ENV_FILE" ]]; then
  warn ".env already exists at $ENV_FILE"
  ask "Overwrite it? [y/N]"
  read -r OVERWRITE
  # ${var,,} (lowercase) requires bash 4+; Git Bash ships bash 4.4 so this is safe
  if [[ "${OVERWRITE,,}" == "y" ]]; then
    write_env
    ok "Overwrote $ENV_FILE"
  else
    info "Skipped — existing .env untouched."
  fi
else
  write_env
  ok "Created $ENV_FILE"
fi

# ── 5. Exa MCP server ─────────────────────────────────────────────────────────

section "5. MCP — Exa"

if claude mcp list 2>/dev/null | grep -q "^exa:"; then
  ok "MCP server 'exa' already registered."
else
  claude mcp add \
    --transport http \
    --header "Authorization: Bearer ${EXA_API_KEY}" \
    --scope user \
    exa \
    "https://mcp.exa.ai/mcp"
  ok "Exa MCP server registered."
fi

# ── 6. Exa Claude plugin ──────────────────────────────────────────────────────

section "6. Exa plugin"

if claude plugin list 2>/dev/null | grep -q "exa@claude-plugins-official"; then
  ok "Exa plugin already installed."
else
  claude plugin install exa@claude-plugins-official --yes 2>/dev/null \
    || warn "Plugin install returned non-zero — may already be installed or need a restart."
fi

# ── 7. Semantic Scholar MCP server ────────────────────────────────────────────

section "7. MCP — Semantic Scholar"

if claude mcp list 2>/dev/null | grep -q "^semantic-scholar:"; then
  ok "MCP server 'semantic-scholar' already registered."
else
  if [[ -n "$S2_KEY" ]]; then
    claude mcp add --scope user \
      -e "SEMANTIC_SCHOLAR_API_KEY=${S2_KEY}" \
      semantic-scholar -- uvx semantic-scholar-fastmcp
  else
    claude mcp add --scope user \
      semantic-scholar -- uvx semantic-scholar-fastmcp
    warn "No S2 key — running unauthenticated (1 req/sec). Calls must be sequential."
  fi
  ok "Semantic Scholar MCP server registered."
fi

# ── 8. Stop hook ──────────────────────────────────────────────────────────────

section "8. Stop hook (session archiver)"

if [[ -f "$SETTINGS_FILE" ]] && grep -q "auto-archive-hook" "$SETTINGS_FILE" 2>/dev/null; then
  ok "Stop hook already configured in $SETTINGS_FILE"
else
  warn "Stop hook not found in $SETTINGS_FILE"
  info "Expected entry in slr/.claude/settings.json:"
  echo '    "hooks": { "Stop": [{ "hooks": [{ "type": "command", "command": "bash scripts/auto-archive-hook.sh" }] }] }'
  info "Add it manually, or copy .claude/settings.json from another machine."
fi

# ── 9. Skills reminder ────────────────────────────────────────────────────────

section "9. Claude Code skills"

info "Skills are not in the git repo — copy them from Faberix if needed:"
echo "    Faberix source:  ~/jukebox/scott/slr/claude-skills/"
echo "    Target:          ~/.claude/skills/"
echo "    Reinstall cmd:   $PYTHON ~/.claude/skills/claude-skill-installer/scripts/install.py . --force"
echo
info "Skills: zotero, zotero-slr-dedup, arxiv-zotero-import, zotero-bulk-tagging,"
info "        claude-skill-installer, slr-project-init, slr-pipeline-patterns"

# ── 10. Verify Semantic Scholar key ──────────────────────────────────────────

section "10. Verify Semantic Scholar key"

if [[ -n "$S2_KEY" ]]; then
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "x-api-key: ${S2_KEY}" \
    "https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1")
  if [[ "$STATUS" == "200" ]]; then
    ok "Semantic Scholar key is valid (HTTP 200)."
  else
    warn "Semantic Scholar returned HTTP $STATUS — double-check the key in $ENV_FILE"
  fi
else
  info "No S2 key provided — skipping verification."
fi

# ── Done ──────────────────────────────────────────────────────────────────────

section "Done"
echo
echo -e "${GREEN}${BOLD}Setup complete.${RESET} Next steps:"
echo
if [[ "$OS" == "windows" ]]; then
  echo "  1. Close and reopen Git Bash so PATH changes take effect."
elif [[ "$OS" == "macos" ]]; then
  echo "  1. source ~/.zshrc"
else
  echo "  1. source ~/.bashrc"
fi
echo "  2. Restart Claude Code so MCP servers load."
echo "  3. claude mcp list  — verify exa and semantic-scholar appear."
echo "  4. Edit $ENV_FILE if any keys were skipped."
echo
echo -e "  ${YELLOW}Rate limit reminder:${RESET} Semantic Scholar is 1 req/sec."
echo "  Citation-chasing scripts must sleep(1) between every API call."
echo
