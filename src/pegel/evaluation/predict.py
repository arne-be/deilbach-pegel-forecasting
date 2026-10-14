"""Runs every registered model on a frozen dataset and writes predictions.parquet.

    python -m pegel.evaluation.predict <dataset.parquet> --out <dir> [--models a,b]

Analysis only: needs the `analysis` dependency group (pyarrow), never imported by the jobs.
"""

import argparse
import hashlib
import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from pegel.config import EvaluationSettings, load_config
from pegel.evaluation import harness
from pegel.evaluation.contract import Manifest
from pegel.evaluation.registry import MODELS


def manifest_path(dataset: Path) -> Path:
    """`eval.parquet` → `eval.manifest.json`, next to the dataset."""
    return dataset.with_suffix(".manifest.json")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified_manifest(dataset: Path) -> Manifest:
    """The dataset's manifest, after checking that the file is the one it describes."""
    manifest = Manifest.model_validate_json(manifest_path(dataset).read_text())
    if file_sha256(dataset) != manifest.sha256:
        raise ValueError(f"{dataset} does not match the sha256 in its manifest")
    return manifest


def selected_models(
    names: Sequence[str] | None, settings: EvaluationSettings
) -> list[harness.ModelFactory]:
    if names is None:
        return list(MODELS)
    by_name = {factory(settings).name: factory for factory in MODELS}
    unknown = set(names) - by_name.keys()
    if unknown:
        raise ValueError(f"unknown models {sorted(unknown)}; registered: {sorted(by_name)}")
    return [by_name[name] for name in names]


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pegel.evaluation.predict")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", help="comma-separated model names; default: all")
    arguments = parser.parse_args(argv)

    settings = load_config().evaluation
    manifest = verified_manifest(arguments.dataset)
    names = arguments.models.split(",") if arguments.models else None
    factories = selected_models(names, settings)
    predictions = harness.run(pd.read_parquet(arguments.dataset), factories, settings)

    arguments.out.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(arguments.out / "predictions.parquet", index=False)
    run_manifest = {
        "dataset_sha256": manifest.sha256,
        "git_commit": _git_commit(),
        "models": sorted(predictions["model"].unique().tolist()),
        "created_at": datetime.now(UTC).isoformat(),
    }
    (arguments.out / "run.json").write_text(json.dumps(run_manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
