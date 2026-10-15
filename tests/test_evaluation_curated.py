import json

import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.core.features import kupferdreh_change
from pegel.evaluation import contract
from pegel.evaluation.models.curated import (
    INPUTS,
    RAIN_CHANGE_V2,
    RIDGE_V2,
    CuratedChange,
    radar_sum,
    ridge_solve,
    zone_cell_counts,
)
from pegel.evaluation.models.persistence import Persistence
from pegel.evaluation.predict import selected_models

SETTINGS = load_config().evaluation
LEADS = SETTINGS.leads_hours
TARGET_COLUMNS = contract.lead_columns(contract.TARGET, LEADS)


def _model(inputs: tuple[str, ...] = RAIN_CHANGE_V2, **options: object) -> CuratedChange:
    return CuratedChange(SETTINGS, name="test", inputs=inputs, **options)  # type: ignore[arg-type]


def _training_rows(first_issue: str, hours: int) -> pd.DataFrame:
    """Synthetic rows with realistic rain, so the 5 mm hinge is on in some rows, off in others."""
    rows = eval_dataset(first_issue=first_issue, hours=hours)
    rng = np.random.default_rng(5)
    icon = rng.uniform(0, 8, size=(hours, LEADS)) * (rng.uniform(size=(hours, 1)) < 0.5)
    rows[contract.lead_columns(contract.ICON_MEAN, LEADS)] = icon
    return rows


def _with_targets(rows: pd.DataFrame, model: CuratedChange, known: np.ndarray) -> pd.DataFrame:
    """Targets that follow the model's formula exactly, with `known` for every lead."""
    rows = rows.copy()
    rows[TARGET_COLUMNS] = rows[[contract.KD_LAST_CM]].to_numpy() + model.inputs(rows) @ known
    return rows


def _rising(rows: pd.DataFrame) -> np.ndarray:
    langenberg = (rows["lb_lag_0"] - rows["lb_lag_3"]).to_numpy()
    return np.asarray((np.nan_to_num(kupferdreh_change(rows, 3)) > 0.5) | (langenberg > 0.5))


def test_registered_names_and_input_lists() -> None:
    names = ["rain_change:v2:split", "ridge:change:v2"]
    assert [factory(SETTINGS).name for factory in selected_models(names, SETTINGS)] == names
    assert set(RAIN_CHANGE_V2) <= set(RIDGE_V2) <= set(INPUTS)
    assert len(set(RIDGE_V2)) == len(RIDGE_V2)


def test_unknown_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown inputs"):
        _model(("constant", "tomorrow's level"))


def test_least_squares_recovers_known_coefficients() -> None:
    model = _model()
    known = np.random.default_rng(1).normal(size=len(RAIN_CHANGE_V2))
    # Summer issue times, so the hour terms aren't all zero.
    model.fit(_with_targets(_training_rows("2024-06-01T00:30Z", 400), model, known))
    assert model.coefficients.shape == (1, LEADS, len(RAIN_CHANGE_V2))
    np.testing.assert_allclose(model.coefficients[0], np.tile(known, (LEADS, 1)), atol=1e-6)


def test_split_fits_rising_and_other_rows_separately() -> None:
    model = _model(split=True)
    rows = _training_rows("2024-06-01T00:30Z", 600)
    rng = np.random.default_rng(2)
    rising_set, other_set = rng.normal(size=(2, len(RAIN_CHANGE_V2)))
    train = _with_targets(rows, model, rising_set)
    other = ~_rising(rows)
    train.loc[other, TARGET_COLUMNS] = _with_targets(rows, model, other_set).loc[
        other, TARGET_COLUMNS
    ]
    model.fit(train)
    np.testing.assert_allclose(model.coefficients[0], np.tile(rising_set, (LEADS, 1)), atol=1e-6)
    np.testing.assert_allclose(model.coefficients[1], np.tile(other_set, (LEADS, 1)), atol=1e-6)


