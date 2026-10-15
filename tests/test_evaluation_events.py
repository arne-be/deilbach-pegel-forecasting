from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.events import (
    alarms,
    episodes,
    flood_events,
    lag_check,
    observed_levels,
    peak_errors,
)
from pegel.evaluation.metrics import PERSISTENCE
from pegel.evaluation.score import alarm_thresholds, main

START = pd.Timestamp("2024-10-01T00:30Z")
LEADS = 6


def _hours(levels: list[float]) -> pd.Series:
    return pd.Series(levels, index=pd.date_range(START, periods=len(levels), freq="h"))


def _dataset(observed: pd.Series) -> pd.DataFrame:
    """One issue time per observed hour; the target for lead k is the level k hours later."""
    dataset = pd.DataFrame({contract.ISSUED_AT: observed.index})
    dataset[contract.KD_LAST_CM] = observed.to_numpy()
    dataset[contract.KD_LAST_AT] = observed.index
    for lead in range(1, LEADS + 1):
        later = observed.shift(-lead).to_numpy()
        dataset[f"target_{lead}"] = later
    return dataset


def _predictions(
    observed: pd.Series, models: dict[str, Callable[[pd.Timestamp, int], float]]
) -> pd.DataFrame:
    rows = [
        {
            contract.ISSUED_AT: issued_at,
            "lead": lead,
            "model": name,
            "fold": "F1",
            "prediction": forecast(issued_at, lead),
            "target": observed.get(issued_at + pd.Timedelta(hours=lead), np.nan),
        }
        for name, forecast in models.items()
        for issued_at in observed.index
        for lead in range(1, LEADS + 1)
    ]
    return pd.DataFrame(rows)


def _at(observed: pd.Series, hours_back: int = 0) -> Callable[[pd.Timestamp, int], float]:
    """A model that forecasts the observed level `hours_back` before the target time."""

    def forecast(issued_at: pd.Timestamp, lead: int) -> float:
        when = issued_at + pd.Timedelta(hours=lead - hours_back)
        return float(observed.get(when, np.nan))

    return forecast


def _persistence(observed: pd.Series) -> Callable[[pd.Timestamp, int], float]:
    return lambda issued_at, lead: float(observed[issued_at])


def test_observed_levels_rebuilds_the_series_from_the_targets() -> None:
    observed = _hours([50.0, 60, 70, 80, 90, 100, 110, 120])
    rebuilt = observed_levels(_dataset(observed), LEADS)
    pd.testing.assert_series_equal(rebuilt, observed[1:], check_names=False, check_freq=False)


def test_peaks_less_than_a_day_apart_are_one_event() -> None:
    levels = [50.0] * 80
    levels[10], levels[20], levels[60] = 100, 110, 120
    floods = episodes(_hours(levels), 95)
    assert floods["peak_cm"].tolist() == [110, 120]
    assert floods["start"].iloc[0] == START + pd.Timedelta(hours=10)
    assert floods["end"].iloc[0] == START + pd.Timedelta(hours=20)


def _rise(levels: list[float], at: int, values: list[float]) -> pd.Series:
    """A base level with a dip to 49 cm just before `values` start at hour `at`."""
    levels[at - 1] = 49
    levels[at : at + len(values)] = values
    return _hours(levels)


def _hour(hour: int) -> pd.Timestamp:
    return START + pd.Timedelta(hours=hour)


def test_flood_event_runs_from_the_low_before_the_rise_back_to_it() -> None:
    floods = flood_events(_rise([50.0] * 60, 30, [70, 90, 100, 80, 60, 53]), 75)
    assert floods.to_dict("records") == [
        {
            "start": _hour(29),
            "end": _hour(35),
            "pre_event_cm": 49,
            "peak_cm": 100,
            "peak_at": _hour(32),
        }
    ]


def test_a_new_rise_before_the_end_joins_the_event() -> None:
    levels = _rise([50.0] * 60, 30, [70, 90, 100, 80, 70, 70, 70, 90, 120, 90, 60, 50])
    floods = flood_events(levels, 75)
    assert floods[["start", "end", "peak_cm"]].values.tolist() == [[_hour(29), _hour(41), 120]]


def test_separate_rises_are_separate_events() -> None:
    levels = [50.0] * 120
    levels[30:34] = [90, 100, 60, 50]
    levels[80:84] = [90, 110, 60, 50]
    floods = flood_events(_hours(levels), 75)
    assert floods["peak_cm"].tolist() == [100, 110]
    assert floods["end"].tolist() == [_hour(33), _hour(83)]


