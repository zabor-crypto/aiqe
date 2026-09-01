#!/usr/bin/env bash
#
# AIQE public sanitisation scan.
#
# Scans every text file in the working tree against the pattern classes in
# patterns.txt, plus any local-only private literal list if one is present.
#
# This is a floor, not a proof. It catches the shapes it was told about.
# Paraphrased private material, an unredacted diagram label, or an asset derived
# from a real screenshot passes every pattern in the list. Human provenance
# review is mandatory and is not replaced by this script.
#
# Exit codes:  0 = clean   1 = findings   2 = scanner could not run

set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
patterns="$here/patterns.txt"

# Local-only private literals. Never committed; ignored by .gitignore.
private_list="$here/private-literals.txt"

if [ ! -f "$patterns" ]; then
  echo "public-scan: patterns.txt not found at $patterns" >&2
  exit 2
fi

cd "$root" || exit 2

# Build the file list: all text files, excluding .git and the pattern file
# itself (which necessarily contains the patterns it defines and is covered by
# human review instead).
files=()
while IFS= read -r -d '' f; do
  case "$f" in
    # In an ordinary worktree .git is a directory; in a linked worktree it is a
    # pointer file. Neither is repository content.
    ./.git|./.git/*) continue ;;
    ./tools/public-scan/patterns.txt) continue ;;
    ./tools/public-scan/private-literals.txt) continue ;;
    # The positive control corpus necessarily contains the shapes the scanner
    # looks for. self-test.sh scans it deliberately, in a temporary tree.
    ./tools/public-scan/self-test-corpus.txt) continue ;;
  esac
  if LC_ALL=C grep -qI . "$f" 2>/dev/null; then
    files+=("$f")
  fi
done < <(find . -type f -print0)

if [ "${#files[@]}" -eq 0 ]; then
  echo "public-scan: no text files found" >&2
  exit 2
fi

findings=0

scan_one() {
  local class="$1" regex="$2" hits
  hits=$(LC_ALL=C grep -nEI -i -- "$regex" "${files[@]}" 2>/dev/null)
  if [ -n "$hits" ]; then
    echo "FINDING [$class]"
    printf '%s\n' "$hits" | sed 's/^/    /'
    echo
    findings=$((findings + 1))
  fi
}

while IFS= read -r line; do
  case "$line" in
    ''|'#'*) continue ;;
  esac
  class="${line%%:::*}"
  regex="${line#*:::}"
  [ "$class" = "$regex" ] && continue
  scan_one "$class" "$regex"
done < "$patterns"

if [ -f "$private_list" ]; then
  echo "public-scan: applying local-only private literal list"
  while IFS= read -r term; do
    case "$term" in
      ''|'#'*) continue ;;
    esac
    scan_one "PRIVATE_LITERAL" "$term"
  done < "$private_list"
else
  echo "public-scan: no local private literal list present (public patterns only)"
fi

echo "public-scan: scanned ${#files[@]} text files against $(grep -cvE '^(#|$)' "$patterns") pattern classes"

if [ "$findings" -gt 0 ]; then
  echo "public-scan: FAIL - $findings pattern class(es) matched"
  exit 1
fi

echo "public-scan: PASS - no pattern class matched"
echo "public-scan: reminder - machine scan is a floor. Human provenance review is required before any push."
exit 0
