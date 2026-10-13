#!/bin/bash
# Run all repro sweeps detached from any agent session; one notification when done.
# Usage: scripts/sweep-unattended.sh [results-dir] [repo-dir] [crate] [extra run_repros args...]
set -u
cd "$(dirname "$0")/.."
RES=${1:-results/tokenizers}; REPO=${2:-work/tokenizers}; CRATE=${3:-tokenizers}; shift $(( $# < 3 ? $# : 3 ))
STAMP=$(date +%Y%m%d-%H%M%S); LOG=work/unattended-$STAMP.log; SUMMARY=$RES/SUMMARY.md
cargo build -q || exit 1
START=$(date +%s)
python3 results/run_repros.py "$RES" "$REPO" "$CRATE" "$@" > "$LOG" 2>&1; STATUS=$?
MIN=$(( ($(date +%s) - START) / 60 ))
{ echo "# Sweep run $STAMP"; echo; echo "- exit status: $STATUS"; echo "- wall time: ${MIN} min"; echo "- log: $LOG"; echo;
  grep -E '^== |^   |^!!' "$LOG" | sed 's/ --repo .*//'; } > "$SUMMARY"
osascript -e "display notification \"exit $STATUS, ${MIN} min — see $SUMMARY\" with title \"bug-age sweep finished\"" 2>/dev/null
exit $STATUS
