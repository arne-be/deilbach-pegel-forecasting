"""Uncertainty bands from past errors of the model, scaled by how much it expects to change.

Per lead k, the error scale is s_k = a_k + b_k·|predicted change_k| + c_k·(ICON rain to k),
capped. The band is the forecast plus empirical quantiles of error / s_k. Where the model fell
back to persistence (a missing input), the quantiles of the persistence error are used instead.
Chosen against one table per lead and against situation buckets in
analysis/model-evaluation/learnings.md; explained in docs/models.md#uncertainty-bands.

Arrays are (rows, leads), one column per lead the model forecasts.
"""

from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import numpy.typing as npt

from pegel.config import BandSettings

Array = npt.NDArray[np.float64]

# The scale never goes below this, so a calm hour never divides by zero.
MIN_SCALE_CM = 0.1
# Fewer usable rows per lead than this give quantiles too rough to publish.
MIN_ROWS_PER_LEAD = 100

CALM = "calm"
MOVING = "moving"
STRONG = "strong"
# Some input was missing and the model fell back to persistence.
DEGRADED = "degraded"


def quantile_pair(coverage_percent: int) -> tuple[float, float]:
    """The lower and upper quantile of a central band, e.g. 0.05 and 0.95 for 90 %."""
    tail = (100 - coverage_percent) / 200
    return tail, 1 - tail


