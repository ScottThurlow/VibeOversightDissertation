#!/usr/bin/env bash
# install-search-tools.sh
#
# Purpose : Bootstrap Exa, Semantic Scholar, and Zotero tooling for the SLR
#           on a fresh macOS or Linux/Ubuntu machine.
# Inputs  : Interactive prompts for API keys (or pre-set in environment)
# Outputs : Registered MCP servers in ~/.claude/settings.json,
#           Python deps installed, slr/.env created from .env.example
# Deps    : bash 4+, curl, python3, pip3, claude (Claude Code CLI)
#
# Usage:
#   bash slr/scripts/install-search-tools.sh
#   bash slr/scripts/install-search-tools.sh --non-interactive  # use env vars only
#
# Pre-set env vars to skip prompts:
#   EXA_API_KEY             - from https://dashboard.exa.ai/api-keys
#   SEMANTIC_SCHOLAR_API_KEY - optional; leave unset to run unauthenticated (1 req/sec limit)
#   ZOTERO_API_KEY_READONLY  - from https://www.zotero.org/settings/keys
#   ZOTERO_API_KEY_READWRITE - from https://www.zotero.org/settings/keys
#   ZOTERO_GROUP_ID          - visible in your Zotero group library URL

set -euo pipefail

# ── Helpers ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
error()   { echo -e "${RED}[error]${RESET} $*" >&2; }
section() { echo -e "\n${BOLD}── $* ──────────────────────────────────────${RESET}"; }

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
  OS="macos"
elif [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "$ID" == "ubuntu" || "$ID_LIKE" == *"ubuntu"* || "$ID_LIKE" == *"debian"* ]]; then
    OS="ubuntu"
  fi
fi

if [[ "$OS" == "unknown" ]]; then
  warn "Unrecognised OS — proceeding anyway, but some steps may need manual adjustment."
fi

# Detect shell profile to write exports into
detect_shell_profile() {
  local shell_name
  shell_name="$(basename "${SHELL:-/bin/bash}")"
  if [[ "$shell_name" == "zsh" ]]; then
    echo "${ZDOTDIR:-$HOME}/.zshrc"
  else
    echo "$HOME/.bashrc"
  fi
}
SHELL_PROFILE="$(detect_shell_profile)"

# Add a line to the shell profile only if it's not already there
add_to_profile() {
  local line="$1"
  if ! grep -qF "$line" "$SHELL_PROFILE" 2>/dev/null; then
    echo "$line" >> "$SHELL_PROFILE"
    ok "Added to $SHELL_PROFILE: $line"
  else
    ok "Already in $SHELL_PROFILE: $line"
  fi
}

# Check if an MCP server name is already registered
mcp_registered() {
  claude mcp list 2>/dev/null | grep -q "^$1:"
}

# Prompt for a value; use env var if already set; skip prompt in non-interactive mode
INTERACTIVE=true
[[ "${1:-}" == "--non-interactive" ]] && INTERACTIVE=false

prompt_or_env() {
  local var_name="$1"
  local prompt_text="$2"
  local required="${3:-true}"

  if [[ -n "${!var_name:-}" ]]; then
    ok "$var_name already set in environment — skipping prompt."
    return
  fi

  if $INTERACTIVE; then
    echo -n "  $prompt_text: "
    # shellcheck disable=SC2229
    read -r "$var_name"
  fi

  if [[ "$required" == "true" && -z "${!var_name:-}" ]]; then
    error "$var_name is required but was not provided. Re-run with it set or answer the prompt."
    exit 1
  fi
}

# ── Resolve script location → find slr/ root ─────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SLR_DIR="$(dirname "$SCRIPT_DIR")"   # slr/
ENV_FILE="$SLR_DIR/.env"
ENV_EXAMPLE="$SLR_DIR/.env.example"

# ── 1. Prerequisites ──────────────────────────────────────────────────────────

section "1. Prerequisites"