def test_flood_event_ends_when_flat_below_high_water() -> None:
    levels = _rise([50.0] * 30 + [70.0] * 40, 30, [80, 100, 90])
    floods = flood_events(levels, 75)
    # Back at 70 cm from hour 33; 24 hours later it has not fallen.
    assert floods["end"].tolist() == [_hour(57)]


def test_daily_dip_above_high_water_is_no_event() -> None:
    hours = np.arange(24 * 5)
    levels = pd.Series(
        74 + 4 * np.sin(hours * 2 * np.pi / 24), index=_hours([0.0] * hours.size).index
    )
    assert flood_events(levels, 75).empty


def test_hours_without_a_level_are_skipped() -> None:
    base = [50.0] * 60
    base[10] = np.nan
    floods = flood_events(_rise(base, 30, [70, 90, 100, np.nan, np.nan, 53]), 75)
    assert floods[["start", "end", "peak_cm"]].values.tolist() == [[_hour(29), _hour(35), 100]]


def test_hits_misses_and_false_alarms_per_threshold() -> None:
    observed = [50.0] * 100
    observed[10:13] = [100, 150, 100]
    observed[50:53] = [100, 100, 100]
    forecast = [50.0] * 100
    forecast[11:13] = [100, 100]
    forecast[80:82] = [100, 100]
    observed_series = _hours(observed)
    # Lead 1: the forecast issued one hour before each target time.
    predictions = pd.DataFrame(
        {
            contract.ISSUED_AT: pd.date_range(START - pd.Timedelta(hours=1), periods=100, freq="h"),
            "lead": 1,
            "model": "m",
            "prediction": forecast,
        }
    )
    flood_cm, category_2_cm = alarm_thresholds(load_config())
    assert category_2_cm == 145
    table = alarms(predictions, observed_series, (flood_cm, category_2_cm))
    counts = table[["hits", "misses", "false_alarms"]].to_numpy().tolist()
    assert table["threshold_cm"].tolist() == [flood_cm, category_2_cm]
    assert counts == [[1, 1, 1], [0, 1, 0]]


def _rising() -> pd.Series:
    """Calm, a steady rise through 95 cm at hour 30, then calm again."""
    levels = [50.0] * 30 + [100.0, 110.0, 120.0, 110.0] + [50.0] * 30
    return _hours(levels)


def test_peak_errors_by_hours_before_the_peak() -> None:
    observed = _rising()
    predictions = _predictions(
        observed, {"perfect": _at(observed), PERSISTENCE: _persistence(observed)}
    )
    floods = episodes(observed, 95)
    table = peak_errors(predictions, floods)

    def errors(model: str, lead: int) -> list[float]:
        row = table[(table["model"] == model) & (table["lead"] == lead)]
        return row[["height_error_cm", "at_peak_error_cm", "timing_error_hours"]].iloc[0].tolist()

    assert errors("perfect", 4) == [0, 0, 0]
    # Issued 2 hours before the 120 cm peak, persistence holds 100 cm: flat, so no timing.
    height, at_peak, timing = errors(PERSISTENCE, 2)
    assert (height, at_peak) == (-20, -20)
    assert np.isnan(timing)


def test_lag_check_finds_a_known_shift() -> None:
    hours = np.arange(200)
    observed = _hours((80 + 30 * np.sin(hours / 9)).tolist())
    predictions = _predictions(observed, {"late": _at(observed, hours_back=3)})
    table = lag_check(predictions, _dataset(observed), LEADS, high_water_cm=75)
    assert (table["shift_hours"] == 3).all()
    assert table["mae"].max() == pytest.approx(0)


def test_runner_writes_every_table(tmp_path: Path) -> None:
    observed = _rising()
    predictions = _predictions(
        observed, {"perfect": _at(observed), PERSISTENCE: _persistence(observed)}
    )
    dataset = _dataset(observed)
    for lead in range(LEADS + 1, load_config().evaluation.leads_hours + 1):
        dataset[f"target_{lead}"] = np.nan
    predictions.to_parquet(tmp_path / "predictions.parquet")
    dataset.to_parquet(tmp_path / "dataset.parquet")
    main(
        [
            str(tmp_path / "predictions.parquet"),
            str(tmp_path / "dataset.parquet"),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    written = sorted(path.stem for path in (tmp_path / "out").glob("*.csv"))
    assert written == [
        "alarms",
        "bootstrap",
        "crossings",
        "events",
        "false_alarms",
        "lag",
        "peaks",
        "scores",
    ]
    assert len(pd.read_csv(tmp_path / "out" / "events.csv")) == 1
