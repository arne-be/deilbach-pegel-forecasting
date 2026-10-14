"""Scores per model, fold, subset and lead, and a day bootstrap of the gain over persistence.

Input is a predictions frame in `contract.PREDICTION_COLUMNS` with the model "persistence" in
it: skill and the bootstrap compare every model with persistence on the same rows.
"""

import numpy as np
import pandas as pd

from pegel.config import EvaluationSettings
from pegel.evaluation import contract

PERSISTENCE = "persistence"
ALL_FOLDS = "all"

SUBSET_ALL = "all"
# Cleaned level above high_water_cm at the issue time or at the target.
SUBSET_HIGH_WATER = "high_water"
# The same judged by the raw level, and scored against the raw target.
SUBSET_HIGH_WATER_RAW = "high_water_raw"

_KEYS = [contract.ISSUED_AT, "lead"]


def with_truth(predictions: pd.DataFrame, dataset: pd.DataFrame, leads: int) -> pd.DataFrame:
    """Predictions joined with the last levels at the issue time and the raw target."""
    raw = dataset.melt(
        id_vars=[contract.ISSUED_AT],
        value_vars=contract.lead_columns(contract.TARGET_RAW, leads),
        var_name="lead",
        value_name=contract.TARGET_RAW,
    )
    raw["lead"] = raw["lead"].str.rsplit("_", n=1).str[1].astype(int)
    last = dataset[[contract.ISSUED_AT, contract.KD_LAST_CM, contract.KD_LAST_RAW_CM]]
    truth = raw.merge(last, on=contract.ISSUED_AT)
    return predictions.merge(truth, on=_KEYS, how="left", validate="many_to_one")


def high_water(rows: pd.DataFrame, threshold_cm: float, *, raw: bool = False) -> pd.Series:
    """Rows whose level is above the threshold at the issue time or at the target."""
    last, target = (
        (contract.KD_LAST_RAW_CM, contract.TARGET_RAW)
        if raw
        else (contract.KD_LAST_CM, contract.TARGET)
    )
    return (rows[last] > threshold_cm) | (rows[target] > threshold_cm)


def _with_persistence(rows: pd.DataFrame) -> pd.DataFrame:
    if PERSISTENCE not in set(rows["model"]):
        raise ValueError(f"predictions have no model {PERSISTENCE!r} to compare against")
    reference = rows.loc[rows["model"] == PERSISTENCE, [*_KEYS, "prediction"]]
    reference = reference.rename(columns={"prediction": "persistence"})
    return rows.merge(reference, on=_KEYS, how="left", validate="many_to_one")


def _errors(rows: pd.DataFrame, target: str) -> pd.DataFrame:
    """Signed errors against `target`, with the persistence error on rows where it exists.

    Rows without a prediction or a target are left out, so skill compares on rows where both
    the model and persistence have a prediction and a target.
    """
    rows = rows[rows[target].notna() & rows["prediction"].notna()]
    error = rows["prediction"] - rows[target]
    persistence_error = (rows["persistence"] - rows[target]).abs()
    paired = persistence_error.notna()
    return pd.DataFrame(
        {
            "model": rows["model"],
            "fold": rows["fold"],
            "lead": rows["lead"],
            "error": error,
            "abs_error": error.abs(),
            "squared_error": error**2,
            "paired_abs_error": error.abs().where(paired),
            "persistence_abs_error": persistence_error,
        }
    )


def _aggregate(errors: pd.DataFrame) -> pd.DataFrame:
    both_folds = pd.concat([errors, errors.assign(fold=ALL_FOLDS)])
    grouped = both_folds.groupby(["model", "fold", "lead"], sort=True)
    scores = grouped.agg(
        n=("error", "size"),
        mae=("abs_error", "mean"),
        mse=("squared_error", "mean"),
        bias=("error", "mean"),
        paired_mae=("paired_abs_error", "mean"),
        persistence_mae=("persistence_abs_error", "mean"),
    ).reset_index()
    scores["rmse"] = np.sqrt(scores["mse"])
    scores["skill"] = 1 - scores["paired_mae"] / scores["persistence_mae"]
    return scores


def scores(
    predictions: pd.DataFrame, dataset: pd.DataFrame, settings: EvaluationSettings
) -> pd.DataFrame:
    """MAE, RMSE, bias (prediction - target) and skill in `contract.SCORE_COLUMNS`.

    One row per model, fold (each fold and "all" pooled over folds), subset and lead. Missing
    targets are left out. Skill is 1 - MAE / MAE of persistence on the rows both have.
    """
    rows = _with_persistence(with_truth(predictions, dataset, settings.leads_hours))
    threshold = settings.high_water_cm
    subsets = {
        SUBSET_ALL: _errors(rows, contract.TARGET),
        SUBSET_HIGH_WATER: _errors(rows[high_water(rows, threshold)], contract.TARGET),
        SUBSET_HIGH_WATER_RAW: _errors(
            rows[high_water(rows, threshold, raw=True)], contract.TARGET_RAW
        ),
    }
    frames = [_aggregate(errors).assign(subset=name) for name, errors in subsets.items()]
    return pd.concat(frames, ignore_index=True)[list(contract.SCORE_COLUMNS)]


def bootstrap_skill(
    predictions: pd.DataFrame, *, resamples: int = 1000, level: float = 0.9, seed: int = 0
) -> pd.DataFrame:
    """MAE minus the MAE of persistence per model and lead, with a day bootstrap interval.

    Whole UTC days of issue times are drawn with replacement, the same draws for every model
    and lead, so neighbouring hours with correlated errors stay together. Negative is better
    than persistence. Rows without a target, a prediction or a persistence forecast are left out.
    """
    rows = _with_persistence(predictions)
    known = rows[contract.TARGET].notna() & rows["prediction"].notna()
    rows = rows[known & rows["persistence"].notna()]
    rows = rows[rows["model"] != PERSISTENCE]
    difference = (rows["prediction"] - rows[contract.TARGET]).abs() - (
        rows["persistence"] - rows[contract.TARGET]
    ).abs()
    day = rows[contract.ISSUED_AT].dt.tz_convert("UTC").dt.floor("D")
    per_day = (
        pd.DataFrame({"model": rows["model"], "lead": rows["lead"], "day": day, "d": difference})
        .groupby(["day", "model", "lead"])["d"]
        .agg(["sum", "size"])
        .unstack(["model", "lead"], fill_value=0)
    )
    sums = per_day["sum"].to_numpy(dtype=float)
    counts = per_day["size"].to_numpy(dtype=float)
    days = len(per_day)
    draws = np.random.default_rng(seed).integers(0, days, size=(resamples, days))
    # How often each day was drawn in each resample.
    weights = np.zeros((resamples, days))
    np.add.at(weights, (np.arange(resamples)[:, None], draws), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        resampled = (weights @ sums) / (weights @ counts)
    tail = (1 - level) / 2
    columns = per_day["sum"].columns
    return pd.DataFrame(
        {
            "model": columns.get_level_values("model"),
            "lead": columns.get_level_values("lead"),
            "n": counts.sum(axis=0).astype(int),
            "mae_difference": sums.sum(axis=0) / counts.sum(axis=0),
            "low": np.nanquantile(resampled, tail, axis=0),
            "high": np.nanquantile(resampled, 1 - tail, axis=0),
        }
    )
