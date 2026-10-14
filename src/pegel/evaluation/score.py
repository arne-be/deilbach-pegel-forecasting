"""Scores a predictions file against its dataset and writes the result tables as CSV.

    uv run python -m pegel.evaluation.score <predictions.parquet> <dataset.parquet> --out <dir>

Analysis only: reads Parquet (pyarrow, `analysis` group), so no job may import it.
"""

import argparse
from pathlib import Path

import pandas as pd

from pegel.config import PegelConfig, load_config
from pegel.evaluation import events, metrics

# Category 2 ("kritisch") is the second alarm level next to the flood threshold.
ALARM_CATEGORY = 2


def alarm_thresholds(config: PegelConfig) -> tuple[float, float]:
    category = next(c for c in config.categories if c.number == ALARM_CATEGORY)
    if category.above_cm is None:
        raise ValueError(f"category {ALARM_CATEGORY} has no lower bound")
    return config.evaluation.flood_cm, category.above_cm


def score_tables(
    predictions: pd.DataFrame, dataset: pd.DataFrame, config: PegelConfig
) -> dict[str, pd.DataFrame]:
    """Every result table by file stem."""
    settings = config.evaluation
    leads = settings.leads_hours
    thresholds = alarm_thresholds(config)
    observed = events.observed_levels(dataset, leads)
    # Only events the predictions cover; the dataset also spans the training periods.
    first = predictions["issued_at"].min()
    last = predictions["issued_at"].max() + pd.Timedelta(hours=leads)
    floods = events.episodes(observed[first:last], settings.flood_cm)
    return {
        "scores": metrics.scores(predictions, dataset, settings),
        "bootstrap": metrics.bootstrap_skill(predictions),
        "events": floods,
        "peaks": events.peak_errors(predictions, floods),
        "alarms": events.alarms(predictions, observed, thresholds),
        "warnings": events.warning_lead_times(predictions, observed, thresholds),
        "lag": events.lag_check(predictions, dataset, leads, settings.high_water_cm),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("predictions", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    predictions = pd.read_parquet(args.predictions)
    dataset = pd.read_parquet(args.dataset)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, table in score_tables(predictions, dataset, load_config()).items():
        table.to_csv(args.out / f"{name}.csv", index=False)


if __name__ == "__main__":
    main()
