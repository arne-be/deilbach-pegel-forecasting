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
  e.g. `feat/hourly-ingest`, `fix/negative-level-cleaning`, `chore/ci-setup`.
- Before starting work, check `git branch --show-current`. If it says `main`, stop and create a worktree.
- One topic per branch and worktree. Keep branches short-lived.
- Before opening or updating a PR, rebase onto the newest main: `git fetch origin && git rebase origin/main`.
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
  - `fix(cleaning): keep negative levels`
  - `chore(deps): pin pandas to 2.2.3`
- The summary says what the commit does; the body says why.
- Small, logical commits; each one leaves the repo in a working state.

## Pull requests
- Every change goes through a PR into `main`.
- PR title uses the same Conventional Commits format (it becomes the squash commit message).
- Description: what changed, why, how it was tested, and what reviewers should look at closely.
- Keep PRs small and focused. Tests and linters must pass before merging.
- Review your own diff before opening the PR: no debug code, stray files or secrets.
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
