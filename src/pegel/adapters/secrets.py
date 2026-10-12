"""Loads settings from AWS Secrets Manager into the environment. Lambda only.

The secret names come from environment variables set by OpenTofu. Locally, settings come
from .env files instead (see env_files.py).
"""

import json
import os
from collections.abc import Callable, MutableMapping
from pathlib import Path

import boto3

# Returns the string value of the secret with this name.
GetSecret = Callable[[str], str]

# Environment variable holding the secret name -> variable the secret's value goes into.
_PLAIN_SECRETS = {"JOBS_DATABASE_URL_SECRET_NAME": "JOBS_DATABASE_URL"}
# Same, but the value is written to a file and the variable gets the file's path.
_FILE_SECRETS = {
    "INFLUX_CLIENT_CERT_SECRET_NAME": ("INFLUX_CLIENT_CERT", "influx-client.crt"),
    "INFLUX_CLIENT_KEY_SECRET_NAME": ("INFLUX_CLIENT_KEY", "influx-client.key"),
}
# A JSON object of variables, e.g. {"INFLUX_URL": ..., "INFLUX_PASSWORD": ...}.
_JSON_SECRETS = ("INFLUX_SECRET_NAME",)


def secrets_manager() -> GetSecret:
    client = boto3.client("secretsmanager")

    def get_secret(name: str) -> str:
        return str(client.get_secret_value(SecretId=name)["SecretString"])

    return get_secret


def load_secrets(
    get_secret: GetSecret,
    files_directory: Path = Path("/tmp"),  # the only writable place on Lambda
    environ: MutableMapping[str, str] = os.environ,
) -> None:
    """Sets variables from the secrets named in `environ`, without overriding set ones.

    Errors name the secret or variable, never a value.
    """
    for name_variable, target in _PLAIN_SECRETS.items():
        if not environ.get(target):
            environ[target] = get_secret(_secret_name(environ, name_variable))
    for name_variable, (target, file_name) in _FILE_SECRETS.items():
        if not environ.get(target):
            path = files_directory / file_name
            _write_private(path, get_secret(_secret_name(environ, name_variable)))
            environ[target] = str(path)
    for name_variable in _JSON_SECRETS:
        secret_name = _secret_name(environ, name_variable)
        for key, value in _parse_json_secret(secret_name, get_secret(secret_name)).items():
            if not environ.get(key):
                environ[key] = value


def _secret_name(environ: MutableMapping[str, str], name_variable: str) -> str:
    name = environ.get(name_variable)
    if not name:
        raise ValueError(f"missing environment variable: {name_variable}")
    return name


def _parse_json_secret(secret_name: str, text: str) -> dict[str, str]:
    try:
        values = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(f"secret {secret_name} is not valid JSON") from None
    if not isinstance(values, dict) or not all(isinstance(value, str) for value in values.values()):
        raise ValueError(f"secret {secret_name} must be a JSON object of strings")
    return values


def _write_private(path: Path, text: str) -> None:
    """Writes a file only the owner can read; the key must never be readable by others."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(text)
    path.chmod(0o600)
