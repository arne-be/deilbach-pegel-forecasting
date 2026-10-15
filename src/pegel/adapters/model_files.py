"""Loads the trained model the page shows from the data bucket (written by `pegel train-model`)."""

import json
import os
from typing import Any

import boto3
from botocore.config import Config

from pegel.config import PegelConfig
from pegel.evaluation.models.curated import CuratedChange

# Short, so a stalled S3 costs the hourly run seconds, not minutes.
_S3_CONFIG = Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 3})


def load_model_from_s3(config: PegelConfig) -> CuratedChange:
    """The model at `forecast.model_file` in the bucket named by MODEL_BUCKET."""
    bucket = os.environ.get("MODEL_BUCKET")
    if not bucket or not config.forecast.model_file:
        raise RuntimeError("MODEL_BUCKET and forecast.model_file must be set")
    client = boto3.client("s3", config=_S3_CONFIG)
    response = client.get_object(Bucket=bucket, Key=config.forecast.model_file)
    return model_from_file(json.loads(response["Body"].read()), config)


def model_from_file(data: dict[str, Any], config: PegelConfig) -> CuratedChange:
    """The model of a stored file; refuses one that isn't the configured model."""
    name = data["model"]["name"]
    if name != config.forecast.model:
        raise ValueError(f"model file holds {name!r}, config wants {config.forecast.model!r}")
    return CuratedChange.from_dict(data["model"], config.evaluation)
