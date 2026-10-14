import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
from eval_factory import radar_areas

from pegel.core.issue_inputs import (
    build_rows,
    forecast_frame,
    hourly_windows,
    icon_by_lead,
    issue_times,
    newest_known,
    observed_frame,
    targets_by_lead,
)
from pegel.core.rain_forecast import archive_run_at
from pegel.core.schedule import scheduled_available_at
from pegel.core.series import InputForecastValue, SeriesValue
from pegel.evaluation import contract

HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
T = datetime(2025, 3, 30, 12, 30, tzinfo=UTC)
TOLERANCE = pd.Timedelta(minutes=10)


def levels(*readings: tuple[datetime, float, datetime | None]) -> pd.DataFrame:
    """(valid_at, value, available_at); None means known right away."""
    return observed_frame(
        [SeriesValue("x", at, value, known or at) for at, value, known in readings]
    )


def at(*moments: datetime) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(list(moments))


def test_issue_times_are_hourly_in_utc_across_the_dst_switch() -> None:
    times = issue_times(date(2025, 3, 30), date(2025, 3, 31), 30)
    assert len(times) == 48
    assert set(times.diff()[1:]) == {pd.Timedelta(hours=1)}
    assert times[0] == pd.Timestamp("2025-03-30T00:30Z")


def test_newest_known_ignores_a_value_known_only_after_the_issue_time() -> None:
    frame = levels((T - 20 * MINUTE, 50.0, None), (T - 5 * MINUTE, 99.0, T + HOUR))
    last = newest_known(frame, at(T, T + HOUR))
    assert last["value"].tolist() == [50.0, 99.0]
    assert last["valid_at"][0] == pd.Timestamp(T - 20 * MINUTE)


def test_newest_known_without_any_value_is_missing() -> None:
    last = newest_known(levels((T, 1.0, T + HOUR)), at(T))
    assert math.isnan(last["value"][0])
    assert pd.isna(last["valid_at"][0])


def test_lag_k_is_the_newest_known_value_in_its_hour() -> None:
    frame = levels(
        (T - 2 * HOUR - 40 * MINUTE, 1.0, None),
        (T - 2 * HOUR - 10 * MINUTE, 2.0, None),
        (T - 3 * HOUR, 3.0, None),
        (T - 5 * MINUTE, 9.0, T + HOUR),
    )
    windows = hourly_windows(frame, at(T, T + HOUR), 5)
    # Lag 0 is empty at T: its only value is known an hour later. Lag 1 and 4 are gaps.
    assert np.isnan(windows[0, [0, 1, 4]]).all()
    assert windows[0, 2] == 2.0
    assert windows[0, 3] == 3.0
    # One hour later the late value is known and has moved to lag 1.
    assert windows[1, 1] == 9.0
    assert windows[1, 3] == 2.0


def icon(run_at: datetime, valid_at: datetime, value: float, known: datetime) -> InputForecastValue:
    return InputForecastValue("icon", run_at, valid_at, value, known)


def archive_day1(valid_hours: list[datetime]) -> list[InputForecastValue]:
    values = []
    for valid_at in valid_hours:
        run_at = archive_run_at(valid_at, 1)
        known = scheduled_available_at(run_at, timedelta(minutes=120), 30)
        values.append(icon(run_at, valid_at, 0.5, known))
    return values


def test_archive_only_gives_leads_of_25_to_27_hours() -> None:
    issued = at(*(T + hour * HOUR for hour in range(6)))
    first_hour = T - 30 * MINUTE
    valid_hours = [first_hour + hour * HOUR for hour in range(30)]
    values, leads = icon_by_lead(forecast_frame(archive_day1(valid_hours)), issued, 24)
    assert not np.isnan(values).any()
    assert set(leads.ravel()) <= {25.0, 26.0, 27.0}


def test_the_newest_known_run_wins_over_the_archive() -> None:
    first_hour = T - 30 * MINUTE
    valid_hours = [first_hour + hour * HOUR for hour in range(24)]
    live_run = datetime(2025, 3, 30, 9, tzinfo=UTC)
    late_run = datetime(2025, 3, 30, 12, tzinfo=UTC)
    live = [icon(live_run, valid, 2.0, T) for valid in valid_hours if valid > live_run]
    not_yet = [icon(late_run, valid, 7.0, T + HOUR) for valid in valid_hours if valid > late_run]
    frame = forecast_frame(archive_day1(valid_hours) + live + not_yet)
    values, leads = icon_by_lead(frame, at(T), 24)
    assert (values[0] == 2.0).all()
    # Column 1 is the hour ending at 12:00, from the 09:00 run.
    assert leads[0, 0] == 3.0
    assert leads[0, 23] == 26.0


def test_target_is_the_nearest_reading_within_the_tolerance() -> None:
    target_1 = T + 52 * MINUTE  # 13:22
    frame = levels(
        (target_1 - 4 * MINUTE, 1.0, None),
        (target_1 + 3 * MINUTE, 2.0, T + 30 * HOUR),
        (target_1 + HOUR + 10 * MINUTE, 3.0, None),
        (target_1 + 2 * HOUR + 11 * MINUTE, 4.0, None),
    )
    targets = targets_by_lead(frame, at(T), 4, TOLERANCE)
    # Targets ignore available_at; 10 minutes off still counts, 11 don't; lead 4 is a gap.
    assert targets[0, 0] == 2.0
    assert targets[0, 1] == 3.0
    assert np.isnan(targets[0, 2:]).all()


def test_rows_have_the_contract_columns_and_the_30_day_base() -> None:
    cleaned = levels(*((T - hour * HOUR, float(hour % 5), None) for hour in range(30 * 24)))
    empty = levels()
    no_forecasts = forecast_frame([])
    areas = radar_areas()
    rows = build_rows(
        at(T),
        "kupferdreh",
        cleaned,
        {"langenberg": empty, "nierenhof": empty},
        dict.fromkeys(areas, empty),
        no_forecasts,
        no_forecasts,
        24,
        TOLERANCE,
    )
    assert list(rows.columns) == contract.dataset_columns(areas, 24)
    assert rows[contract.KD_BASE_30D_CM][0] == 2.0
    assert rows[contract.KD_LAST_CM][0] == 0.0
    assert rows["kd_lag_1"][0] == 1.0
