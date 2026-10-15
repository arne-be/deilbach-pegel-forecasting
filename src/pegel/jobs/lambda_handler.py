"""AWS Lambda entry point for the hourly run. Same code path as `pegel run-hourly`."""

from typing import Any

from pegel.adapters.logging import configure_logging
from pegel.adapters.secrets import load_secrets, secrets_manager
from pegel.config import load_config
from pegel.jobs.cli import run_hourly_from_env


def handler(event: object, context: object) -> dict[str, Any]:
    """Runs the hourly job. Any error propagates, so Lambda marks the invocation failed."""
    configure_logging()
    load_secrets(secrets_manager())
    forecast = run_hourly_from_env(load_config())
    return {
        "model": forecast.model,
        "issued_at": forecast.issued_at.isoformat(),
        "newest_observation_at": forecast.newest_observation_at.isoformat(),
    }