@dataclass(frozen=True)
class BandTable:
    """Fitted per lead. Quantiles are (coverages, leads), in the order of coverages_percent."""

    coverages_percent: tuple[int, ...]
    # (leads, 3): constant, |predicted change|, ICON rain to the lead.
    scale_coefficients: Array
    scale_caps: Array
    z_lower: Array
    z_upper: Array
    persistence_lower: Array
    persistence_upper: Array

    @property
    def leads(self) -> int:
        return len(self.scale_caps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverages_percent": list(self.coverages_percent),
            "scale_coefficients": self.scale_coefficients.tolist(),
            "scale_caps": self.scale_caps.tolist(),
            "z_lower": self.z_lower.tolist(),
            "z_upper": self.z_upper.tolist(),
            "persistence_lower": self.persistence_lower.tolist(),
            "persistence_upper": self.persistence_upper.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BandTable":
        """The table saved by `to_dict`; refuses wrong shapes and values that aren't finite."""
        coverages = tuple(int(coverage) for coverage in data["coverages_percent"])
        arrays = {
            name: np.array(data[name], dtype=np.float64)
            for name in (
                "scale_coefficients",
                "scale_caps",
                "z_lower",
                "z_upper",
                "persistence_lower",
                "persistence_upper",
            )
        }
        leads = len(arrays["scale_caps"])
        expected = {"scale_coefficients": (leads, 3), "scale_caps": (leads,)}
        for name, values in arrays.items():
            shape = expected.get(name, (len(coverages), leads))
            if values.shape != shape:
                raise ValueError(f"band table {name} has shape {values.shape}, expected {shape}")
            if not np.isfinite(values).all():
                raise ValueError(f"band table {name} is not all finite")
        return cls(coverages_percent=coverages, **arrays)


def fit_band_table(
    levels: Array, last_level: Array, icon_to_lead: Array, targets: Array, settings: BandSettings
) -> BandTable:
    """Fits the scale and the quantiles per lead on out-of-sample forecasts and their truth.

    `levels`, `icon_to_lead` and `targets` are (rows, leads); `last_level` is (rows,). Rows
    without a target are left out per lead.
    """
    change = levels - last_level[:, np.newaxis]
    pairs = [quantile_pair(coverage) for coverage in settings.coverages_percent]
    lower_levels = [lower for lower, _ in pairs]
    upper_levels = [upper for _, upper in pairs]
    coefficients, caps, z_lower, z_upper, persistence_lower, persistence_upper = (
        [] for _ in range(6)
    )
    for lead in range(levels.shape[1]):
        error = targets[:, lead] - levels[:, lead]
        persistence_error = targets[:, lead] - last_level
        usable = (
            np.isfinite(error)
            & np.isfinite(persistence_error)
            & np.isfinite(icon_to_lead[:, lead])
            # The model fell back to persistence there: its error belongs to the other table.
            & (change[:, lead] != 0)
        )
        if usable.sum() < MIN_ROWS_PER_LEAD:
            raise ValueError(
                f"{usable.sum()} usable rows for lead {lead + 1}, need {MIN_ROWS_PER_LEAD}"
            )
        inputs = _scale_inputs(change[usable, lead], icon_to_lead[usable, lead])
        # Non-negative, so the scale grows with change and rain, never shrinks.
        fitted = non_negative_least_squares(inputs, np.abs(error[usable]))
        raw_scale = np.maximum(inputs @ fitted, MIN_SCALE_CM)
        cap = float(np.quantile(raw_scale, settings.scale_cap_quantile))
        z = error[usable] / np.minimum(raw_scale, cap)
        coefficients.append(fitted)
        caps.append(cap)
        z_lower.append(np.quantile(z, lower_levels))
        z_upper.append(np.quantile(z, upper_levels))
        persistence_lower.append(np.quantile(persistence_error[usable], lower_levels))
        persistence_upper.append(np.quantile(persistence_error[usable], upper_levels))
    return BandTable(
        coverages_percent=settings.coverages_percent,
        scale_coefficients=np.array(coefficients),
        scale_caps=np.array(caps),
        z_lower=np.array(z_lower).T,
        z_upper=np.array(z_upper).T,
        persistence_lower=np.array(persistence_lower).T,
        persistence_upper=np.array(persistence_upper).T,
    )


def degraded(levels: Array, last_level: Array, icon_to_lead: Array) -> npt.NDArray[np.bool_]:
    """(rows, leads): the model fell back to persistence there, or the rain is unknown.

    A curated model sets the change of a lead with any missing input to exactly 0; a real
    forecast never lands exactly on the last level (0 of 13,416 test issue times did).
    """
    change = levels - last_level[:, np.newaxis]
    result: npt.NDArray[np.bool_] = (
        (change == 0) | ~np.isfinite(change) | ~np.isfinite(icon_to_lead)
    )
    return result


def band_bounds(
    table: BandTable,
    levels: Array,
    last_level: Array,
    icon_to_lead: Array,
    settings: BandSettings,
) -> dict[int, tuple[Array, Array]]:
    """Lower and upper bound per configured coverage, each (rows, leads); lower never below 0."""
    if levels.shape[1] != table.leads:
        raise ValueError(f"forecast has {levels.shape[1]} leads, band table {table.leads}")
    missing = set(settings.coverages_percent) - set(table.coverages_percent)
    if missing:
        raise ValueError(f"band table has no coverage {sorted(missing)}")
    fallback = degraded(levels, last_level, icon_to_lead)
    scale = _scale(table, levels - last_level[:, np.newaxis], icon_to_lead)
    floor = settings.min_half_width_cm
    bounds = {}
    for coverage in settings.coverages_percent:
        index = table.coverages_percent.index(coverage)
        lower = np.where(fallback, table.persistence_lower[index], table.z_lower[index] * scale)
        upper = np.where(fallback, table.persistence_upper[index], table.z_upper[index] * scale)
        bounds[coverage] = (
            np.maximum(levels + np.minimum(lower, -floor), 0.0),
            levels + np.maximum(upper, floor),
        )
    return bounds


def situations(
    levels: Array, last_level: Array, icon_to_lead: Array, settings: BandSettings
) -> list[str]:
    """A tag per row for the page. It names the situation; the bands don't depend on it."""
    fallback = degraded(levels, last_level, icon_to_lead).any(axis=1)
    largest_change = np.abs(levels - last_level[:, np.newaxis]).max(axis=1)
    rain = icon_to_lead[:, -1]
    tags = []
    for row in range(len(levels)):
        if fallback[row]:
            tags.append(DEGRADED)
        elif largest_change[row] >= settings.strong_change_cm:
            tags.append(STRONG)
        elif (
            largest_change[row] >= settings.moving_change_cm or rain[row] >= settings.moving_rain_mm
        ):
            tags.append(MOVING)
        else:
            tags.append(CALM)
    return tags


def non_negative_least_squares(inputs: Array, target: Array) -> Array:
    """Least squares with every coefficient >= 0, exact for a few columns.

    The optimum is the plain fit on its non-zero columns, so trying every subset of columns and
    keeping the best fit without a negative coefficient finds it.
    """
    columns = inputs.shape[1]
    best: Array = np.zeros(columns)
    best_residual = float(np.sum(target**2))
    for size in range(1, columns + 1):
        for subset in combinations(range(columns), size):
            solution, *_ = np.linalg.lstsq(inputs[:, subset], target, rcond=None)
            if (solution < 0).any():
                continue
            residual = float(np.sum((inputs[:, subset] @ solution - target) ** 2))
            if residual < best_residual:
                best = np.zeros(columns)
                best[list(subset)] = solution
                best_residual = residual
    return best


def _scale_inputs(change: Array, icon_to_lead: Array) -> Array:
    return np.column_stack([np.ones(len(change)), np.abs(change), icon_to_lead])


def _scale(table: BandTable, change: Array, icon_to_lead: Array) -> Array:
    a, b, c = (table.scale_coefficients[:, column] for column in range(3))
    raw = a + b * np.abs(change) + c * icon_to_lead
    result: Array = np.minimum(np.maximum(raw, MIN_SCALE_CM), table.scale_caps)
    return result
