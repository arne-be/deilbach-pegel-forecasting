"""Rain change: the last level plus a linear change in six physical inputs, fitted per lead.

    change_k = c0 + c1 · (last level - 30-day base)          recession towards the base
                  + c2 · Langenberg 3 h change + c3 · Nierenhof 3 h change    upstream wave
                  + c4 · radar rain, lags 0-2 + c5 · radar rain, lags 3-11    rain on the way
                  + c6 · ICON-D2 mean summed over hours 1..k                  rain still to fall

Radar is the catchment mean: the zone means weighted by each zone's cell count. Least squares
per lead on the training rows with a target. A missing upstream change counts as 0 (no wave);
any other missing input gives persistence. With `split=True` there are two coefficient sets:
one for rising rows (Kupferdreh or Langenberg up more than 0.5 cm in 3 hours), one for the rest.
Explained in docs/models/rain-change.md.
"""

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.adapters.sources.radolan import load_cells
from pegel.config import EvaluationSettings, config_file, load_config
from pegel.core.radar import CATCHMENT_AREA
from pegel.evaluation import contract

Array = npt.NDArray[np.float64]
Mask = npt.NDArray[np.bool_]

CHANGE_HOURS = 3
RISING_CM = 0.5
# Radar lags 0..2 are rain still on its way; lags 3..11 have mostly run off already.
RECENT_RADAR_HOURS = 3
OLD_RADAR_HOURS = 12
KUPFERDREH = contract.GAUGE_PREFIXES["kupferdreh"]
LANGENBERG = contract.GAUGE_PREFIXES["langenberg"]
NIERENHOF = contract.GAUGE_PREFIXES["nierenhof"]


def zone_cell_counts() -> dict[str, int]:
    """Radar cells per zone of the cells file; `catchment` is all of them, not a zone."""
    cells = load_cells(config_file(load_config().rain.radar.cells_file))
    return {area: len(indices) for area, indices in cells.items() if area != CATCHMENT_AREA}


def radar_sum(rows: pd.DataFrame, cell_counts: dict[str, int], first: int, end: int) -> Array:
    """Catchment mean radar rain summed over lags `first` to `end - 1`."""
    all_cells = sum(cell_counts.values())
    total = np.zeros(len(rows))
    for zone, cells in cell_counts.items():
        columns = contract.lag_columns(f"radar_{zone}", end)[first:]
        total += rows[columns].to_numpy(np.float64).sum(axis=1) * cells / all_cells
    return total


def level_change(rows: pd.DataFrame, prefix: str) -> Array:
    """Change of a gauge's level over the last CHANGE_HOURS hours; NaN where a value is missing."""
    newest = rows[f"{prefix}_lag_0"]
    return (newest - rows[f"{prefix}_lag_{CHANGE_HOURS}"]).to_numpy(np.float64)


class RainChange:
    def __init__(self, settings: EvaluationSettings, *, split: bool = False) -> None:
        self.name = "rain_change:split" if split else "rain_change"
        self._leads = settings.leads_hours
        self._split = split
        self._cell_counts = zone_cell_counts()
        # Shape (groups, leads, inputs); set by fit.
        self.coefficients: Array = np.empty((0, 0, 0))

    def _inputs(self, rows: pd.DataFrame) -> Array:
        """Shape (rows, leads, inputs). Only the ICON-D2 sum differs between leads."""
        last = rows[contract.KD_LAST_CM].to_numpy(np.float64)
        same_for_all_leads = np.column_stack(
            [
                np.ones(len(rows)),
                last - rows[contract.KD_BASE_30D_CM].to_numpy(np.float64),
                np.nan_to_num(level_change(rows, LANGENBERG)),
                np.nan_to_num(level_change(rows, NIERENHOF)),
                radar_sum(rows, self._cell_counts, 0, RECENT_RADAR_HOURS),
                radar_sum(rows, self._cell_counts, RECENT_RADAR_HOURS, OLD_RADAR_HOURS),
            ]
        )
        icon_columns = contract.lead_columns(contract.ICON_MEAN, self._leads)
        icon_sum = np.cumsum(rows[icon_columns].to_numpy(np.float64), axis=1)
        repeated = np.repeat(same_for_all_leads[:, np.newaxis, :], self._leads, axis=1)
        return np.concatenate([repeated, icon_sum[:, :, np.newaxis]], axis=2)

    def _groups(self, rows: pd.DataFrame) -> list[Mask]:
        """Row masks, one per coefficient set."""
        if not self._split:
            return [np.ones(len(rows), dtype=bool)]
        kupferdreh_rise = rows[contract.KD_LAST_CM] - rows[f"{KUPFERDREH}_lag_{CHANGE_HOURS}"]
        langenberg_rise = pd.Series(level_change(rows, LANGENBERG), index=rows.index)
        rising = (
            (kupferdreh_rise.fillna(0) > RISING_CM) | (langenberg_rise.fillna(0) > RISING_CM)
        ).to_numpy()
        return [rising, ~rising]

    def fit(self, train: pd.DataFrame) -> None:
        inputs = self._inputs(train)
        target_columns = contract.lead_columns(contract.TARGET, self._leads)
        targets = train[target_columns].to_numpy(np.float64)
        change_cm = targets - train[[contract.KD_LAST_CM]].to_numpy(np.float64)
        coefficient_sets = []
        for group in self._groups(train):
            per_lead = []
            for lead in range(self._leads):
                lead_inputs = inputs[:, lead, :]
                usable = (
                    group & np.isfinite(change_cm[:, lead]) & np.isfinite(lead_inputs).all(axis=1)
                )
                solution, *_ = np.linalg.lstsq(
                    lead_inputs[usable], change_cm[usable, lead], rcond=None
                )
                per_lead.append(solution)
            coefficient_sets.append(per_lead)
        self.coefficients = np.array(coefficient_sets)

    def predict(self, rows: pd.DataFrame) -> Array:
        inputs = self._inputs(rows)
        change_cm = np.zeros((len(rows), self._leads))
        for group, per_lead in zip(self._groups(rows), self.coefficients, strict=True):
            change_cm[group] = np.einsum("rli,li->rl", inputs[group], per_lead)
        # A missing input gives a NaN change: fall back to persistence.
        change_cm[~np.isfinite(change_cm)] = 0.0
        last = rows[[contract.KD_LAST_CM]].to_numpy(np.float64)
        prediction: Array = last + change_cm
        return prediction
