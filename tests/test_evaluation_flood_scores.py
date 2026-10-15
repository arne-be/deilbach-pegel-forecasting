import numpy as np
import pandas as pd

from pegel.evaluation import contract
from pegel.evaluation.events import FLOOD_EVENT_COLUMNS
from pegel.evaluation.flood_scores import false_alarms, flood_peaks, scored_events

START = pd.Timestamp("2024-10-01T00:30Z")
LEADS = 24
BASE_CM = 50.0
HIGH_WATER_CM = 75.0


def _hour(hour: int) -> pd.Timestamp:
    return START + pd.Timedelta(hours=hour)


def _event(start: int, end: int, peak_at: int, peak_cm: float = 100.0) -> dict[str, object]:
    return {
        "start": _hour(start),
        "end": _hour(end),
        "pre_event_cm": BASE_CM,
        "peak_cm": peak_cm,
        "peak_at": _hour(peak_at),
    }


def _floods(*events: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(list(events), columns=FLOOD_EVENT_COLUMNS)


def _forecast(issued_hour: int, peaks: dict[int, float], model: str = "m") -> pd.DataFrame:
    """A flat BASE_CM forecast with the given values at the given leads."""
    values = [peaks.get(lead, BASE_CM) for lead in range(1, LEADS + 1)]
    return pd.DataFrame(
        {
            contract.ISSUED_AT: _hour(issued_hour),
            "lead": range(1, LEADS + 1),
            "model": model,
            "fold": "F1",
            "prediction": values,
        }
    )


def _peaks(floods: pd.DataFrame, *forecasts: pd.DataFrame) -> pd.DataFrame:
    predictions = pd.concat(forecasts, ignore_index=True)
    return flood_peaks(predictions, floods, scored_events(floods, {"F1"}), LEADS)


def _row(peaks: pd.DataFrame, lead: int) -> pd.Series:
    return peaks[peaks["lead_hours"] == lead].iloc[0]


# One event from hour 10 to 60, peaking at 100 cm at hour 40, 50 cm above the pre-event level.
EVENT = _event(10, 60, 40)


def test_size_and_timing_against_the_rise() -> None:
    # Issued 6 h before the peak, peaking at 90 cm 2 h late: 80 % of the rise.
    row = _row(_peaks(_floods(EVENT), _forecast(34, {8: 90.0})), 6)
    assert row["size"] == 0.8
    assert row["timing_hours"] == 2
    assert row["forecast_peak_at"] == _hour(42)
    assert row["predicted"] and not row["timing_at_least"]


def test_half_the_rise_is_not_predicted() -> None:
    assert not _row(_peaks(_floods(EVENT), _forecast(34, {6: 75.0})), 6)["predicted"]


def test_tied_hours_take_the_first() -> None:
    row = _row(_peaks(_floods(EVENT), _forecast(34, {4: 90.0, 8: 90.0})), 6)
    assert row["timing_hours"] == -2


def test_a_peak_at_the_last_hour_is_at_least_late() -> None:
    row = _row(_peaks(_floods(EVENT), _forecast(34, {24: 90.0})), 6)
    assert row["timing_hours"] == 18
    assert row["timing_at_least"]


def test_a_missing_forecast_gets_a_row_without_values() -> None:
    peaks = _peaks(_floods(EVENT), _forecast(34, {8: 90.0}))
    assert sorted(peaks["lead_hours"]) == [1, 3, 6, 12, 24]
    row = _row(peaks, 12)
    assert np.isnan(row["size"])
    assert pd.isna(row["predicted"])


def test_a_lead_before_the_previous_event_ends_is_missing() -> None:
    previous, current = _event(0, 20, 5), _event(22, 60, 40)
    # Issued at hour 16, before the previous event ends at hour 20.
    peaks = _peaks(_floods(previous, current), _forecast(16, {24: 90.0}), _forecast(28, {12: 90.0}))
    current_peaks = peaks[peaks["event"] == 2]
    assert np.isnan(_row(current_peaks, 24)["size"])
    assert _row(current_peaks, 12)["predicted"]


def test_events_outside_the_scored_folds_are_left_out_and_numbered_by_peak() -> None:
    training = _event(-500, -400, -450)
    events = scored_events(_floods(EVENT, training), {"F1"})
    assert events[["event", "fold", "peak_at"]].values.tolist() == [[1, "F1", _hour(40)]]


def _dataset(hours: int, last_age_hours: int = 0) -> pd.DataFrame:
    issued_at = pd.date_range(START, periods=hours, freq="h")
    return pd.DataFrame(
        {
            contract.ISSUED_AT: issued_at,
            contract.KD_LAST_CM: BASE_CM,
            contract.KD_LAST_AT: issued_at - pd.Timedelta(hours=last_age_hours),
        }
    )


def _alarm_count(floods: pd.DataFrame, alarm_hours: list[int], last_age_hours: int = 0) -> int:
    """False alarms of one model that forecasts 90 cm at the given issue hours, calm otherwise."""
    hours = 200
    forecasts = [_forecast(h, {6: 90.0} if h in alarm_hours else {}) for h in range(hours)]
    predictions = pd.concat(forecasts, ignore_index=True)
    dataset = _dataset(hours, last_age_hours)
    table = false_alarms(predictions, dataset, floods, HIGH_WATER_CM, LEADS)
    return int(table["count"].iloc[0])


def test_a_run_of_false_alarms_counts_once() -> None:
    assert _alarm_count(_floods(), [100, 101, 102, 150]) == 2


def test_a_skipped_hour_inside_a_run_does_not_split_it() -> None:
    hours = 200
    forecasts = [_forecast(h, {6: 90.0} if h in (100, 101, 103) else {}) for h in range(hours)]
    dataset = _dataset(hours)
    dataset.loc[102, contract.KD_LAST_AT] = _hour(102) - pd.Timedelta(hours=4)
    predictions = pd.concat(forecasts, ignore_index=True)
    table = false_alarms(predictions, dataset, _floods(), HIGH_WATER_CM, LEADS)
    assert int(table["count"].iloc[0]) == 1


def test_an_alarm_needs_high_water_and_a_rise_of_15_cm() -> None:
    hours = 10
    dataset = _dataset(hours)
    dataset[contract.KD_LAST_CM] = 70.0

    def count(peak_cm: float) -> int:
        predictions = _forecast(5, {6: peak_cm})
        table = false_alarms(predictions, dataset, _floods(), HIGH_WATER_CM, LEADS)
        return int(table["count"].iloc[0])

    assert count(85.0) == 1  # above 75 cm, exactly 15 cm above the last level
    assert count(84.9) == 0  # less than 15 cm above
    dataset[contract.KD_LAST_CM] = 59.0
    assert count(75.0) == 0  # 16 cm above, but not above 75 cm


def test_an_alarm_uses_the_highest_known_value() -> None:
    predictions = _forecast(5, {6: 90.0})
    predictions.loc[predictions["lead"] == 1, "prediction"] = np.nan
    table = false_alarms(predictions, _dataset(10), _floods(), HIGH_WATER_CM, LEADS)
    assert int(table["count"].iloc[0]) == 1


def test_a_forecast_with_a_missing_lead_is_missing_in_peaks() -> None:
    forecast = _forecast(34, {8: 90.0})
    forecast.loc[forecast["lead"] == 20, "prediction"] = np.nan
    row = _row(_peaks(_floods(EVENT), forecast), 6)
    assert np.isnan(row["size"])
    assert pd.isna(row["predicted"])


def test_no_events_give_empty_tables() -> None:
    floods = _floods()
    assert scored_events(floods, {"F1"}).empty
    assert _peaks(floods, _forecast(5, {})).empty


def test_a_stale_last_level_is_skipped() -> None:
    assert _alarm_count(_floods(), [100], last_age_hours=4) == 0
    assert _alarm_count(_floods(), [100], last_age_hours=3) == 1


def test_an_alarm_during_or_just_before_an_event_is_not_false() -> None:
    # During the event (hours 10 to 60) and 24 h before its start at hour 120.
    floods = _floods(EVENT, _event(120, 140, 130))
    assert _alarm_count(floods, [30, 96]) == 0
    assert _alarm_count(floods, [95]) == 1


def test_false_alarms_per_month_of_issue_times() -> None:
    predictions = pd.concat([_forecast(h, {6: 90.0}) for h in range(2)], ignore_index=True)
    table = false_alarms(predictions, _dataset(2), _floods(), HIGH_WATER_CM, LEADS)
    assert table[["model", "count"]].values.tolist() == [["m", 1]]
    assert table["per_month"].iloc[0] == 1 / table["months"].iloc[0]
