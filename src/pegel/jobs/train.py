"""`pegel train-model`: fits a registered model on the window and saves it as one JSON file,
with the uncertainty band table from its out-of-sample errors.

Reads the jobs database read-only, with the same dataset build as `pegel build-eval-set`.
"""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import boto3
import numpy as np
import pandas as pd

from pegel.config import EvaluationSettings, PegelConfig
from pegel.core.bands import BandTable
from pegel.evaluation import bands, contract, harness
from pegel.evaluation.models.curated import CuratedChange
from pegel.evaluation.predict import selected_models
from pegel.jobs.eval_set import (
    build_dataset,
    connect_read_only,
    coverage_report,
    database_label,
    git_commit,
)

S3_PREFIX = "models/"


def trainable_model(name: str, settings: EvaluationSettings) -> CuratedChange:
    """The registered model with this name, set up as in the evaluation; only these can be saved."""
    try:
        (factory,) = selected_models([name], settings)
    except ValueError as error:
        raise SystemExit(f"error: {error}") from None
    model = factory(settings)
    if not isinstance(model, CuratedChange):
        raise SystemExit(f"error: {name} can't be saved; only curated change models can")
    return model


def in_sample_mae(model: CuratedChange, rows: pd.DataFrame, leads: int) -> list[float | None]:
    """Mean absolute error per lead on the training rows; None where no row has a target."""
    targets = rows[contract.lead_columns(contract.TARGET, leads)].to_numpy(np.float64)
    errors = np.abs(model.predict(rows) - targets)
    has_target = np.isfinite(errors).any(axis=0)
    return [
        float(np.nanmean(errors[:, lead])) if has_target[lead] else None for lead in range(leads)
    ]


def out_of_sample_bands(model_name: str, rows: pd.DataFrame, config: PegelConfig) -> BandTable:
    """The band table from the model's errors on each fold's test period, trained as in the
    evaluation on the rows before it, never on the rows it is scored on."""
    predictions = harness.run(
        rows, [lambda settings: trainable_model(model_name, settings)], config.evaluation
    )
    return bands.fit_table(predictions, rows, config)


def model_document(
    model: CuratedChange,
    band_table: BandTable,
    rows: pd.DataFrame,
    config: PegelConfig,
    first_day: date,
    last_day: date,
    commit: str,
    database: str,
    created_at: datetime,
) -> dict[str, Any]:
    """The fitted model and how it was trained, as plain JSON values."""
    return {
        "model": model.to_dict(),
        "bands": band_table.to_dict(),
        "trained": {
            "window_first_day": first_day.isoformat(),
            "window_last_day": last_day.isoformat(),
            "row_count": len(rows),
            "git_commit": commit,
            "created_at": created_at.isoformat(),
            "database": database,
            "config": config.model_dump(mode="json"),
            # A sanity check on the training rows, not the evaluation.
            "in_sample_mae_cm_per_lead": in_sample_mae(model, rows, config.evaluation.leads_hours),
        },
    }


def file_name(model_name: str, created_at: datetime) -> str:
    return f"{model_name.replace(':', '-')}-{created_at.astimezone(UTC):%Y%m%dT%H%MZ}.json"


def write_new(path: Path, document: dict[str, Any]) -> None:
    """Writes the JSON file; refuses if it exists, so a saved model is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(json.dumps(document, indent=2, allow_nan=False) + "\n")
    except FileExistsError:
        raise SystemExit(f"error: {path} exists; a saved model is never overwritten") from None


def upload(path: Path, bucket: str) -> str:
    """Uploads the file to `models/<file name>`; refuses if the key exists. Returns the key."""
    key = S3_PREFIX + path.name
    client = boto3.client("s3")
    try:
        client.put_object(Bucket=bucket, Key=key, Body=path.read_bytes(), IfNoneMatch="*")
    except client.exceptions.ClientError as error:
        if error.response["Error"]["Code"] == "PreconditionFailed":
            raise SystemExit(f"error: s3://{bucket}/{key} exists; never overwritten") from None
        raise
    return key


def run(
    config: PegelConfig,
    database_url: str,
    model_name: str,
    first_day: date,
    last_day: date,
    out_dir: Path,
    bucket: str | None,
) -> None:
    """Builds the dataset read-only, fits the model on all its rows, writes and uploads it."""
    # Checked before connecting, so a wrong name or a git failure costs no read of the database.
    model = trainable_model(model_name, config.evaluation)
    commit = git_commit()
    with connect_read_only(database_url) as conn:
        rows, _ = build_dataset(conn, config, first_day, last_day)
        database = database_label(conn)
    print(coverage_report(rows))
    model.fit(rows)
    band_table = out_of_sample_bands(model.name, rows, config)
    created_at = datetime.now(UTC)
    document = model_document(
        model, band_table, rows, config, first_day, last_day, commit, database, created_at
    )
    path = out_dir / file_name(model.name, created_at)
    write_new(path, document)
    print(f"Trained {model.name} on {len(rows)} rows ({first_day} to {last_day}, {database})")
    print(f"Wrote {path}")
    if bucket is None:
        return
    key = upload(path, bucket)
    print(f"Uploaded s3://{bucket}/{key}")
    print(f'Set "forecast.model_file": "{key}" in config/pegel.json to use it.')
