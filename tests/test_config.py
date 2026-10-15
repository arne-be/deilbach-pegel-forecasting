import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pegel.config import DEFAULT_CONFIG_PATH, ForecastSettings, PegelConfig, load_config


def test_repo_config_is_valid() -> None:
    config = load_config()
    assert config.station(config.forecast.station_id).source == "influx"


def _config_with(path: Path, **changes: object) -> Path:
    data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_descending_category_bounds_are_rejected(tmp_path: Path) -> None:
    categories = [
        {"number": 1, "name": "a", "above_cm": None},
        {"number": 2, "name": "b", "above_cm": 120.0},
        {"number": 3, "name": "c", "above_cm": 100.0},
    ]
    with pytest.raises(ValidationError):
        load_config(_config_with(tmp_path / "pegel.json", categories=categories))


def test_unknown_forecast_station_is_rejected(tmp_path: Path) -> None:
    forecast = {"station_id": "nowhere", "horizon_hours": 48, "summary_horizons_hours": [3]}
    with pytest.raises(ValidationError):
        load_config(_config_with(tmp_path / "pegel.json", forecast=forecast))


def test_unknown_station_lookup_raises() -> None:
    config: PegelConfig = load_config()
    with pytest.raises(KeyError):
        config.station("nowhere")


def test_non_positive_cleaning_setting_is_rejected(tmp_path: Path) -> None:
    cleaning = load_config().cleaning.model_dump() | {"min_deviation_cm": 0}
    with pytest.raises(ValidationError):
        load_config(_config_with(tmp_path / "pegel.json", cleaning=cleaning))


def test_a_model_other_than_persistence_needs_a_model_file() -> None:
    forecast = load_config().forecast.model_dump()
    with pytest.raises(ValidationError, match="model_file"):
        ForecastSettings.model_validate(forecast | {"model": "ridge:change:v2", "model_file": None})
    ridge = forecast | {"model": "ridge:change:v2", "model_file": "models/ridge.json"}
    assert ForecastSettings.model_validate(ridge).model_file == "models/ridge.json"
