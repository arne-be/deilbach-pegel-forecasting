import math

import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset, radar_areas

from pegel.config import load_config
from pegel.core.features import (
    Hydrograph,
    icon_ages,
    radar_ages,
    response_change,
    store_response,
)
from pegel.evaluation import contract
from pegel.evaluation.models.rain_response import RainResponse
from pegel.evaluation.predict import selected_models

SETTINGS = load_config().evaluation
LEADS = SETTINGS.leads_hours
TRUE = Hydrograph(
    fast_cm_per_mm=2.5, slow_cm_per_mm=0.8, fast_hours=6.0, slow_hours=96.0, routing_hours=3.0
)


def test_rain_that_fell_keeps_acting_and_icon_acts_once_it_falls() -> None:
    no_routing = Hydrograph(2.0, 1.0, 5.0, 50.0, 0.0)

    def unit(age: float) -> float:
        return 2.0 * math.exp(-age / 5.0) + 1.0 * math.exp(-age / 50.0) if age > 0 else 0.0

    radar = np.zeros((1, 168))
    radar[0, 2] = 3.0  # 3 mm, 3 hours old at the issue time
    change = response_change(radar, radar_ages(168), no_routing.response, LEADS)
    expected = [3.0 * (unit(3 + k) - unit(3)) for k in range(1, LEADS + 1)]
    np.testing.assert_allclose(change[0], expected)

    icon = np.zeros((1, LEADS))
    icon[0, 4] = 2.0  # column 5: falls 3 hours after the issue time
    change = response_change(icon, icon_ages(LEADS), no_routing.response, LEADS)
    expected = [2.0 * unit(k - 3) for k in range(1, LEADS + 1)]
    np.testing.assert_allclose(change[0], expected)
    assert (change[0, :3] == 0).all()


def test_a_routed_store_starts_empty_and_peaks_on_time() -> None:
    ages = np.arange(0.0, 48.0, 0.01)
    content = store_response(ages, 6.0, 3.0)
    assert content[0] == 0.0
    # Two linear stores in series peak at ln(tau / tau_r) · tau · tau_r / (tau - tau_r).
    assert ages[content.argmax()] == pytest.approx(math.log(2) * 6.0, abs=0.01)
    with pytest.raises(ValueError, match="differ"):
        store_response(ages, 3.0, 3.0)


def _rain_world(hours: int) -> pd.DataFrame:
    """Hourly rows whose levels follow TRUE exactly: 5-hour rain bursts 600 hours apart.

    So far apart that rain older than the 168 radar lags has almost no effect left.
    """
    rain = np.zeros(hours)
    rng = np.random.default_rng(7)
    for start in range(200, hours - 10, 600):
        rain[start : start + 5] = rng.uniform(0.5, 4.0, size=5)
    # Rain of hour i is lag 0 of row i; at row i its age is j + 1 for lag j.
    level = 50.0 + np.convolve(rain, TRUE.response(radar_ages(hours)))[:hours]
    rows = eval_dataset(first_issue="2024-02-01T00:30Z", hours=hours)
    lagged = np.column_stack([np.roll(rain, lag) for lag in range(contract.RADAR_LAG_HOURS)])
    for area in radar_areas():
        rows[contract.radar_lag_columns(area)] = lagged
    # A perfect ICON-D2: column k is the rain of hour i + k - 1. Column 1 is radar lag 0 again,
    # so the world leaves it at 0.
    future = np.concatenate([rain, np.zeros(LEADS)])
    rows[contract.lead_columns(contract.ICON_MEAN, LEADS)] = np.column_stack(
        [np.zeros(hours)] + [future[k - 1 : k - 1 + hours] for k in range(2, LEADS + 1)]
    )
    rows[contract.KD_LAST_CM] = level
    padded = np.concatenate([level, np.full(LEADS, np.nan)])
    rows[contract.lead_columns(contract.TARGET, LEADS)] = np.column_stack(
        [padded[k : k + hours] for k in range(1, LEADS + 1)]
    )
    return rows


def test_fit_recovers_the_hydrograph_from_radar_episodes() -> None:
    model = RainResponse(SETTINGS, name="test", radar_offset=True)
    model.fit(_rain_world(4000))
    assert model.hydrograph is not None
    assert model.hydrograph.fast_hours == TRUE.fast_hours
    assert model.hydrograph.slow_hours == TRUE.slow_hours
    assert model.hydrograph.routing_hours == TRUE.routing_hours
    assert model.hydrograph.fast_cm_per_mm == pytest.approx(TRUE.fast_cm_per_mm, rel=0.01)
    assert model.hydrograph.slow_cm_per_mm == pytest.approx(TRUE.slow_cm_per_mm, rel=0.01)


@pytest.mark.parametrize("radar_offset", [True, False])
def test_both_variants_predict_the_rain_world_without_targets(radar_offset: bool) -> None:
    world = _rain_world(4000)
    model = RainResponse(SETTINGS, name="test", radar_offset=radar_offset)
    model.fit(world.iloc[:3700])
    rows = world.iloc[3700:4000]
    targets = rows[contract.lead_columns(contract.TARGET, LEADS)].to_numpy()
    forecast = model.predict(rows.drop(columns=contract.lead_columns(contract.TARGET, LEADS)))
    assert forecast.shape == (300, LEADS)
    persistence = rows[[contract.KD_LAST_CM]].to_numpy()
    # Not exact: the ridge penalty and the random other inputs cost a little.
    assert np.nanmean(np.abs(forecast - targets)) < 0.1 * np.nanmean(np.abs(persistence - targets))


def test_variants_are_registered() -> None:
    names = ["rain_response:v1:offset", "rain_response:v1:ridge"]
    assert [factory(SETTINGS).name for factory in selected_models(names, SETTINGS)] == names
