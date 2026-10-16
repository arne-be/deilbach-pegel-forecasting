"""Loads the trained model the page shows from the data bucket (written by `pegel train-model`)."""

import json
import os
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.config import Config

from pegel.config import PegelConfig
from pegel.core.bands import BandTable
from pegel.evaluation import contract
from pegel.evaluation.models.curated import CuratedChange

# Short, so a stalled S3 costs the hourly run seconds, not minutes.
_S3_CONFIG = Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 3})


@dataclass(frozen=True)
class TrainedModel:
    model: contract.Model
    # None for files written before bands existed: the forecast then has none.
    bands: BandTable | None


def load_model_from_s3(config: PegelConfig) -> TrainedModel:
    """The model at `forecast.model_file` in the bucket named by MODEL_BUCKET."""
    bucket = os.environ.get("MODEL_BUCKET")
    if not bucket or not config.forecast.model_file:
        raise RuntimeError("MODEL_BUCKET and forecast.model_file must be set")
    client = boto3.client("s3", config=_S3_CONFIG)
    response = client.get_object(Bucket=bucket, Key=config.forecast.model_file)
    return model_from_file(json.loads(response["Body"].read()), config)


def model_from_file(data: dict[str, Any], config: PegelConfig) -> TrainedModel:
    """The model and band table of a stored file; refuses one that isn't the configured model."""
    name = data["model"]["name"]
    if name != config.forecast.model:
        raise ValueError(f"model file holds {name!r}, config wants {config.forecast.model!r}")
    model = CuratedChange.from_dict(data["model"], config.evaluation)
    bands = BandTable.from_dict(data["bands"]) if "bands" in data else None
    return TrainedModel(model, bands)
