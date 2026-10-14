"""Trains every model on every fold and collects its predictions for the fold's test period."""

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.evaluation import contract

# A fresh model per fold, so nothing learned on one fold leaks into the next.
ModelFactory = Callable[[EvaluationSettings], contract.Model]


def run(
    dataset: pd.DataFrame, models: Sequence[ModelFactory], settings: EvaluationSettings
) -> pd.DataFrame:
    """One row per issue time, lead, model and fold, in contract.PREDICTION_COLUMNS."""
    leads = settings.leads_hours
    frames = []
    for fold in contract.FOLDS:
        holdout = contract.holdout_rows(dataset, fold)
        # A dataset that ends before a fold (e.g. in tests) has nothing to score there.
        if holdout.empty:
            continue
        train = contract.train_rows(dataset, fold, settings)
        targets = holdout[contract.lead_columns(contract.TARGET, leads)].to_numpy(np.float64)
        for factory in models:
            model = factory(settings)
            model.fit(train)
            predictions = model.predict(holdout)
            if predictions.shape != targets.shape:
                raise ValueError(
                    f"{model.name} predicted shape {predictions.shape} on fold {fold.name}, "
                    f"expected {targets.shape}"
                )
            frames.append(_long_rows(holdout, model.name, fold.name, predictions, targets))
    if not frames:
        raise ValueError("the dataset has no rows in any fold's test period")
    return pd.concat(frames, ignore_index=True)


def _long_rows(
    holdout: pd.DataFrame,
    model_name: str,
    fold_name: str,
    predictions: np.ndarray,
    targets: np.ndarray,
) -> pd.DataFrame:
    count, leads = targets.shape
    return pd.DataFrame(
        {
            "issued_at": np.repeat(holdout[contract.ISSUED_AT].to_numpy(), leads),
            "lead": np.tile(np.arange(1, leads + 1, dtype=np.int64), count),
            "model": model_name,
            "fold": fold_name,
            "prediction": predictions.astype(np.float64).ravel(),
            "target": targets.ravel(),
        },
        columns=list(contract.PREDICTION_COLUMNS),
    )
