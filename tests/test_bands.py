import numpy as np
import pytest

from pegel.config import load_config
from pegel.core import bands

SETTINGS = load_config().bands
LEADS = 3


def synthetic(rows: int = 4000) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Errors whose spread grows with the predicted change: scale 1 + |change| / 2."""
    rng = np.random.default_rng(0)
    last_level = rng.uniform(40, 60, rows)
    change = rng.normal(0, 6, (rows, LEADS))
    levels = last_level[:, np.newaxis] + change
    icon_to_lead = rng.uniform(0, 5, (rows, LEADS))
    targets = levels + rng.normal(0, 1, (rows, LEADS)) * (1 + np.abs(change) / 2)
    return levels, last_level, icon_to_lead, targets


def test_scale_follows_the_change_and_bands_hold_their_coverage() -> None:
    levels, last_level, icon_to_lead, targets = synthetic()
    table = bands.fit_band_table(levels, last_level, icon_to_lead, targets, SETTINGS)
    assert (table.scale_coefficients >= 0).all()
    # |N(0, s)| has mean 0.8 s: about 0.8 + 0.4 |change|; the constant is the noisier one.
    np.testing.assert_allclose(table.scale_coefficients[:, 0], 0.8, atol=0.2)
    np.testing.assert_allclose(table.scale_coefficients[:, 1], 0.4, atol=0.05)
    fresh = synthetic(rows=4000)
    bounds = bands.band_bounds(table, *fresh[:3], SETTINGS)
    for coverage, (lower, upper) in bounds.items():
        inside = ((lower <= fresh[3]) & (fresh[3] <= upper)).mean()
        assert inside == pytest.approx(coverage / 100, abs=0.03)
    # Nested: a wider coverage never gives a narrower band.
    (low80, high80), (low95, high95) = bounds[80], bounds[95]
    assert (low95 <= low80).all() and (high80 <= high95).all()


def test_bands_keep_the_floor_and_never_go_below_zero() -> None:
    table = bands.fit_band_table(*synthetic(), SETTINGS)
    levels = np.array([[0.5, 30.0, 30.0]])
    last_level = np.array([0.2])
    icon_to_lead = np.zeros((1, LEADS))
    lower, upper = bands.band_bounds(table, levels, last_level, icon_to_lead, SETTINGS)[80]
    assert lower[0, 0] == 0.0
    assert (upper - levels >= SETTINGS.min_half_width_cm).all()
    assert (levels[0, 1:] - lower[0, 1:] >= SETTINGS.min_half_width_cm).all()


def test_missing_input_falls_back_to_the_persistence_errors() -> None:
    table = bands.fit_band_table(*synthetic(), SETTINGS)
    last_level = np.array([50.0, 50.0])
    # Row 0: the model fell back to persistence; row 1: the rain is unknown.
    levels = np.array([[50.0, 50.0, 50.0], [52.0, 53.0, 54.0]])
    icon_to_lead = np.array([[0.0, 0.0, 0.0], [np.nan, np.nan, np.nan]])
    lower, upper = bands.band_bounds(table, levels, last_level, icon_to_lead, SETTINGS)[90]
    index = table.coverages_percent.index(90)
    floor = SETTINGS.min_half_width_cm
    expected_upper = levels + np.maximum(table.persistence_upper[index], floor)
    np.testing.assert_allclose(upper, expected_upper)
    assert np.isfinite(lower).all()
    tags = bands.situations(levels, last_level, icon_to_lead, SETTINGS)
    assert tags == [bands.DEGRADED, bands.DEGRADED]


def test_situations_check_degraded_then_strong_then_moving() -> None:
    last_level = np.full(4, 50.0)
    levels = 50.0 + np.array([[0.5, 9.0, 1.0], [0.5, 3.0, 1.0], [0.5, 0.5, 0.5], [0.5, 0.5, -1]])
    icon_to_lead = np.array([[0, 0, 0], [0, 0, 0], [1, 2, 4], [0, 0, 1]], dtype=np.float64)
    tags = bands.situations(levels, last_level, icon_to_lead, SETTINGS)
    assert tags == [bands.STRONG, bands.MOVING, bands.MOVING, bands.CALM]


def test_too_few_rows_refuse_to_fit() -> None:
    levels, last_level, icon_to_lead, targets = synthetic(rows=50)
    with pytest.raises(ValueError, match="usable rows for lead 1"):
        bands.fit_band_table(levels, last_level, icon_to_lead, targets, SETTINGS)


def test_table_round_trips_and_refuses_broken_files() -> None:
    table = bands.fit_band_table(*synthetic(), SETTINGS)
    loaded = bands.BandTable.from_dict(table.to_dict())
    np.testing.assert_array_equal(loaded.z_upper, table.z_upper)
    assert loaded.coverages_percent == table.coverages_percent
    broken = table.to_dict()
    broken["z_lower"] = broken["z_lower"][:-1]
    with pytest.raises(ValueError, match="z_lower has shape"):
        bands.BandTable.from_dict(broken)
    broken = table.to_dict()
    broken["scale_caps"][0] = float("nan")
    with pytest.raises(ValueError, match="not all finite"):
        bands.BandTable.from_dict(broken)


def test_non_negative_least_squares_drops_a_column_that_would_go_negative() -> None:
    inputs = np.column_stack([np.ones(4), [0.0, 1.0, 2.0, 3.0]])
    target = np.array([3.0, 2.0, 1.0, 0.0])
    np.testing.assert_allclose(bands.non_negative_least_squares(inputs, target), [1.5, 0.0])
