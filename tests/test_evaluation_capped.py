import numpy as np
import pandas as pd
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.models.capped import capped
from pegel.evaluation.models.simple import Upstream

SETTINGS = load_config().evaluation
TARGETS = contract.lead_columns(contract.TARGET, SETTINGS.leads_hours)


class Recorder:
    name = "recorder"

    def fit(self, train: pd.DataFrame) -> None:
        self.train = train

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        return np.zeros((len(rows), SETTINGS.leads_hours))


def test_capped_training_drops_rows_above_the_cap_only() -> None:
    dataset = eval_dataset(hours=10)
    dataset[[contract.KD_LAST_CM, *TARGETS]] = 50.0
    dataset.loc[1, contract.KD_LAST_CM] = 101.0
    dataset.loc[2, TARGETS[-1]] = 100.5
    dataset.loc[3, TARGETS[0]] = 100.0  # at the cap: kept
    dataset.loc[4, TARGETS[5]] = np.nan  # missing: kept
    recorder = Recorder()
    model = capped(lambda _: recorder, 100.0)(SETTINGS)
    model.fit(dataset)
    assert model.name == "recorder:cap100"
    assert list(recorder.train.index) == [0, 3, 4, 5, 6, 7, 8, 9]


def test_capped_model_predicts_like_the_model_fitted_on_the_kept_rows() -> None:
    dataset = eval_dataset(hours=100)
    dataset.loc[:29, TARGETS[3]] = 150.0
    capped_model = capped(Upstream, 100.0)(SETTINGS)
    capped_model.fit(dataset)
    plain = Upstream(SETTINGS)
    plain.fit(dataset.iloc[30:])
    rows = dataset.drop(columns=TARGETS)
    np.testing.assert_array_equal(capped_model.predict(rows), plain.predict(rows))
    uncapped = Upstream(SETTINGS)
    uncapped.fit(dataset)
    assert not np.allclose(capped_model.predict(rows), uncapped.predict(rows))
