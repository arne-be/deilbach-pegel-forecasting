from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset, radar_areas

from pegel.core.features import features, step_features
from pegel.evaluation import contract

LEADS = 24


def test_kupferdreh_inputs_are_passed_through() -> None:
    dataset = eval_dataset()
    result = features(dataset)
    for name in [contract.KD_LAST_CM, "kd_lag_0", "kd_lag_23", contract.KD_BASE_30D_CM]:
        pd.testing.assert_series_equal(result[name], dataset[name])


def test_upstream_lags_stop_at_six_hours_and_changes_match_a_hand_computation() -> None:
    dataset = eval_dataset()
    result = features(dataset)
    assert "lb_lag_6" in result and "lb_lag_7" not in result
    row = dataset.iloc[5]
    assert result["nh_change_1h"].iloc[5] == row["nh_lag_0"] - row["nh_lag_1"]
    assert result["lb_change_3h"].iloc[5] == row["lb_lag_0"] - row["lb_lag_3"]


def test_radar_sums_cover_the_newest_hours_of_each_area() -> None:
    dataset = eval_dataset()
    result = features(dataset)
    row = dataset.iloc[0]
    expected = sum(row[f"radar_middle_lag_{k}"] for k in range(6))
    assert result["radar_middle_sum_6h"].iloc[0] == pytest.approx(expected)
    week = sum(row[f"radar_catchment_lag_{k}"] for k in range(168))
    assert result["radar_catchment_sum_168h"].iloc[0] == pytest.approx(week)
    assert {f"radar_{area}_sum_1h" for area in radar_areas()} <= set(result.columns)


def test_a_missing_radar_hour_makes_only_the_windows_that_contain_it_nan() -> None:
    dataset = eval_dataset()
    dataset.loc[0, "radar_lower_lag_5"] = np.nan
    result = features(dataset).iloc[0]
    assert not np.isnan(result["radar_lower_sum_3h"])
    assert np.isnan(result["radar_lower_sum_6h"])
    assert np.isnan(result["radar_lower_sum_168h"])


def test_without_icon_no_icon_column_is_left() -> None:
    with_icon = features(eval_dataset())
    without = features(eval_dataset(), with_icon=False)
    assert {"icon_mean_1", "icon_p90_24", "icon_lead_24"} <= set(with_icon.columns)
    assert not [c for c in without.columns if "icon" in str(c)]
    assert not [c for c in step_features(eval_dataset(), with_icon=False) if "icon" in str(c)]


def test_time_of_year_is_on_the_unit_circle() -> None:
    result = features(eval_dataset(first_issue="2024-03-20T00:30Z"))
    radius = result["year_sin"] ** 2 + result["year_cos"] ** 2
    assert np.allclose(radius, 1)
    # Around the March equinox, a quarter into the year.
    assert result["year_sin"].iloc[0] == pytest.approx(1, abs=0.03)


@pytest.mark.parametrize("build", [features, step_features])
def test_no_feature_reads_a_target(build: Callable[[pd.DataFrame], pd.DataFrame]) -> None:
    dataset = eval_dataset()
    changed = dataset.copy()
    target_columns = [str(c) for c in dataset if str(c).startswith(contract.TARGET)]
    changed[target_columns] = np.nan
    original = build(dataset)
    assert not [c for c in original.columns if str(c).startswith(contract.TARGET)]
    pd.testing.assert_frame_equal(original, build(changed))


def test_step_features_repeat_each_issue_time_once_per_lead() -> None:
    dataset = eval_dataset(hours=3)
    result = step_features(dataset)
    assert len(result) == 3 * LEADS
    assert list(result["lead"].iloc[:LEADS]) == list(range(1, LEADS + 1))
    assert set(result["kd_last_cm"].iloc[LEADS : 2 * LEADS]) == {dataset.at[1, "kd_last_cm"]}
    assert not [c for c in result.columns if str(c).startswith("icon_")]


def test_step_rain_looks_back_six_hours_and_is_nan_before_the_issue_time() -> None:
    dataset = eval_dataset(hours=2)
    result = step_features(dataset)
    assert result.at[(1, 10), "step_icon_mean_0"] == dataset.at[1, "icon_mean_10"]
    assert result.at[(1, 10), "step_icon_p90_5"] == dataset.at[1, "icon_p90_5"]
    assert result.at[(1, 2), "step_icon_mean_1"] == dataset.at[1, "icon_mean_1"]
    assert pd.isna(result.at[(1, 2), "step_icon_mean_2"])
    assert pd.isna(result.at[(1, 2), "step_icon_lead_5"])


def test_step_features_group_by_lead_and_survive_a_repeated_index() -> None:
    dataset = eval_dataset(hours=3)
    dataset.index = pd.Index([7, 7, 8])
    result = step_features(dataset)
    assert len(result) == 3 * LEADS
    assert list(result.groupby("lead").size()) == [3] * LEADS
    first_rows = result["kd_last_cm"].iloc[::LEADS].to_numpy()
    np.testing.assert_array_equal(first_rows, dataset["kd_last_cm"].to_numpy())
