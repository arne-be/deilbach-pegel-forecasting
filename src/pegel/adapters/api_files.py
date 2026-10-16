"""The API's response files in the data bucket: written by the hourly run, read by the API."""

from collections.abc import Callable

import boto3
from botocore.config import Config

FORECAST_KEY = "api/forecast.json"
RECENT_KEY = "api/recent.json"

# Returns the file's bytes; raises on any error, including a missing file.
ReadFile = Callable[[str], bytes]
WriteFile = Callable[[str, bytes], None]

# Short: a stalled S3 should cost a request or the hourly run seconds (2 tries, about 16 s).
_S3_CONFIG = Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2})


def s3_reader(bucket: str) -> ReadFile:
    client = boto3.client("s3", config=_S3_CONFIG)

    def read(key: str) -> bytes:
        return bytes(client.get_object(Bucket=bucket, Key=key)["Body"].read())

    return read


def s3_writer(bucket: str) -> WriteFile:
    client = boto3.client("s3", config=_S3_CONFIG)

    def write(key: str, body: bytes) -> None:
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")

    return write
