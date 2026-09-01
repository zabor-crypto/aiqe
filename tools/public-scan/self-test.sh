#!/usr/bin/env bash
#
# Self-test for the public sanitisation scanner.
#
# A gate that has never been shown to fail is not a gate. This script proves
# two things about the scanner, and it is the control that must accompany any
# change to patterns.txt:
#
#   1. Every declared pattern class still matches its positive control.
#      A class added without a control fails here. A class tightened until it
#      no longer matches real private material fails here too.
#
#   2. The known false positives stay negative. When a pattern is narrowed
#      against a demonstrated false positive, the string that caused it is
#      recorded below, so that a later "simplification" that reintroduces the
#      noise is caught rather than discovered by someone disabling the gate.
#
# Exit codes:  0 = self-test passed   1 = self-test failed   2 = could not run

set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
scanner="$here/public-scan.sh"
patterns="$here/patterns.txt"
corpus="$here/self-test-corpus.txt"

for required in "$scanner" "$patterns" "$corpus"; do
  if [ ! -f "$required" ]; then
    echo "self-test: missing $required" >&2
    exit 2
  fi
done

workdir=$(mktemp -d) || exit 2
trap 'rm -rf "$workdir"' EXIT

# --- 1. Positive controls: every class must still fire. --------------------

positive="$workdir/positive"
mkdir -p "$positive/tools/public-scan" || exit 2
cp "$scanner" "$positive/tools/public-scan/public-scan.sh"
cp "$patterns" "$positive/tools/public-scan/patterns.txt"
cp "$corpus" "$positive/corpus-under-test.txt"

positive_output=$("$positive/tools/public-scan/public-scan.sh" 2>&1)
positive_status=$?

failures=0

if [ "$positive_status" -ne 1 ]; then
  echo "FAIL: scanner exited $positive_status on the positive corpus, expected 1"
  failures=$((failures + 1))
fi

while IFS= read -r line; do
  case "$line" in
    ''|'#'*) continue ;;
  esac
  class="${line%%:::*}"
  [ "$class" = "$line" ] && continue
  if ! printf '%s\n' "$positive_output" | grep -qF "FINDING [$class]"; then
    echo "FAIL: pattern class $class matched nothing in the positive corpus."
    echo "      Either the class was tightened until it no longer detects"
    echo "      anything, or it was added without a control. Add one to"
    echo "      self-test-corpus.txt."
    failures=$((failures + 1))
  fi
done < "$patterns"

# --- 2. Known false positives must stay negative. --------------------------
#
# Each entry is a string that a previous version of a pattern matched
# incorrectly. They are written literally here because, by construction, they
# are benign.

negative="$workdir/negative"
mkdir -p "$negative/tools/public-scan" || exit 2
cp "$scanner" "$negative/tools/public-scan/public-scan.sh"
cp "$patterns" "$negative/tools/public-scan/patterns.txt"

cat > "$negative/benign.txt" <<'BENIGN'
A repository .claude/settings.local.json file is agent configuration.
Reading .claude/settings.json and .claude/settings.local.json is bounded.
The relative path tools/public-scan/patterns.txt is not a hostname.
BENIGN

negative_output=$("$negative/tools/public-scan/public-scan.sh" 2>&1)
negative_status=$?

if [ "$negative_status" -ne 0 ]; then
  echo "FAIL: scanner reported findings on benign content:"
  printf '%s\n' "$negative_output" | sed 's/^/    /'
  failures=$((failures + 1))
fi

if [ "$failures" -gt 0 ]; then
  echo "self-test: FAIL - $failures problem(s)"
  exit 1
fi

echo "self-test: PASS - every pattern class fires on its control, and the"
echo "self-test: recorded false positives stay negative."
exit 0
