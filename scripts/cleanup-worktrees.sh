#!/usr/bin/env bash
set -euo pipefail
REPO_BASE="${REPO_BASE_PATH:-/tmp/selva-repos}"
STALE_HOURS="${STALE_HOURS:-24}"

find "$REPO_BASE" -maxdepth 2 -name "_worktrees" -type d 2>/dev/null | while read -r wt_root; do
  repo_dir=$(dirname "$wt_root")
  find "$wt_root" -mindepth 1 -maxdepth 1 -type d -mmin +$((STALE_HOURS * 60)) | while read -r wt; do
    echo "Removing stale worktree: $wt"
    git -C "$repo_dir" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
  done
  git -C "$repo_dir" worktree prune 2>/dev/null || true
done
echo "Worktree cleanup complete"
