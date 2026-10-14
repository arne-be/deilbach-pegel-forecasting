import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.models.persistence import Persistence
from pegel.evaluation.models.rain_change import RainChange, radar_sum, zone_cell_counts

SETTINGS = load_config().evaluation
LEADS = SETTINGS.leads_hours
INPUTS = 7
TARGET_COLUMNS = contract.lead_columns(contract.TARGET, LEADS)
# Constant, distance to base, Langenberg, Nierenhof, recent radar, old radar, ICON-D2 sum.
KNOWN = np.array([-1.5, -0.2, 0.8, 0.4, 2.0, -0.3, 0.6])
OTHER = np.array([0.5, -0.05, 0.1, 0.2, 0.7, -0.1, 0.2])


def _inputs(rows: pd.DataFrame) -> np.ndarray:
    """The model's inputs, computed independently of the model; shape (rows, leads, inputs)."""
    counts = zone_cell_counts()
    total = sum(counts.values())
    recent = sum(
        rows[contract.lag_columns(f"radar_{zone}", 3)].sum(axis=1) * cells / total
        for zone, cells in counts.items()
    )
    old = sum(
        rows[contract.lag_columns(f"radar_{zone}", 12)[3:]].sum(axis=1) * cells / total
        for zone, cells in counts.items()
    )
    fixed = np.column_stack(
        [
            np.ones(len(rows)),
            rows[contract.KD_LAST_CM] - rows[contract.KD_BASE_30D_CM],
            rows["lb_lag_0"] - rows["lb_lag_3"],
            rows["nh_lag_0"] - rows["nh_lag_3"],
            recent,
            old,
        ]
    )
    icon = rows[contract.lead_columns(contract.ICON_MEAN, LEADS)].to_numpy().cumsum(axis=1)
    repeated = np.repeat(fixed[:, np.newaxis, :], LEADS, axis=1)
    return np.concatenate([repeated, icon[:, :, np.newaxis]], axis=2)


def _with_targets(rows: pd.DataFrame, coefficients: np.ndarray) -> pd.DataFrame:
    """Targets that follow the model's formula exactly, with the same coefficients per lead."""
    rows = rows.copy()
    change = _inputs(rows) @ coefficients
    rows[TARGET_COLUMNS] = rows[[contract.KD_LAST_CM]].to_numpy() + change
    return rows


def _model_with(split: bool, *coefficient_sets: np.ndarray) -> RainChange:
    model = RainChange(SETTINGS, split=split)
    model.coefficients = np.array([np.tile(c, (LEADS, 1)) for c in coefficient_sets])
    return model


def test_names() -> None:
    assert RainChange(SETTINGS).name == "rain_change"
    assert RainChange(SETTINGS, split=True).name == "rain_change:split"


def test_radar_is_the_cell_weighted_mean_of_the_zones() -> None:
    counts = {"neviges": 1, "lower": 3}
    rows = pd.DataFrame(
        {
            **{f"radar_neviges_lag_{k}": [4.0] for k in range(12)},
            **{f"radar_lower_lag_{k}": [0.0] for k in range(12)},
        }
    )
    rows["radar_lower_lag_1"] = 8.0
    # Lags 0..2: neviges 3 x 4 mm with weight 1/4, lower 8 mm with weight 3/4.
    assert radar_sum(rows, counts, 0, 3) == pytest.approx([3.0 + 6.0])
    # Lags 3..11: only neviges, 9 x 4 mm with weight 1/4.
    assert radar_sum(rows, counts, 3, 12) == pytest.approx([9.0])


def test_zone_counts_come_from_the_cells_file_without_the_catchment() -> None:
    counts = zone_cell_counts()
    assert "catchment" not in counts
    assert set(counts) == {"neviges", "upper_deilbach", "felderbach", "middle", "lower"}


def test_fit_recovers_known_coefficients_for_every_lead() -> None:
    train = _with_targets(eval_dataset(hours=300), KNOWN)
    model = RainChange(SETTINGS)
    model.fit(train)
    assert model.coefficients.shape == (1, LEADS, INPUTS)
    np.testing.assert_allclose(model.coefficients[0], np.tile(KNOWN, (LEADS, 1)), atol=1e-8)


