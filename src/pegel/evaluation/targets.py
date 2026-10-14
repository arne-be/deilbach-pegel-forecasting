"""The three target forms a model can learn, and back to levels (docs/decisions/0008).

Arrays have shape (rows, leads); column k-1 is lead k, as in `Model.predict`.
- level: the level at lead k.
- change: the level at lead k minus the last level at the issue time.
- step: the level at lead k minus the level at lead k-1; lead 0 is the last level.
A missing target stays NaN; for step it makes both steps around it NaN.
"""

from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.evaluation import contract

TargetKind = Literal["level", "change", "step"]
Array = npt.NDArray[np.float64]


def to_target(dataset: pd.DataFrame, kind: TargetKind) -> Array:
    leads = sum(1 for c in dataset.columns if c.removeprefix(f"{contract.TARGET}_").isdigit())
    levels = dataset[contract.lead_columns(contract.TARGET, leads)].to_numpy(dtype=float)
    last = _last_level(dataset)
    if kind == "level":
        return levels
    if kind == "change":
        return levels - last
    return np.diff(np.hstack([last, levels]), axis=1)


def from_target(predictions: Array, dataset: pd.DataFrame, kind: TargetKind) -> Array:
    last = _last_level(dataset)
    if kind == "level":
        return predictions
    if kind == "change":
        return predictions + last
    return last + np.cumsum(predictions, axis=1)


def _last_level(dataset: pd.DataFrame) -> Array:
    return dataset[[contract.KD_LAST_CM]].to_numpy(dtype=float)
