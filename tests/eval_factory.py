"""Builds small synthetic evaluation datasets in the schema of pegel.evaluation.contract."""

import numpy as np
import pandas as pd

from pegel.adapters.sources.radolan import load_cells
from pegel.config import config_file, load_config
from pegel.evaluation import contract


def radar_areas() -> list[str]:
    return list(load_cells(config_file(load_config().rain.radar.cells_file)))


def eval_dataset(first_issue: str = "2024-02-01T00:30Z", hours: int = 48) -> pd.DataFrame:
    """Hourly issue times from `first_issue` with seeded random values in every column."""
    leads = load_config().evaluation.leads_hours
    columns = contract.dataset_columns(radar_areas(), leads)
    issued_at = pd.date_range(first_issue, periods=hours, freq="h")
    values = np.random.default_rng(0).uniform(0, 100, size=(hours, len(columns) - 2))
    dataset = pd.DataFrame(values, columns=[c for c in columns if c not in _TIME_COLUMNS])
    dataset[contract.ISSUED_AT] = issued_at
    dataset[contract.KD_LAST_AT] = issued_at - pd.Timedelta(minutes=10)
    return dataset[columns]


_TIME_COLUMNS = (contract.ISSUED_AT, contract.KD_LAST_AT)
