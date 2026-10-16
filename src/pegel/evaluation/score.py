"""Scores a predictions file against its dataset and writes the result tables as CSV.

    uv run --group analysis python -m pegel.evaluation.score \
        <predictions.parquet> <dataset.parquet> --out <dir>

Analysis only: reads Parquet (pyarrow, `analysis` group), so no job may import it.
"""

import argparse
from pathlib import Path

import pandas as pd

from pegel.config import PegelConfig, load_config
from pegel.evaluation import bands, events, flood_scores, metrics


def score_tables(
    predictions: pd.DataFrame, dataset: pd.DataFrame, config: PegelConfig
) -> dict[str, pd.DataFrame]:
    """Every result table by file stem."""
    settings = config.evaluation
    leads = settings.leads_hours
    observed = events.observed_levels(dataset, leads)
    # On the whole window: a test event's previous event or a false alarm's event can be earlier.
    floods = events.flood_events(observed, settings.high_water_cm)
    scored = flood_scores.scored_events(floods, set(predictions["fold"]))
    return {
        "scores": metrics.scores(predictions, dataset, settings),
        "bootstrap": metrics.bootstrap_skill(predictions),
        "events": scored,
        "peaks": flood_scores.flood_peaks(predictions, floods, scored, leads),
        "false_alarms": flood_scores.false_alarms(
            predictions, dataset, floods, settings.high_water_cm, leads
        ),
        "lag": events.lag_check(predictions, dataset, leads, settings.high_water_cm),
        "bands": bands.band_scores(predictions, dataset, config),
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
