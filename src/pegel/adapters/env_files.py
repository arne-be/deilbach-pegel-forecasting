"""Loads local settings from .env and .env.local into the environment. Local runs only.

On AWS, settings come from the Lambda environment and Secrets Manager instead.
"""

import os
import subprocess
from collections.abc import MutableMapping
from pathlib import Path

ENV_FILE_NAMES = (".env", ".env.local")


def main_checkout() -> Path:
    """The main checkout, where the gitignored env files live, also when run from a worktree."""
    common_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(common_dir).parent


def parse_env_file(text: str) -> dict[str, str]:
    """KEY=VALUE lines; values are taken literally, with one pair of surrounding quotes removed."""
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_env_files(directory: Path, environ: MutableMapping[str, str] = os.environ) -> list[Path]:
    """Sets variables from .env, then .env.local, without overriding the real environment.

    The real environment wins so a one-off override (the prod connection string for the
    first backfill) never has to be written into a file. Empty values don't count as set.
    Returns the files that were read.
    """
    merged: dict[str, str] = {}
    loaded = []
    for name in ENV_FILE_NAMES:
        path = directory / name
        if path.is_file():
            merged.update(parse_env_file(path.read_text(encoding="utf-8")))
            loaded.append(path)
    for key, value in merged.items():
        if value and not environ.get(key):
            environ[key] = value
    return loaded
