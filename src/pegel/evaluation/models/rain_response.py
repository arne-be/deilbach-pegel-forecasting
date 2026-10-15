"""Rain response models: a two-store unit hydrograph fitted on radar, plus `ridge:change:v2`'s rest.

The hydrograph turns rain into a level change per lead (features.response_change): observed
radar over the last 168 hours and the ICON-D2 hours ahead, each with the same shape. It is fitted
per fold on the training rows that had rain in the last day and stayed dry for the next three
(`episodes`). Two variants, explained in docs/models.md:

- `offset`: change = radar response at the fitted gain + ridge on the rest (ICON response and
  the v2 inputs without radar and ICON sums).
- `ridge`: both responses are ridge inputs in place of the radar sums and the ICON sum.
"""

import itertools
from functools import partial

import numpy as np
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.core import features
from pegel.evaluation import contract
from pegel.evaluation.models.curated import (
    RIDGE_V2,
    RIDGE_V2_ALPHA,
    Array,
    CuratedChange,
    Mask,
    catchment_radar,
)

# Searched by least squares on the amplitudes for every combination. The analysis found about
# 6 h and 71 h for the stores and a peak about 6 h after the rain; the grid spans well beyond.
ROUTING_HOURS = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0)
FAST_HOURS = (2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0)
SLOW_HOURS = (24.0, 36.0, 48.0, 72.0, 96.0, 144.0, 240.0, 480.0)
# The fit looks 72 hours ahead: over 24 hours a slow store can't be told from a step.
FIT_HOURS = 72
# A fitting row: at least WET_MM of radar in the last 24 hours, at most DRY_MM in the next 72.
WET_MM = 1.0
DRY_MM = 0.6
DAY = 24

RESPONSE_RIDGE_V1 = tuple(
    name for name in RIDGE_V2 if not name.startswith("radar_") and name != "icon_to_lead"
)


def _later(rows: pd.DataFrame, values: Array, hours: int) -> Array:
    """`values` of the row issued `hours` later; NaN where that row isn't in `rows`."""
    issued_at = rows[contract.ISSUED_AT]
    series = pd.Series(values, index=issued_at.to_numpy())
    later = series.reindex((issued_at + pd.Timedelta(hours=hours)).to_numpy())
    return np.asarray(later, dtype=np.float64)


def episodes(rows: pd.DataFrame, radar: Array) -> tuple[Mask, Array]:
    """The fitting rows, and every row's level change over the next FIT_HOURS hours.

    A fitting row had rain in the last day and stayed dry for FIT_HOURS, so its change comes
    from rain the radar has already seen. Both look ahead like targets do, through the rows
    issued later in `rows` only, so nothing reaches past the training rows.
    """
    last = rows[contract.KD_LAST_CM].to_numpy(np.float64)
    later = [_later(rows, last, hours) for hours in range(1, FIT_HOURS + 1)]
    change = np.column_stack(later) - last[:, np.newaxis]
    day_sums = radar[:, :DAY].sum(axis=1)
    rain_ahead = sum(_later(rows, day_sums, hours) for hours in range(DAY, FIT_HOURS + 1, DAY))
    fitting: Mask = (day_sums >= WET_MM) & (np.asarray(rain_ahead) <= DRY_MM)
    return fitting, change


def fit_hydrograph(rain: Array, change: Array) -> features.Hydrograph:
    """The two-store hydrograph that best explains `change` (rows, hours) from `rain` (rows, lags).

    For each combination of time constants the two amplitudes are fitted by least squares; the
    combination with the smallest squared error and no negative amplitude wins.
    """
    hours = change.shape[1]
    usable = np.isfinite(change).all(axis=1) & np.isfinite(rain).all(axis=1)
    rain, target = rain[usable], change[usable].ravel()
    ages = features.radar_ages(rain.shape[1])
    best: tuple[float, features.Hydrograph] | None = None
    for routing, fast, slow in itertools.product(ROUTING_HOURS, FAST_HOURS, SLOW_HOURS):
        if fast <= routing:
            continue
        stores = [
            features.response_change(
                rain,
                ages,
                partial(features.store_response, store_hours=tau, routing_hours=routing),
                hours,
            ).ravel()
            for tau in (fast, slow)
        ]
        inputs = np.column_stack(stores)
        amplitudes, *_ = np.linalg.lstsq(inputs, target, rcond=None)
        if (amplitudes < 0).any():
            continue
        error = float(np.sum((inputs @ amplitudes - target) ** 2))
        if best is None or error < best[0]:
            hydrograph = features.Hydrograph(
                fast_cm_per_mm=float(amplitudes[0]),
                slow_cm_per_mm=float(amplitudes[1]),
                fast_hours=fast,
                slow_hours=slow,
                routing_hours=routing,
            )
            best = (error, hydrograph)
    if best is None:
        raise ValueError(f"no hydrograph with positive amplitudes fits {len(rain)} rows")
    return best[1]


class RainResponse(CuratedChange):
    def __init__(self, settings: EvaluationSettings, *, name: str, radar_offset: bool) -> None:
        super().__init__(
            settings, name=name, inputs=RESPONSE_RIDGE_V1, split=True, alpha=RIDGE_V2_ALPHA
        )
        self._radar_offset = radar_offset
        # Set by fit.
        self.hydrograph: features.Hydrograph | None = None

    def fit(self, train: pd.DataFrame) -> None:
        radar = catchment_radar(train, self._cell_counts, contract.RADAR_LAG_HOURS)
        fitting, change = episodes(train, radar)
        self.hydrograph = fit_hydrograph(radar[fitting], change[fitting])
        super().fit(train)

    def radar_response(self, rows: pd.DataFrame) -> Array:
        """Shape (rows, leads): the change the radar rain of the last 168 hours gives."""
        radar = catchment_radar(rows, self._cell_counts, contract.RADAR_LAG_HOURS)
        return features.response_change(
            radar, features.radar_ages(radar.shape[1]), self._fitted().response, self._leads
        )

    def icon_response(self, rows: pd.DataFrame) -> Array:
        """Shape (rows, leads): the change the ICON-D2 hours ahead give at the radar's gain."""
        icon = rows[contract.lead_columns(contract.ICON_MEAN, self._leads)].to_numpy(np.float64)
        return features.response_change(
            icon, features.icon_ages(self._leads), self._fitted().response, self._leads
        )

    def inputs(self, rows: pd.DataFrame) -> Array:
        responses = [self.icon_response(rows)]
        if not self._radar_offset:
            responses.append(self.radar_response(rows))
        return np.concatenate([super().inputs(rows), np.stack(responses, axis=2)], axis=2)

    def offset(self, rows: pd.DataFrame) -> Array:
        if self._radar_offset:
            return self.radar_response(rows)
        return super().offset(rows)

    def _fitted(self) -> features.Hydrograph:
        if self.hydrograph is None:
            raise ValueError(f"{self.name}: fit before predicting")
        return self.hydrograph
