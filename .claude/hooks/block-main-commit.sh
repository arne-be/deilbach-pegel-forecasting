#!/usr/bin/env bash
# PreToolUse hook: block git commits on main/master and pushes to main.
# Work must happen in a worktree on a feature branch (see .claude/rules/git-workflow.md).
set -euo pipefail

input=$(cat)
cmd=$(jq -r '.tool_input.command // empty' <<<"$input")
cwd=$(jq -r '.cwd // empty' <<<"$input")

block() {
  echo "Blocked: $1 Create a worktree from origin/main and work on a branch (see .claude/rules/git-workflow.md)." >&2
  exit 2
}

if grep -Eq 'git[[:space:]].*push.*[[:space:]:](main|master)([[:space:]]|$)' <<<"$cmd"; then
  block "pushing to main is not allowed."
fi

grep -Eq 'git[[:space:]]+(-C[[:space:]]+[^[:space:]]+[[:space:]]+)?commit' <<<"$cmd" || exit 0

# Resolve the directory the commit runs in: `git -C <dir>`, a leading `cd <dir>`, or the session cwd.
dir=$(sed -nE 's/.*git[[:space:]]+-C[[:space:]]+([^[:space:]]+).*/\1/p' <<<"$cmd")
[ -z "$dir" ] && dir=$(sed -nE 's/^[[:space:]]*cd[[:space:]]+([^[:space:]&;]+).*/\1/p' <<<"$cmd")
dir=${dir:-$cwd}
dir=${dir/#\~/$HOME}
dir=${dir//\"/}
dir=${dir//\'/}
[[ "$dir" = /* ]] || dir="$cwd/$dir"

branch=$(git -C "$dir" branch --show-current 2>/dev/null || true)
if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  block "committing on '$branch' is not allowed."
fi
exit 0