# Claude Code CLI
if ! command -v claude &>/dev/null; then
  error "Claude Code CLI ('claude') not found. Install it first:"
  error "  https://claude.ai/download"
  exit 1
fi
ok "claude CLI found: $(claude --version 2>/dev/null | head -1)"

# Python 3
if ! command -v python3 &>/dev/null; then
  error "python3 not found. Install Python 3.9+ first."
  exit 1
fi
ok "python3 found: $(python3 --version)"

# pip3
if ! command -v pip3 &>/dev/null; then
  warn "pip3 not found — attempting to bootstrap via python3 -m pip"
  python3 -m ensurepip --upgrade 2>/dev/null || {
    error "Could not bootstrap pip. Install pip3 manually."
    exit 1
  }
fi
ok "pip3 available"

# uv / uvx (needed for Semantic Scholar MCP)
if ! command -v uvx &>/dev/null; then
  info "uvx not found — installing uv toolchain..."
  if [[ "$OS" == "macos" ]]; then
    if command -v brew &>/dev/null; then
      brew install uv
    else
      curl -LsSf https://astral.sh/uv/install.sh | sh
      # Reload PATH so uvx is visible in this shell
      export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
  elif [[ "$OS" == "ubuntu" ]]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  else
    warn "Unknown OS — trying curl-based uv install."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  fi

  if ! command -v uvx &>/dev/null; then
    error "uvx still not found after install. Add ~/.local/bin or ~/.cargo/bin to PATH and rerun."
    exit 1
  fi
fi
ok "uvx found: $(uvx --version 2>/dev/null || echo 'ok')"

# ── 2. Python dependencies (Zotero client) ────────────────────────────────────

section "2. Python dependencies"

info "Installing requests and python-dotenv..."
# --break-system-packages is required on Homebrew Python 3.12+ (PEP 668 "externally managed").
# --user keeps the install in ~/.local so it doesn't touch the Homebrew prefix.
pip3 install --quiet --user --break-system-packages requests python-dotenv
ok "requests + python-dotenv installed"

# ── 3. Collect API keys ───────────────────────────────────────────────────────

section "3. API keys"

echo
info "EXA_API_KEY — get yours at https://dashboard.exa.ai/api-keys"
prompt_or_env EXA_API_KEY "EXA_API_KEY" true

echo
info "SEMANTIC_SCHOLAR_API_KEY — optional; press Enter to skip (1 req/sec unauthenticated limit)"
info "Request a key at https://www.semanticscholar.org/product/api"
prompt_or_env SEMANTIC_SCHOLAR_API_KEY "SEMANTIC_SCHOLAR_API_KEY (leave blank to skip)" false

echo
info "Zotero keys — create read-only and read-write keys at https://www.zotero.org/settings/keys"
prompt_or_env ZOTERO_API_KEY_READONLY "ZOTERO_API_KEY_READONLY" false
prompt_or_env ZOTERO_API_KEY_READWRITE "ZOTERO_API_KEY_READWRITE" false
prompt_or_env ZOTERO_GROUP_ID "ZOTERO_GROUP_ID (number in your group library URL)" false

# ── 4. Shell profile exports ──────────────────────────────────────────────────

section "4. Shell profile ($SHELL_PROFILE)"

add_to_profile "export EXA_API_KEY=\"$EXA_API_KEY\""

if [[ -n "${SEMANTIC_SCHOLAR_API_KEY:-}" ]]; then
  add_to_profile "export SEMANTIC_SCHOLAR_API_KEY=\"$SEMANTIC_SCHOLAR_API_KEY\""
fi

# ── 5. Exa MCP server ─────────────────────────────────────────────────────────

section "5. Exa MCP server"

if mcp_registered "exa"; then
  ok "MCP server 'exa' already registered — skipping."
else
  info "Registering Exa MCP server..."
  claude mcp add \
    --transport http \
    --header "Authorization: Bearer $EXA_API_KEY" \
    --scope user \
    exa \
    "https://mcp.exa.ai/mcp"
  ok "Exa MCP server registered."