def test_ridge_without_penalty_is_least_squares_and_never_shrinks_the_constant() -> None:
    rng = np.random.default_rng(3)
    inputs = np.column_stack([np.ones(200), rng.normal(size=(200, 3)) * [1, 10, 100]])
    target = inputs @ np.array([5.0, 1.0, -0.2, 0.03]) + rng.normal(scale=0.1, size=200)
    expected, *_ = np.linalg.lstsq(inputs, target, rcond=None)
    np.testing.assert_allclose(ridge_solve(inputs, target, 0.0), expected)
    # A huge penalty takes every slope to 0; the constant becomes the mean.
    shrunk = ridge_solve(inputs, target, 1e12)
    np.testing.assert_allclose(shrunk[1:], 0.0, atol=1e-6)
    assert shrunk[0] == pytest.approx(target.mean(), rel=1e-6)


def test_predict_needs_no_targets_and_ignores_them() -> None:
    model = _model(RIDGE_V2, split=True, alpha=100.0)
    known = np.random.default_rng(4).normal(size=len(RIDGE_V2))
    model.fit(_with_targets(_training_rows("2024-06-01T00:30Z", 600), model, known))
    rows = eval_dataset(first_issue="2024-07-01T00:30Z", hours=30)
    inputs_only = rows.drop(columns=[c for c in rows if str(c).startswith("target_")])
    forecast = model.predict(inputs_only)
    assert forecast.shape == (30, LEADS)
    assert np.isfinite(forecast).all()
    rows[TARGET_COLUMNS] = -1000.0
    np.testing.assert_array_equal(model.predict(rows), forecast)


def test_missing_last_level_base_or_rain_gives_persistence() -> None:
    model = _model()
    model.coefficients = np.ones((1, LEADS, len(RAIN_CHANGE_V2)))
    rows = eval_dataset(hours=3)
    rows.loc[0, contract.KD_BASE_30D_CM] = np.nan
    rows.loc[1, contract.KD_LAST_CM] = np.nan
    rows.loc[2, "radar_middle_lag_5"] = np.nan
    np.testing.assert_array_equal(model.predict(rows), Persistence(SETTINGS).predict(rows))


def test_missing_kupferdreh_lags_and_upstream_still_give_a_forecast() -> None:
    model = _model()
    model.coefficients = np.ones((1, LEADS, len(RAIN_CHANGE_V2)))
    rows = eval_dataset(hours=1)
    rows[[*contract.level_lag_columns("kupferdreh"), "lb_lag_3", "nh_lag_0"]] = np.nan
    forecast = model.predict(rows)
    assert np.isfinite(forecast).all()
    assert not np.array_equal(forecast, Persistence(SETTINGS).predict(rows))


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


def test_saved_model_loads_and_predicts_the_same() -> None:
    model = _model(RIDGE_V2, split=True, alpha=100.0)
    rows = _training_rows("2024-06-01T00:30Z", 600)
    rows = _with_targets(rows, model, np.random.default_rng(1).normal(size=len(RIDGE_V2)))
    model.fit(rows)
    saved = json.loads(json.dumps(model.to_dict()))
    loaded = CuratedChange.from_dict(saved, SETTINGS)
    np.testing.assert_array_equal(loaded.predict(rows), model.predict(rows))
    assert loaded.name == model.name


def test_loading_refuses_unfitted_wrong_leads_or_wrong_shape() -> None:
    with pytest.raises(ValueError, match="not fitted"):
        _model().to_dict()
    model = _model()
    model.fit(
        _with_targets(
            _training_rows("2024-02-01T00:30Z", 100), model, np.zeros(len(RAIN_CHANGE_V2))
        )
    )
    saved = model.to_dict()
    with pytest.raises(ValueError, match="leads"):
        CuratedChange.from_dict(saved | {"leads": LEADS + 1}, SETTINGS)
    with pytest.raises(ValueError, match="shape"):
        CuratedChange.from_dict(saved | {"split": True}, SETTINGS)
