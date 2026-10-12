import json
import stat
from pathlib import Path

import pytest

from pegel.adapters.secrets import load_secrets

SECRET_NAMES = {
    "INFLUX_SECRET_NAME": "deilbach-pegel/influx",
    "INFLUX_CLIENT_CERT_SECRET_NAME": "deilbach-pegel/influx-client-cert",
    "INFLUX_CLIENT_KEY_SECRET_NAME": "deilbach-pegel/influx-client-key",
    "JOBS_DATABASE_URL_SECRET_NAME": "deilbach-pegel/jobs-database-url",
}
SECRETS = {
    "deilbach-pegel/influx": json.dumps(
        {"INFLUX_URL": "https://influx.test", "INFLUX_USERNAME": "u", "INFLUX_PASSWORD": "p"}
    ),
    "deilbach-pegel/influx-client-cert": "CERT PEM",
    "deilbach-pegel/influx-client-key": "KEY PEM",
    "deilbach-pegel/jobs-database-url": "postgresql://jobs@db.test/pegel\n",
}


def test_secrets_become_variables_and_files(tmp_path: Path) -> None:
    environ = dict(SECRET_NAMES)
    load_secrets(SECRETS.__getitem__, tmp_path, environ)
    assert environ["INFLUX_URL"] == "https://influx.test"
    assert environ["INFLUX_PASSWORD"] == "p"
    assert environ["JOBS_DATABASE_URL"] == "postgresql://jobs@db.test/pegel"
    assert Path(environ["INFLUX_CLIENT_CERT"]).read_text() == "CERT PEM"
    key = Path(environ["INFLUX_CLIENT_KEY"])
    assert key.read_text() == "KEY PEM"
    assert stat.S_IMODE(key.stat().st_mode) == 0o600


def test_changed_secrets_replace_values_from_an_earlier_run(tmp_path: Path) -> None:
    environ = dict(SECRET_NAMES)
    load_secrets(SECRETS.__getitem__, tmp_path, environ)
    changed = {**SECRETS, "deilbach-pegel/jobs-database-url": "postgresql://new@db.test/pegel"}
    load_secrets(changed.__getitem__, tmp_path, environ)
    assert environ["JOBS_DATABASE_URL"] == "postgresql://new@db.test/pegel"


def test_missing_secret_name_is_named(tmp_path: Path) -> None:
    environ = {k: v for k, v in SECRET_NAMES.items() if k != "INFLUX_SECRET_NAME"}
    with pytest.raises(ValueError, match="INFLUX_SECRET_NAME"):
        load_secrets(SECRETS.__getitem__, tmp_path, environ)


def test_invalid_json_secret_does_not_leak_its_value(tmp_path: Path) -> None:
    secrets = {**SECRETS, "deilbach-pegel/influx": "not json hunter2"}
    with pytest.raises(ValueError, match="deilbach-pegel/influx") as error:
        load_secrets(secrets.__getitem__, tmp_path, dict(SECRET_NAMES))
    assert "hunter2" not in str(error.value)
