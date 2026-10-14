import pandas as pd
import pytest

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.crossings import (
    HOURS_PER_MONTH,
    crossing_warnings,
    false_alarms,
    forecast_crossings,
    observed_crossings,
)
from pegel.evaluation.score import warning_thresholds

START = pd.Timestamp("2024-10-01T00:30Z")
HOURS = 60
LEADS = 6
CALM = 50.0


def _at(hour: int) -> pd.Timestamp:
    return START + pd.Timedelta(hours=hour)


def _observed(changes: dict[int, float]) -> pd.Series:
    levels = [changes.get(hour, CALM) for hour in range(HOURS)]
    return pd.Series(levels, index=pd.date_range(START, periods=HOURS, freq="h"))


def _predictions(warnings: dict[tuple[int, int], float]) -> pd.DataFrame:
    """A calm forecast from every hour, except the (issue hour, lead) values given."""
    rows = [
        {
            contract.ISSUED_AT: _at(hour),
            "lead": lead,
            "model": "m",
            "prediction": warnings.get((hour, lead), CALM),
        }
        for hour in range(HOURS)
        for lead in range(1, LEADS + 1)
    ]
    return pd.DataFrame(rows)


def _readings(observed: pd.Series) -> pd.DataFrame:
    """The last reading at each issue time: the observed level, read just then."""
    return pd.DataFrame(
        {contract.KD_LAST_CM: observed, contract.KD_LAST_AT: observed.index}, index=observed.index
    )


def _false_alarm_count(predictions: pd.DataFrame) -> int:
    calm = _observed({})
    return int(false_alarms(predictions, calm, _readings(calm), [95])["count"].iloc[0])


def _rise() -> pd.Series:
    """Crosses 95 cm at hour 30 and 145 cm at hour 33."""
    return _observed({30: 100, 31: 110, 32: 130, 33: 150, 34: 120})


def test_thresholds_are_the_flood_level_and_every_category() -> None:
    assert warning_thresholds(load_config()) == [95, 145, 165, 185, 225]


def test_a_warning_4_hours_ahead_is_a_hit_at_3_hours_and_a_miss_at_6() -> None:
    table = crossing_warnings(_predictions({(26, 4): 100}), _rise(), _readings(_rise()), [95])
    row = table.iloc[0]
    assert (row["crossing_at"], row["first_warning_at"]) == (_at(30), _at(26))
    assert row["warning_hours"] == 4
    assert (bool(row["hit_3h"]), bool(row["hit_6h"])) == (True, False)


def test_a_forecast_issued_after_the_crossing_does_not_count() -> None:
    observed = _observed({30: 100})
    table = crossing_warnings(_predictions({(31, 1): 100}), observed, _readings(observed), [95])
    assert pd.isna(table["warning_hours"].iloc[0])
    assert not table["hit_3h"].iloc[0]


def test_a_re_crossing_within_a_day_is_left_out() -> None:
    observed = _observed({10: 100, 20: 100})
    table = crossing_warnings(_predictions({}), observed, _readings(observed), [95])
    assert table["crossing_at"].tolist() == [_at(10)]


def test_a_higher_threshold_later_in_the_flood_gets_its_own_warning() -> None:
    table = crossing_warnings(
        _predictions({(28, 2): 100, (28, 5): 150}), _rise(), _readings(_rise()), [95, 145]
    )
    rows = table.set_index("threshold_cm")
    assert rows.loc[95, "warning_hours"] == 2
    assert rows.loc[145, "crossing_at"] == _at(33)
    assert rows.loc[145, "warning_hours"] == 5


def test_a_persistent_false_warning_counts_once() -> None:
    persistent = {(hour, LEADS): 100.0 for hour in range(10, 21)}
    table = false_alarms(
        _predictions({**persistent, (40, 1): 100}), _observed({}), _readings(_observed({})), [95]
    )
    assert table["count"].iloc[0] == 2
    assert table["per_month"].iloc[0] == pytest.approx(2 / (HOURS / HOURS_PER_MONTH))


def test_a_forecast_crossing_within_6_hours_of_an_observed_one_is_no_false_alarm() -> None:
    six_early = {(20, 4): 100.0}
    seven_early = {(20, 3): 100.0}
    assert (
        false_alarms(_predictions(six_early), _rise(), _readings(_rise()), [95])["count"].iloc[0]
        == 0
    )
    assert (
        false_alarms(_predictions(seven_early), _rise(), _readings(_rise()), [95])["count"].iloc[0]
        == 1
    )


def test_a_warning_that_flickers_off_for_an_hour_counts_twice() -> None:
    flicker = {(hour, LEADS): 100.0 for hour in [10, 11, 12, 14, 15, 16]}
    assert _false_alarm_count(_predictions(flicker)) == 2


def test_a_missing_issue_hour_breaks_a_run() -> None:
    predictions = _predictions({(hour, LEADS): 100.0 for hour in range(10, 21)})
    assert _false_alarm_count(predictions[predictions[contract.ISSUED_AT] != _at(15)]) == 2


def test_no_forecast_crossing_without_a_fresh_last_reading() -> None:
    calm = _observed({})
    predictions = _predictions({(10, LEADS): 100.0, (20, LEADS): 100.0, (30, LEADS): 100.0})
    readings = _readings(calm)
    readings.loc[_at(10), contract.KD_LAST_CM] = float("nan")
    readings.loc[_at(20), contract.KD_LAST_AT] = _at(16)
    readings.loc[_at(30), contract.KD_LAST_AT] = _at(27)
    warned = forecast_crossings(predictions, readings, 95)
    assert warned[contract.ISSUED_AT].tolist() == [_at(30)]


def test_a_gap_moves_the_crossing_to_the_first_hour_after_it() -> None:
    observed = _observed({28: float("nan"), 29: float("nan"), 30: 100})
    table = crossing_warnings(_predictions({(25, 4): 100}), observed, _readings(observed), [95])
    assert table["crossing_at"].tolist() == [_at(30)]
    assert table["warning_hours"].iloc[0] == 5


def test_a_gap_before_an_above_hour_within_a_day_is_a_re_crossing() -> None:
    observed = _observed({10: 100, 20: float("nan"), 21: 100})
    crossings = observed_crossings(observed, 95)
    assert crossings["crossing_at"].tolist() == [_at(10), _at(21)]
    assert crossings["re_crossing"].tolist() == [False, True]
