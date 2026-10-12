#!/usr/bin/env bash
# Publish private main to the public repo (drorjac/OpenMesh), minus PRIVATE_PATHS.
#
# One-way: private main -> one new commit on public/main. Never merge public back.
# Default is a dry run (builds the commit, shows the diff); pass --push to publish.
#
#   scripts/sync_public.sh          # preview
#   scripts/sync_public.sh --push   # publish
set -euo pipefail

# Everything that must never reach the public repo. Keep this list in sync with
# new research code; this script is excluded too.
PRIVATE_PATHS=(
  methods
  dataset/meta/paper
  src/analysis/paper_snow_utils.py
  src/analysis/paper_viz_utils.py
  src/analysis/notebooks/nycmesh_weather_analysis.ipynb
  src/analysis/notebooks/paper_pws_frozen_precip.ipynb
  scripts/sync_public.sh
)
# Strings that suggest a public file still points at private code.
LEAK_PATTERN='methods/|methods/cml_baseline|cml_rainrate|cml_analysis|cml_classifier|RESEARCH_NOTES|paper_snow_utils|paper_viz_utils'

PUSH=0
[[ "${1:-}" == "--push" ]] && PUSH=1

cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == "main" ]] || { echo "Run from main."; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "Working tree not clean; commit first."; exit 1; }

git fetch -q public
git fetch -q origin
[[ "$(git rev-parse main)" == "$(git rev-parse origin/main)" ]] \
  || echo "WARNING: main differs from origin/main (push private first?)"

# Build the public tree in a throwaway index, without touching the work tree.
export GIT_INDEX_FILE
GIT_INDEX_FILE="$(mktemp)"
trap 'rm -f "$GIT_INDEX_FILE"' EXIT
git read-tree main
git rm -r -q --cached --ignore-unmatch -- "${PRIVATE_PATHS[@]}"
TREE="$(git write-tree)"

if [[ "$TREE" == "$(git rev-parse 'public/main^{tree}')" ]]; then
  echo "Public is already up to date."
  exit 0
fi

# Safety checks on the tree about to be published.
for p in "${PRIVATE_PATHS[@]}"; do
  if git ls-tree -r --name-only "$TREE" -- "$p" | grep -q .; then
    echo "ABORT: private path still in tree: $p"; exit 1
  fi
done
LEAKS="$(git grep -n -I -E "$LEAK_PATTERN" "$TREE" -- . || true)"
if [[ -n "$LEAKS" ]]; then
  echo "ABORT: public files reference private code:"
  echo "$LEAKS" | sed "s/^$TREE://" | cut -c1-160
  exit 1
fi

MSG="Sync from private: $(git log -1 --format=%s main)"
COMMIT="$(git commit-tree "$TREE" -p public/main -m "$MSG")"

echo "== Changes going public (public/main -> $COMMIT) =="
git diff --stat public/main "$COMMIT"

if (( PUSH )); then
  git push public "$COMMIT:refs/heads/main"
  echo "Published."
else
  echo
  echo "Dry run. Re-run with --push to publish."
fi
