#!/usr/bin/env bash
# archive-session.sh
#
# Purpose : Create a timestamped chat-history archive file in
#           slr/methodology/chat-history/.
# Inputs  : --mode checkpoint|summary  (default: checkpoint)
#           --title "Session title"    (optional; used in filename and heading)
#           --body-file <path>         (optional; prepend a file's content)
# Outputs : slr/methodology/chat-history/YYYY-MM-DD_HHMM[_summary].md
# Deps    : bash 3+, date, sed — no external packages required

set -euo pipefail

MODE="checkpoint"
TITLE=""
BODY_FILE=""

usage() {
  echo "Usage: $0 [--mode checkpoint|summary] [--title \"Title\"] [--body-file path]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)       MODE="$2";      shift 2 ;;
    --title)      TITLE="$2";     shift 2 ;;
    --body-file)  BODY_FILE="$2"; shift 2 ;;
    -h|--help)    usage ;;
    *)            echo "Unknown flag: $1"; usage ;;
  esac
done

if [[ "$MODE" != "checkpoint" && "$MODE" != "summary" ]]; then
  echo "Error: --mode must be 'checkpoint' or 'summary'"
  usage
fi

# Resolve directory relative to this script so it works from any cwd
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_DIR="$SCRIPT_DIR/../methodology/chat-history"
mkdir -p "$ARCHIVE_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H%M)"
SUFFIX=""
[[ "$MODE" == "summary" ]] && SUFFIX="_summary"

# Sanitise title for filename (lowercase, spaces→dashes, strip non-alnum-dash)
TITLE_SLUG=""
if [[ -n "$TITLE" ]]; then
  TITLE_SLUG="_$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | sed 's/[^a-z0-9-]//g')"
fi

OUTFILE="$ARCHIVE_DIR/${TIMESTAMP}${TITLE_SLUG}${SUFFIX}.md"

DISPLAY_TITLE="${TITLE:-Untitled session}"
MODE_LABEL="Checkpoint"
[[ "$MODE" == "summary" ]] && MODE_LABEL="Session summary"

{
  echo "---"
  echo "date: $(date +%Y-%m-%dT%H:%M:%S%z)"
  echo "mode: $MODE"
  echo "title: \"$DISPLAY_TITLE\""
  echo "---"
  echo ""
  echo "# $MODE_LABEL — $DISPLAY_TITLE"
  echo ""
  echo "_Archived: $(date '+%A %d %B %Y at %H:%M %Z')_"
  echo ""

  if [[ "$MODE" == "summary" ]]; then
    echo "## Summary"
    echo ""
    echo "<!-- One paragraph: what was accomplished this session -->"
    echo ""
    echo "## Key decisions"
    echo ""
    echo "<!-- Bullet list of decisions made, with rationale -->"
    echo ""
    echo "## Next steps"
    echo ""
    echo "<!-- What to pick up in the next session -->"
    echo ""
  else
    echo "## Checkpoint log"
    echo ""
  fi

  if [[ -n "$BODY_FILE" && -f "$BODY_FILE" ]]; then
    cat "$BODY_FILE"
    echo ""
  else
    echo "<!-- Paste or narrate the turn-by-turn exchange below -->"
    echo ""
  fi
} > "$OUTFILE"

echo "Created: $OUTFILE"
