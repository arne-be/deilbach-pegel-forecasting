"""Curated change models: the last level plus a linear change in a few named inputs, per lead.

The second iteration of `rain_change` and `ridge:change`, built from the learnings in
analysis/model-evaluation/learnings.md. Each model is a list of input names from `INPUTS`, so
every coefficient has a physical meaning. Per lead k:

    change_k = sum_i c_ik · input_i(row, k)

fitted on the training rows with a target by least squares, or by ridge with a fixed strength
on standardised inputs. With `split=True` there are two coefficient sets: rising rows
(Kupferdreh or Langenberg up more than 0.5 cm in 3 hours) and the rest. A missing upstream
change, Kupferdreh change or recent rise counts as 0; any other missing input gives
persistence. Explained in docs/models/rain-change-v2.md and docs/models/ridge-change-v2.md.
"""

from collections.abc import Callable, Sequence

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.core import features
from pegel.evaluation import contract
from pegel.evaluation.models.rain_change import radar_sum, zone_cell_counts

Array = npt.NDArray[np.float64]
Mask = npt.NDArray[np.bool_]
# One value per row and lead, NaN where missing.
InputFunction = Callable[[pd.DataFrame, int, dict[str, int]], Array]

RISING_CM = 0.5
# Chosen on inner time splits of the training rows, see models-v2-candidates.csv.
RISE_HOURS_SLOW = 24.0
RISE_HOURS_FAST = 6.0
ICON_HINGE_MM = 5.0


def _same_for_all_leads(values: Array, leads: int) -> Array:
    return np.repeat(values[:, np.newaxis], leads, axis=1)


def _row_input(build: Callable[[pd.DataFrame], Array]) -> InputFunction:
    """An input with one value per row, the same for every lead."""
    return lambda rows, leads, _: _same_for_all_leads(build(rows), leads)


def _upstream_change(prefix: str) -> InputFunction:
    """3-hour change of an upstream gauge, 0 when missing (no wave)."""
    return _row_input(
        lambda rows: np.nan_to_num(
            (rows[f"{prefix}_lag_0"] - rows[f"{prefix}_lag_3"]).to_numpy(np.float64)
        )
    )


def _radar(first: int, end: int) -> InputFunction:
    def build(rows: pd.DataFrame, leads: int, cell_counts: dict[str, int]) -> Array:
        return _same_for_all_leads(radar_sum(rows, cell_counts, first, end), leads)

    return build


def _icon_window(first: int, last: int) -> InputFunction:
    """ICON-D2 mean summed over hours `first`..`last`, the same for every lead."""

    def window(rows: pd.DataFrame) -> Array:
        cumulative = features.icon_cumulative(rows, last)
        before: Array = cumulative[:, first - 2] if first > 1 else np.zeros(len(rows))
        return cumulative[:, last - 1] - before

    return _row_input(window)


def _kupferdreh_change(hours: int) -> InputFunction:
    return _row_input(lambda rows: np.nan_to_num(features.kupferdreh_change(rows, hours)))


def _recent_rise(hours: float) -> InputFunction:
    return _row_input(lambda rows: np.nan_to_num(features.recent_rise(rows, hours)))


def _hour_term(column: int) -> InputFunction:
    return _row_input(lambda rows: features.summer_hour_terms(rows)[:, column])


def _last_level(rows: pd.DataFrame) -> Array:
    return rows[[contract.KD_LAST_CM]].to_numpy(np.float64)


INPUTS: dict[str, InputFunction] = {
    "constant": lambda rows, leads, _: np.ones((len(rows), leads)),
    "to_base": _row_input(
        lambda rows: (rows[contract.KD_LAST_CM] - rows[contract.KD_BASE_30D_CM]).to_numpy(
            np.float64
        )
    ),
    "kd_change_1h": _kupferdreh_change(1),
    "kd_change_3h": _kupferdreh_change(3),
    "lb_change_3h": _upstream_change("lb"),
    "nh_change_3h": _upstream_change("nh"),
    "recent_rise_6h": _recent_rise(RISE_HOURS_FAST),
    "recent_rise_24h": _recent_rise(RISE_HOURS_SLOW),
    "radar_0_2": _radar(0, 3),
    "radar_3_11": _radar(3, 12),
    "radar_12_23": _radar(12, 24),
    "icon_to_lead": lambda rows, leads, _: features.icon_cumulative(rows, leads),
    "icon_to_lead_above_5": lambda rows, leads, _: np.maximum(
        features.icon_cumulative(rows, leads) - ICON_HINGE_MM, 0.0
    ),
    "icon_to_lead_x_level": lambda rows, leads, _: (
        features.icon_cumulative(rows, leads) * _last_level(rows) / 10
    ),
    "icon_1_6": _icon_window(1, 6),
    "icon_1_24": _icon_window(1, 24),
    "summer_hour_sin": _hour_term(0),
    "summer_hour_cos": _hour_term(1),
    "summer_hour2_sin": _hour_term(2),
    "summer_hour2_cos": _hour_term(3),
}