fi

# ── 6. Exa Claude Code plugin ─────────────────────────────────────────────────

section "6. Exa plugin"

if claude plugin list 2>/dev/null | grep -q "exa@claude-plugins-official"; then
  ok "Exa plugin already installed — skipping."
else
  info "Installing exa@claude-plugins-official plugin..."
  claude plugin install exa@claude-plugins-official --yes 2>/dev/null || \
    warn "Plugin install returned non-zero — it may already be installed or need a restart."
fi

# ── 7. Semantic Scholar MCP server ────────────────────────────────────────────

section "7. Semantic Scholar MCP server"

if mcp_registered "semantic-scholar"; then
  ok "MCP server 'semantic-scholar' already registered — skipping."
else
  info "Registering Semantic Scholar MCP server..."
  if [[ -n "${SEMANTIC_SCHOLAR_API_KEY:-}" ]]; then
    claude mcp add \
      --scope user \
      -e "SEMANTIC_SCHOLAR_API_KEY=$SEMANTIC_SCHOLAR_API_KEY" \
      semantic-scholar \
      -- uvx semantic-scholar-fastmcp
  else
    claude mcp add \
      --scope user \
      semantic-scholar \
      -- uvx semantic-scholar-fastmcp
    warn "Running Semantic Scholar unauthenticated — max 1 req/sec. Run calls sequentially."
  fi
  ok "Semantic Scholar MCP server registered."
fi

# ── 8. Zotero .env file ───────────────────────────────────────────────────────

section "8. Zotero .env"

if [[ -f "$ENV_FILE" ]]; then
  ok ".env already exists at $ENV_FILE — not overwriting."
  info "Edit it manually if you need to update credentials."
else
  if [[ ! -f "$ENV_EXAMPLE" ]]; then
    error ".env.example not found at $ENV_EXAMPLE — is this script running from inside the repo?"
    exit 1
  fi
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  ok "Copied .env.example → .env"

  # Populate any values we already have
  if [[ -n "${ZOTERO_API_KEY_READONLY:-}" ]]; then
    sed -i.bak "s|^ZOTERO_API_KEY_READONLY=.*|ZOTERO_API_KEY_READONLY=$ZOTERO_API_KEY_READONLY|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
  fi
  if [[ -n "${ZOTERO_API_KEY_READWRITE:-}" ]]; then
    sed -i.bak "s|^ZOTERO_API_KEY_READWRITE=.*|ZOTERO_API_KEY_READWRITE=$ZOTERO_API_KEY_READWRITE|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
  fi
  if [[ -n "${ZOTERO_GROUP_ID:-}" ]]; then
    sed -i.bak "s|^ZOTERO_GROUP_ID=.*|ZOTERO_GROUP_ID=$ZOTERO_GROUP_ID|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
  fi

  ok "Zotero credentials written to $ENV_FILE"
fi

# ── 9. Summary ────────────────────────────────────────────────────────────────

section "Done"
echo
echo -e "${GREEN}${BOLD}Installation complete.${RESET} Next steps:"
echo
echo "  1. Reload your shell:  source $SHELL_PROFILE"
echo "  2. Restart Claude Code so MCP servers are picked up."
echo "  3. Verify with:        claude mcp list"
echo
if [[ -z "${ZOTERO_API_KEY_READONLY:-}" || -z "${ZOTERO_GROUP_ID:-}" ]]; then
  echo -e "  4. ${YELLOW}Fill in remaining Zotero keys in:${RESET}"
  echo "       $ENV_FILE"
  echo "     Then test with:  python3 $SCRIPT_DIR/zotero_client.py list-collections"
  echo
fi
echo "  Rate limit reminder: Semantic Scholar is 1 req/sec without an API key."
echo "  Run Semantic Scholar calls sequentially (never in parallel)."
echo
