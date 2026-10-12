---
description: Universal code style and design principles for the entire project
---

# Code Style

- **KISS.** Choose the simplest solution that works. No abstractions until a concrete need exists.
- **YAGNI.** Build what the current task needs, not what might be needed later.
- **DRY, within reason.** Keep each fact in one place. Don't abstract two similar lines; wait for the third.
- Functions should do one thing. If you need the word "and" to describe it, split it.
- Keep data fetching, cleaning, modelling, storage and presentation in separate modules.
- Pure core, thin edges: keep logic in pure functions; put I/O (databases, APIs, files, clock) at the edges and pass it in.
- Name variables after what they contain, functions after what they do. Don't abbreviate.
- Use early returns over nested conditionals.
- Use type hints for all function signatures.
- Comments explain *why*, not *what*. No commented-out code — delete it, git remembers.
- Don't leave `TODO`s without context; say what is missing and why.
- Handle errors explicitly. Don't swallow exceptions or fall back silently to defaults; log with context.
- Validate inputs at system boundaries.
- Environment-specific values come from config or environment variables, not constants in code.
- Keep files under 300 lines. If a file is growing, extract a module.
- Imports go at the top, grouped: stdlib, external packages, internal modules.
- Pin dependencies. Add a library only when it clearly saves work. Add it with `uv add` (or `pnpm add`), then pin the exact version that resolved, not the newest one on the registry: a minimum package age policy can block the newest release.
- Don't mix refactors with feature work in one commit.
- Update `README.md` and `.claude/` when behaviour, setup or conventions change.
