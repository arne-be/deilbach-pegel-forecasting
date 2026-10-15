---
description: Branching, commit message and pull request rules
---

# Git Workflow

## Worktrees and branches
- **Never commit on `main`.** The main checkout stays on `main`, clean, and is only used to pull. Enforced by `.claude/hooks/block-main-commit.sh` and branch protection on GitHub.
- **All work happens in a git worktree** on its own branch, created from the newest `origin/main`:
  ```
  git fetch origin
  git worktree add -b <type>/<short-description> ../deilbach-pegel-prediction.worktrees/<short-description> origin/main
  ```
  e.g. `feat/hourly-ingest`, `fix/spike-cleaning`, `chore/ci-setup`.
- Before starting work, check `git branch --show-current`. If it says `main`, stop and create a worktree.
- One topic per branch and worktree. Keep branches short-lived.
- Before opening or updating a PR, rebase onto the newest main: `git fetch origin && git rebase origin/main`.
  - Exception: if the PR's docs point to a commit on its own branch (e.g. retired code kept only in history), use `git merge origin/main` for every update of that PR, never a rebase. A rebase rewrites that commit's SHA and breaks the link; the squash merge flattens the merge commit anyway. In the docs, give the SHA and `git fetch origin pull/<n>/head && git show <sha>`, which still works after the branch is deleted.
- After the PR is merged, clean up (see below).

## Commit messages
Use Conventional Commits:

```
<type>(<optional scope>): <short summary in imperative, lower case, no period>

<body: what changed and why, wrapped at ~72 chars>
```

- Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`, `style`.
- Examples:
  - `feat(ingest): fetch hourly levels from upstream gauges`
  - `fix(cleaning): reject single-reading spikes`
  - `chore(deps): pin pandas to 2.2.3`
- The summary says what the commit does; the body says why.
- Small, logical commits; each one leaves the repo in a working state.

## Pull requests
- Every change goes through a PR into `main`.
- PR title uses the same Conventional Commits format (it becomes the squash commit message).
- Description: what changed, why, how it was tested, and what reviewers should look at closely.
- Keep PRs small and focused. Tests and linters must pass before merging.
- Review your own diff before opening the PR: no debug code, stray files or secrets.
- **After opening a PR, start a review subagent** that first loads the skill `ponytail:ponytail` (exact name). It reviews the PR diff read-only and reports findings only, with file:line, a failure scenario and the smallest fix. Fix or answer each finding before asking for a merge.
- **Always squash merge.** Delete the branch after merging.

## Cleanup after merge
Once the PR is merged, run from the main checkout:

```
git worktree remove ../deilbach-pegel-prediction.worktrees/<short-description>
git branch -D <type>/<short-description>
git switch main && git pull
```

- Use `-D` because squash merges leave the branch looking unmerged to git.
- Only clean up after confirming the PR is merged (`gh pr view <number> --json state`). Never remove a worktree with uncommitted changes.
- Run `git worktree prune` to drop entries for worktrees deleted by hand.

## Retrospective after merge
After the cleanup, look back over the work on the PR before moving on:

- What went wrong or took a detour: a correction from the user, a failed command, a check that missed something, a rework after review.
- For each one that could happen again, write it down where it will be found next time: a rule in `.claude/rules/` or `CLAUDE.md` for anything that applies to everyone working on this repo, the agent's memory for personal or machine-specific things. Update an existing rule rather than adding a near duplicate.
- If nothing went wrong, say so and add nothing. Put rule changes in their own small `docs` PR, not in the merged one.
