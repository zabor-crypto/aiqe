#!/usr/bin/env bash
#
# Self-test for the public sanitisation scanner.
#
# A gate that has never been shown to fail is not a gate. This script proves
# two things about the scanner, and it is the control that must accompany any
# change to patterns.txt:
#
#   1. Every declared pattern class still matches *its own* positive control,
#      identified by the leading label its corpus line carries. A class added
#      without a control fails here. A class tightened until it no longer
#      matches real private material fails here too. So does a class whose
#      control has been deleted and which is now only firing on some other
#      class's control - the failure mode that let `GIT_SHA_40` rest on the
#      `CRYPTO_WALLET_EVM` line.
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

# A class must match *its own* control, not merely something in the corpus.
#
# "The class produced a finding" is too weak an assertion, because one control
# line can satisfy two classes by accident. `GIT_SHA_40` was exactly that: the
# `CRYPTO_WALLET_EVM` control is `0x` followed by forty hex characters, so it
# also satisfied the bare-object-id class, and deleting `GIT_SHA_40`'s own
# control left this self-test passing. A control that can be deleted without
# failing the gate is not protecting anything.
#
# So each class is required to match a line the corpus *designates* as its
# control. The designation is the leading label every corpus line carries.
control_designation() {
  # `TRANSCRIPT_MARKER` is anchored to the start of the line and therefore
  # cannot carry a leading label - and it must not be given a trailing one,
  # because two of the controls exist to exercise an end-of-line boundary.
  # Its control is identified by the shape it is testing instead.
  case "$1" in
    TRANSCRIPT_MARKER) printf '^Human:[[:space:]]' ;;
    *) printf '^%s[[:space:]]' "$1" ;;
  esac
}

# The content of every line the scanner reported for one class, with grep's
# `file:lineno:` prefix removed.
matched_lines() {
  printf '%s\n' "$positive_output" | awk -v want="FINDING [$1]" '
    $0 == want { collecting = 1; next }
    collecting && /^FINDING \[/ { collecting = 0 }
    collecting && $0 ~ /^[[:space:]]+[^[:space:]]/ { print }
  ' | sed -E 's/^[[:space:]]*[^:]*:[0-9]+://'
}

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
  elif ! matched_lines "$class" | grep -qE "$(control_designation "$class")"; then
    echo "FAIL: pattern class $class matched the corpus, but not its own"
    echo "      control line. Either the control was removed - in which case"
    echo "      the class is now resting on another class's control and is"
    echo "      unprotected - or it was renamed away from its leading label."
    echo "      Add or restore the $class line in self-test-corpus.txt."
    failures=$((failures + 1))
  fi
done < "$patterns"

# --- 2. Known false positives must stay negative. --------------------------
#
# Each entry is a string that a previous version of a pattern matched
# incorrectly. They are written literally here because, by construction, they
# are benign.
#
# The last entry is different in kind: it is not a narrowed pattern but the
# recorded `GIT_SHA_40` exception for a pinned action reference, kept here so
# that the exception is exercised rather than merely described. Its object id
# is the same synthetic placeholder the positive corpus uses, so if the
# exception were ever dropped this line would start being reported - which is
# the regression worth catching. A *bare* id in a workflow is still a finding;
# that narrowness is asserted in `tests/test_workflow_pinning.py`.

negative="$workdir/negative"
mkdir -p "$negative/tools/public-scan" || exit 2
cp "$scanner" "$negative/tools/public-scan/public-scan.sh"
cp "$patterns" "$negative/tools/public-scan/patterns.txt"

cat > "$negative/benign.txt" <<'BENIGN'
A repository .claude/settings.local.json file is agent configuration.
Reading .claude/settings.json and .claude/settings.local.json is bounded.
The relative path tools/public-scan/patterns.txt is not a hostname.
The identifier receipt.LOCAL_REDACTION_POLICY is a dotted attribute reference.
A local receipt names policy aiqe.receipt.local.v1 in its own output.
      - uses: actions/checkout@0123456789abcdef0123456789abcdef01234567 # v4.0.0
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
