"""Uncertainty bands in the evaluation: calibration rows from out-of-sample predictions, and
scores of bands calibrated only on the folds before the one they are tested on."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.config import PegelConfig
from pegel.core import bands, features
from pegel.evaluation import contract, metrics

ALL = "all"
BAND_SCORE_COLUMNS = (
    "model",
    "fold",
    "situation",
    "lead",
    "coverage_percent",
    "n",
    "coverage",
    "width",
    "interval_score",
)

Array = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Calibration:
    """One row per issue time; level, rain and target arrays are (rows, leads)."""

    folds: npt.NDArray[np.str_]
    last_level: Array
    levels: Array
    icon_to_lead: Array
    targets: Array

    def take(self, mask: npt.NDArray[np.bool_]) -> "Calibration":
        return Calibration(
            self.folds[mask],
            self.last_level[mask],
            self.levels[mask],
            self.icon_to_lead[mask],
            self.targets[mask],
        )


def calibration(predictions: pd.DataFrame, dataset: pd.DataFrame, leads: int) -> Calibration:
    """The out-of-sample forecasts of one model with their inputs and truth."""
    if predictions["model"].nunique() != 1:
        raise ValueError("calibration takes the predictions of one model")
    wide = predictions.pivot(index=contract.ISSUED_AT, columns="lead", values="prediction")
    wide = wide.reindex(columns=range(1, leads + 1)).sort_index()
    folds = predictions.groupby(contract.ISSUED_AT)["fold"].first().reindex(wide.index)
    rows = dataset.set_index(contract.ISSUED_AT).loc[wide.index].reset_index()
    return Calibration(
        folds=folds.to_numpy(str),
        last_level=rows[contract.KD_LAST_CM].to_numpy(np.float64),
        levels=wide.to_numpy(np.float64),
        icon_to_lead=features.icon_cumulative(rows, leads),
        targets=rows[contract.lead_columns(contract.TARGET, leads)].to_numpy(np.float64),
    )


def fit_table(
    predictions: pd.DataFrame, dataset: pd.DataFrame, config: PegelConfig
) -> bands.BandTable:
    """The band table of one model from all its out-of-sample predictions, for the live job."""
    rows = calibration(predictions, dataset, config.evaluation.leads_hours)
    return bands.fit_band_table(*_fit_inputs(rows), config.bands)


def band_scores(
    predictions: pd.DataFrame, dataset: pd.DataFrame, config: PegelConfig
) -> pd.DataFrame:
    """Coverage, mean width and interval score per model, fold, situation, lead and coverage.

    Each fold's bands are fitted on the folds before it, as a live table only knows the past;
    the first fold has none and is not scored. Fold and situation "all" pool the others.
    Persistence is left out.
    """
    leads = config.evaluation.leads_hours
    fold_names = [fold.name for fold in contract.FOLDS]
    frames = []
    # Persistence never changes the level, so its band is only the fallback table.
    scored_models = predictions[predictions["model"] != metrics.PERSISTENCE]
    for model, model_predictions in scored_models.groupby("model", sort=True):
        rows = calibration(model_predictions, dataset, leads)
        for position, fold in enumerate(fold_names[1:], start=1):
            test = rows.take(rows.folds == fold)
            if len(test.folds) == 0:
                continue
            table = bands.fit_band_table(
                *_fit_inputs(rows.take(np.isin(rows.folds, fold_names[:position]))),
                config.bands,
            )
            frames.append(_scored_rows(table, test, config).assign(model=model, fold=fold))
    if not frames:
        return pd.DataFrame(columns=list(BAND_SCORE_COLUMNS))
    scored = pd.concat(frames, ignore_index=True)
    return _aggregate(scored)


def _fit_inputs(rows: Calibration) -> tuple[Array, Array, Array, Array]:
    return rows.levels, rows.last_level, rows.icon_to_lead, rows.targets


def _scored_rows(table: bands.BandTable, test: Calibration, config: PegelConfig) -> pd.DataFrame:
    """One row per issue time, lead and coverage with a target."""
    bounds = bands.band_bounds(table, test.levels, test.last_level, test.icon_to_lead, config.bands)
    situation = np.repeat(
        bands.situations(test.levels, test.last_level, test.icon_to_lead, config.bands),
        test.levels.shape[1],
    )
    lead = np.tile(np.arange(1, test.levels.shape[1] + 1), len(test.levels))
    truth = test.targets.ravel()
    known = np.isfinite(truth)
    frames = []
    for coverage, (lower, upper) in bounds.items():
        low, high = lower.ravel(), upper.ravel()
        miss_weight = 2 / (1 - coverage / 100)
        interval_score = (
            (high - low)
            + miss_weight * np.maximum(low - truth, 0)
            + miss_weight * np.maximum(truth - high, 0)
        )
        frames.append(
            pd.DataFrame(
                {
                    "situation": situation[known],
                    "lead": lead[known],
                    "coverage_percent": coverage,
                    "covered": ((low <= truth) & (truth <= high))[known],
                    "width": (high - low)[known],
                    "interval_score": interval_score[known],
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _aggregate(scored: pd.DataFrame) -> pd.DataFrame:
    pooled = pd.concat([scored, scored.assign(fold=ALL)])
    pooled = pd.concat([pooled, pooled.assign(situation=ALL)])
    grouped = pooled.groupby(["model", "fold", "situation", "lead", "coverage_percent"])
    result = grouped.agg(
        n=("covered", "size"),
        coverage=("covered", "mean"),
        width=("width", "mean"),
        interval_score=("interval_score", "mean"),
    ).reset_index()
    return result[list(BAND_SCORE_COLUMNS)]
