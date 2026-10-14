import math

import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.core.features import (
    icon_cumulative,
    kupferdreh_change,
    last_level_age_hours,
    recent_rise,
    summer_hour_terms,
)
from pegel.evaluation import contract

KD_LAGS = contract.level_lag_columns("kupferdreh")


def _flat_kupferdreh(rows: pd.DataFrame, level: float) -> pd.DataFrame:
    rows = rows.copy()
    rows[[contract.KD_LAST_CM, *KD_LAGS]] = level
    return rows


def test_change_counts_from_the_newest_reading_not_from_lag_0() -> None:
    rows = _flat_kupferdreh(eval_dataset(hours=2), 50.0)
    rows[contract.KD_LAST_CM] = 60.0
    rows[contract.KD_LAST_AT] = rows[contract.ISSUED_AT] - pd.to_timedelta(["10min", "70min"])
    rows.loc[0, "kd_lag_3"] = 52.0
    rows.loc[1, "kd_lag_4"] = 55.0
    assert last_level_age_hours(rows) == pytest.approx([1 / 6, 7 / 6])
    # 10 minutes old pairs with lag 3; 70 minutes old with lag 4.
    np.testing.assert_allclose(kupferdreh_change(rows, 3), [8.0, 5.0])


def test_change_is_nan_when_the_older_lag_is_missing_or_beyond_the_window() -> None:
    rows = _flat_kupferdreh(eval_dataset(hours=2), 50.0)
    rows.loc[0, "kd_lag_3"] = np.nan
    rows[contract.KD_LAST_AT] = rows[contract.ISSUED_AT] - pd.to_timedelta(["10min", "22h"])
    assert np.isnan(kupferdreh_change(rows, 3)).all()


def test_recent_rise_fades_with_the_hours_since_the_peak() -> None:
    rows = _flat_kupferdreh(eval_dataset(hours=3), 40.0)
    # Peak 70 at lag 5 (column 6: about 6 hours ago), trough 30 at lag 20.
    rows.loc[0, "kd_lag_5"] = 70.0
    rows.loc[0, "kd_lag_20"] = 30.0
    # Still rising: the last level is the peak.
    rows.loc[1, contract.KD_LAST_CM] = 55.0
    rows.loc[2, [contract.KD_LAST_CM, *KD_LAGS]] = np.nan
    result = recent_rise(rows, 24.0)
    assert result[0] == pytest.approx(40.0 * math.exp(-6 / 24))
    assert result[1] == pytest.approx(15.0)
    assert np.isnan(result[2])


def test_recent_rise_skips_missing_lags() -> None:
    rows = _flat_kupferdreh(eval_dataset(hours=1), 40.0)
    rows.loc[0, ["kd_lag_0", "kd_lag_1"]] = np.nan
    rows.loc[0, "kd_lag_2"] = 46.0
    assert recent_rise(rows, 6.0)[0] == pytest.approx(6.0 * math.exp(-3 / 6))


def test_icon_cumulative_sums_hours_1_to_k() -> None:
    rows = eval_dataset(hours=1)
    rows[contract.lead_columns(contract.ICON_MEAN, 24)] = 0.5
    np.testing.assert_allclose(icon_cumulative(rows, 24)[0], 0.5 * np.arange(1, 25))


def test_summer_hour_terms_are_zero_in_winter_and_follow_the_hour_in_summer() -> None:
    winter = eval_dataset(first_issue="2025-01-10T05:30Z", hours=1)
    assert not summer_hour_terms(winter).any()
    summer = eval_dataset(first_issue="2025-06-10T05:30Z", hours=1)
    # 06:00 is a quarter of the day: sin 1, cos 0; twice it is half: sin 0, cos -1.
    summer[contract.ISSUED_AT] = pd.Timestamp("2025-06-10T06:00Z")
    np.testing.assert_allclose(summer_hour_terms(summer)[0], [1, 0, 0, -1], atol=1e-12)