_SUMMER_HOUR = ("summer_hour_sin", "summer_hour_cos", "summer_hour2_sin", "summer_hour2_cos")
# rain_change's six inputs and constant, plus what the inner splits kept.
RAIN_CHANGE_V2 = (
    "constant",
    "to_base",
    "lb_change_3h",
    "nh_change_3h",
    "radar_0_2",
    "radar_3_11",
    "icon_to_lead",
    "recent_rise_24h",
    "kd_change_3h",
    "icon_to_lead_above_5",
    *_SUMMER_HOUR,
)
RIDGE_V2 = (
    *RAIN_CHANGE_V2[:9],
    *_SUMMER_HOUR,
    "kd_change_1h",
    "recent_rise_6h",
    "radar_12_23",
    "icon_1_6",
    "icon_1_24",
    "icon_to_lead_above_5",
    "icon_to_lead_x_level",
)
RIDGE_V2_ALPHA = 100.0


class CuratedChange:
    def __init__(
        self,
        settings: EvaluationSettings,
        *,
        name: str,
        inputs: Sequence[str],
        split: bool = False,
        alpha: float = 0.0,
    ) -> None:
        unknown = set(inputs) - INPUTS.keys()
        if unknown:
            raise ValueError(f"unknown inputs {sorted(unknown)}")
        self.name = name
        self._leads = settings.leads_hours
        self._input_names = list(inputs)
        self._split = split
        self._alpha = alpha
        self._cell_counts = zone_cell_counts()
        # Shape (groups, leads, inputs); set by fit.
        self.coefficients: Array = np.empty((0, 0, 0))

    def inputs(self, rows: pd.DataFrame) -> Array:
        """Shape (rows, leads, inputs), in the order of the input names."""
        columns = [INPUTS[name](rows, self._leads, self._cell_counts) for name in self._input_names]
        return np.stack(columns, axis=2)

    def groups(self, rows: pd.DataFrame) -> list[Mask]:
        """Row masks, one per coefficient set."""
        if not self._split:
            return [np.ones(len(rows), dtype=bool)]
        kupferdreh = np.nan_to_num(features.kupferdreh_change(rows, 3))
        langenberg = np.nan_to_num((rows["lb_lag_0"] - rows["lb_lag_3"]).to_numpy(np.float64))
        rising = (kupferdreh > RISING_CM) | (langenberg > RISING_CM)
        return [rising, ~rising]

    def fit(self, train: pd.DataFrame) -> None:
        inputs = self.inputs(train)
        change = _targets(train, self._leads) - train[[contract.KD_LAST_CM]].to_numpy(np.float64)
        coefficient_sets = []
        for group in self.groups(train):
            per_lead = []
            for lead in range(self._leads):
                lead_inputs = inputs[:, lead, :]
                usable = group & np.isfinite(change[:, lead]) & np.isfinite(lead_inputs).all(axis=1)
                if usable.sum() < lead_inputs.shape[1]:
                    raise ValueError(
                        f"{self.name}: {usable.sum()} usable training rows for lead {lead + 1}, "
                        f"need at least {lead_inputs.shape[1]}"
                    )
                per_lead.append(ridge_solve(lead_inputs[usable], change[usable, lead], self._alpha))
            coefficient_sets.append(per_lead)
        self.coefficients = np.array(coefficient_sets)

    def predict(self, rows: pd.DataFrame) -> Array:
        inputs = self.inputs(rows)
        change = np.zeros((len(rows), self._leads))
        for group, per_lead in zip(self.groups(rows), self.coefficients, strict=True):
            change[group] = np.einsum("rli,li->rl", inputs[group], per_lead)
        # A missing input gives a NaN change: fall back to persistence.
        change[~np.isfinite(change)] = 0.0
        prediction: Array = _last_level(rows) + change
        return prediction


def ridge_solve(inputs: Array, target: Array, alpha: float) -> Array:
    """Least squares with a ridge penalty of `alpha` on the standardised inputs.

    Every column is scaled to unit standard deviation before the penalty, and a constant
    column (zero spread) is never penalised. With alpha 0 it is plain least squares.
    """
    spread = inputs.std(axis=0)
    penalised = spread > 0
    scale = np.where(penalised, spread, 1.0)
    scaled = inputs / scale
    penalty = np.sqrt(alpha) * np.diag(penalised.astype(np.float64))
    stacked_inputs = np.vstack([scaled, penalty])
    stacked_target = np.concatenate([target, np.zeros(inputs.shape[1])])
    solution, *_ = np.linalg.lstsq(stacked_inputs, stacked_target, rcond=None)
    coefficients: Array = solution / scale
    return coefficients


def _targets(rows: pd.DataFrame, leads: int) -> Array:
    return rows[contract.lead_columns(contract.TARGET, leads)].to_numpy(np.float64)
