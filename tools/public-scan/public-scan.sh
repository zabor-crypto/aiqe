#!/usr/bin/env bash
#
# AIQE public sanitisation scan.
#
#     public-scan.sh [<root>]
#
# Scans every text file under <root> against the pattern classes in
# patterns.txt, plus any local-only private literal list if one is present.
# <root> defaults to the repository this script lives in. It may also be a
# single file.
#
# The argument exists because a source tree that scans clean says nothing
# about what a build backend put inside a wheel or an sdist. Packaging is its
# own way to publish a private file, so the extracted artifacts are scanned as
# trees in their own right rather than assumed to inherit the source result.
#
# This is a floor, not a proof. It catches the shapes it was told about.
# Paraphrased private material, an unredacted diagram label, or an asset derived
# from a real screenshot passes every pattern in the list. Human provenance
# review is mandatory and is not replaced by this script.
#
# Exit codes:  0 = clean   1 = findings   2 = scanner could not run

set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
patterns="$here/patterns.txt"

# The scan target. Without an argument it is the repository containing this
# script, which is what the source-tree gate has always scanned.
target="${1:-$here/../..}"
if [ -d "$target" ]; then
  root=$(cd "$target" && pwd)
  scan_one_file=""
elif [ -f "$target" ]; then
  root=$(cd "$(dirname "$target")" && pwd)
  scan_one_file="./$(basename "$target")"
else
  echo "public-scan: no such file or directory: $target" >&2
  exit 2
fi

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
if [ -n "$scan_one_file" ]; then
  # A single named file - the release-proof manifest is scanned this way,
  # because it is generated outside any tree the source scan walks.
  if LC_ALL=C grep -qI . "$scan_one_file" 2>/dev/null; then
    files+=("$scan_one_file")
  fi
fi
while [ -z "$scan_one_file" ] && IFS= read -r -d '' f; do
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
done < <(if [ -z "$scan_one_file" ]; then find . -type f -print0; fi)

if [ "${#files[@]}" -eq 0 ]; then
  echo "public-scan: no text files found under $root" >&2
  exit 2
fi

findings=0
justified=0

# The one place a pattern class is deliberately not applied, and why.
#
# The release-proof manifest's job is to say which commit an artifact was
# built from, so it necessarily contains a bare 40-character object id. The
# GIT_SHA_40 class exists to catch an object id from *another* repository
# reaching public content, and blanket-excluding the file would blind the scan
# to exactly that. So the exception is scoped to one class in one path, and a
# stronger check replaces it there: `tests/test_release_proof.py` asserts that
# every 40-character object id in the manifest is an object that exists in
# this repository. A foreign id fails that test.
#
# The second exception is a pinned GitHub Actions reference. An action pinned
# to a full commit id is the supply-chain control the release workflow is
# required to carry, so the scan would otherwise punish exactly the thing it
# wants. This exception is scoped to one class on one *line shape* rather than
# to a file: the whole line must be a `uses:` pin and nothing else, so a bare
# object id elsewhere in the same workflow is still a finding. The stronger
# check that replaces it is `tests/test_workflow_pinning.py`, which asserts
# that every `uses:` in every workflow is pinned to a 40-character object id,
# carries a version comment, and names a canonical first-party action
# repository - none of which the skipped class was checking.
#
# Nothing else is excepted. A third entry here needs the same treatment: a
# named reason and a check that is stronger than the one being skipped.
#: Files that identify themselves as the release-proof manifest. Recognised by
#: content rather than by path, because the manifest is scanned both in place
#: inside the source tree and as a single named file straight out of a CI job,
#: and a path-shaped rule would silently stop applying in the second case -
#: which is the one where the scan matters most.
manifest_files=""
for f in "${files[@]}"; do
  if LC_ALL=C grep -q '"record_type": *"AIQE_RELEASE_PROOF_MANIFEST"' "$f" 2>/dev/null; then
    manifest_files="${manifest_files}${f}"$'\n'
  fi
done

#: A whole line that is nothing but a pinned action reference:
#:
#:     - uses: owner/repo@<40 hex> # v1.2.3
#:
#: Anchored at both ends on purpose. A line that merely *contains* a pin could
#: carry a foreign object id alongside it, and that is the case this class
#: exists for.
action_pin_line='^[[:space:]]*-?[[:space:]]*uses:[[:space:]]+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}([[:space:]]+#[[:space:]]*[^[:space:]].*)?$'

justified_match() {
  local class="$1" line="$2" file="${2%%:*}" rest content
  [ "$class" = "GIT_SHA_40" ] || return 1

  case $'\n'"$manifest_files" in
    *$'\n'"$file"$'\n'*) return 0 ;;
  esac

  # `path:lineno:content` - drop the path, then the line number.
  rest="${line#*:}"
  content="${rest#*:}"
  if printf '%s' "$content" | LC_ALL=C grep -qE -- "$action_pin_line"; then
    return 0
  fi
  return 1
}

scan_one() {
  local class="$1" regex="$2" hits kept="" skipped=0
  # /dev/null is passed so that grep always prefixes its output with a
  # filename. With a single file it would otherwise omit the prefix, and the
  # exception below - which is scoped to one file - would stop being able to
  # tell which file a match came from. That is the single-file mode the
  # release-proof manifest is scanned in.
  hits=$(LC_ALL=C grep -nEI -i -- "$regex" "${files[@]}" /dev/null 2>/dev/null)
  if [ -n "$hits" ]; then
    while IFS= read -r hit; do
      [ -z "$hit" ] && continue
      if justified_match "$class" "$hit"; then
        skipped=$((skipped + 1))
        continue
      fi
      kept="${kept}${hit}"$'\n'
    done <<< "$hits"
    if [ "$skipped" -gt 0 ]; then
      echo "JUSTIFIED [$class] $skipped match(es) in a path with a recorded exception"
      justified=$((justified + skipped))
    fi
    if [ -n "${kept%$'\n'}" ]; then
      echo "FINDING [$class]"
      printf '%s\n' "${kept%$'\n'}" | sed 's/^/    /'
      echo
      findings=$((findings + 1))
    fi
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

echo "public-scan: root $root"
if [ "$justified" -gt 0 ]; then
  echo "public-scan: $justified match(es) skipped under a recorded, path-scoped exception"
fi
echo "public-scan: scanned ${#files[@]} text files against $(grep -cvE '^(#|$)' "$patterns") pattern classes"

if [ "$findings" -gt 0 ]; then
  echo "public-scan: FAIL - $findings pattern class(es) matched"
  exit 1
fi

echo "public-scan: PASS - no pattern class matched"
echo "public-scan: reminder - machine scan is a floor. Human provenance review is required before any push."
exit 0