def test_split_fits_rising_and_other_rows_separately() -> None:
    rows = eval_dataset(hours=400)
    rising = (rows[contract.KD_LAST_CM] - rows["kd_lag_3"] > 0.5) | (
        rows["lb_lag_0"] - rows["lb_lag_3"] > 0.5
    )
    train = _with_targets(rows, KNOWN)
    train.loc[~rising, TARGET_COLUMNS] = _with_targets(rows, OTHER).loc[~rising, TARGET_COLUMNS]
    model = RainChange(SETTINGS, split=True)
    model.fit(train)
    np.testing.assert_allclose(model.coefficients[0], np.tile(KNOWN, (LEADS, 1)), atol=1e-8)
    np.testing.assert_allclose(model.coefficients[1], np.tile(OTHER, (LEADS, 1)), atol=1e-8)


def test_split_calls_a_row_rising_when_kupferdreh_or_langenberg_rose() -> None:
    rows = eval_dataset(hours=4)
    rows[contract.KD_LAST_CM] = 50.0
    rows["lb_lag_0"] = 30.0
    # Kupferdreh up 0.6; Langenberg up 0.6; both up 0.4; Kupferdreh unknown, Langenberg flat.
    rows["kd_lag_3"] = [49.4, 50.0, 49.6, np.nan]
    rows["lb_lag_3"] = [30.0, 29.4, 29.6, 30.0]
    rising_constant = np.zeros(INPUTS)
    rising_constant[0] = 1.0
    other_constant = np.zeros(INPUTS)
    other_constant[0] = 2.0
    model = _model_with(True, rising_constant, other_constant)
    forecast = model.predict(rows)
    np.testing.assert_allclose(forecast[:, 0], [51.0, 51.0, 52.0, 52.0])


def test_missing_last_level_or_base_gives_persistence() -> None:
    rows = eval_dataset(hours=3)
    rows.loc[0, contract.KD_BASE_30D_CM] = np.nan
    rows.loc[1, contract.KD_LAST_CM] = np.nan
    rows.loc[2, "radar_middle_lag_5"] = np.nan
    forecast = _model_with(False, KNOWN).predict(rows)
    np.testing.assert_array_equal(forecast, Persistence(SETTINGS).predict(rows))


def test_missing_upstream_change_counts_as_zero() -> None:
    one_row = eval_dataset(hours=1)
    rows = pd.concat([one_row, one_row], ignore_index=True)
    rows.loc[0, ["lb_lag_3", "nh_lag_0"]] = np.nan
    rows.loc[1, "lb_lag_3"] = rows.loc[1, "lb_lag_0"]
    rows.loc[1, "nh_lag_0"] = rows.loc[1, "nh_lag_3"]
    forecast = _model_with(False, KNOWN).predict(rows)
    np.testing.assert_allclose(forecast[0], forecast[1])


def test_predict_needs_no_target_columns_and_gives_one_value_per_lead() -> None:
    train = _with_targets(eval_dataset(hours=300), KNOWN)
    model = RainChange(SETTINGS)
    model.fit(train)
    rows = eval_dataset(first_issue="2024-03-01T00:30Z", hours=50)
    expected = rows[[contract.KD_LAST_CM]].to_numpy() + _inputs(rows) @ KNOWN
    inputs_only = rows.loc[:, ~rows.columns.str.startswith(f"{contract.TARGET}_")]
    forecast = model.predict(inputs_only)
    assert forecast.shape == (50, LEADS)
    np.testing.assert_allclose(forecast, expected, atol=1e-6)


def test_fit_rejects_a_group_with_too_few_rows() -> None:
    train = _with_targets(eval_dataset(hours=300), KNOWN)
    # No row rises, so the rising set would have nothing to fit.
    train["kd_lag_3"] = train[contract.KD_LAST_CM]
    train["lb_lag_3"] = train["lb_lag_0"]
    with pytest.raises(ValueError, match="usable training rows"):
        RainChange(SETTINGS, split=True).fit(train)
