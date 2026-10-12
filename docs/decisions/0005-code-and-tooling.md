# 0005 · Code layout and tooling

- **Status:** accepted
- **Date:** 2026-10-12

## Decisions

**One repo** for Python, website, SQL and OpenTofu. A schema change, the API that uses it and the page that shows it land in one pull request.

**`src/pegel/` split into `core/` and `adapters/`** from the start, plus `api/` and `jobs/`. Core is pure logic without I/O; adapters talk to the outside. This follows our "pure core, thin edges" rule.

**Plain SQL, no ORM.** psycopg 3 for access, plain SQL migrations run by dbmate. We have a few tables and two kinds of query: upserts and time ranges. SQL says that most clearly.

**Python records generated from the schema.** A small script reads the schema after migrating and writes `records.py`. CI fails if the committed file is out of date, so code and schema can't drift. Shapes that aren't a table stay hand-written.

**One shared config file**, `config/pegel.json`, for thresholds, horizons, stations and freshness limits. Python and Astro both read JSON without extra dependencies.

**Tests against a throwaway Postgres container**, never against Neon. Fast, free, and no risk to real data.

**Tooling:**

| Area | Tools |
|---|---|
| Python | Python 3.13, uv, ruff, mypy (strict), pytest, testcontainers |
| Website | pnpm, TypeScript (strict), Biome, Vitest, `astro check` |
| Infrastructure | `tofu fmt`, `tofu validate`, TFLint |
| Tool versions | mise; uv manages Python |

**Logging:** Python's `logging` with a small JSON formatter, no extra library.

## Rejected

- **A generic `modules/` folder.** Longer imports, no extra meaning.
- **Starting flat and splitting later.** We'd rather keep I/O out of the core from day one.
- **SQLAlchemy and Alembic.** Built around models we don't want.
- **sqlc.** Its Python support looked less mature; another tool to learn.
- **A check-only test instead of generated records.** Simpler, but still manual work.
- **YAML or TOML for config.** Needs a parser on one side.
- **Neon branches for tests.** Uses compute hours and needs the network.
- **pyright.** Fine, but mypy has better plugin support, for example for Pydantic.
- **ESLint + Prettier.** Safer for `.astro` files, but two tools. We switch if Biome gets in the way.
- **Browser tests (Playwright).** Not yet; one page doesn't justify them.
- **Trivy security scan.** Skipped for now.
- **Homebrew or asdf for tools.** No per-project versions, or slower.
- **structlog.** Nicer, but one more dependency.
