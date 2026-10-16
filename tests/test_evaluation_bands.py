import numpy as np
import pandas as pd
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import bands, contract

CONFIG = load_config()
LEADS = CONFIG.evaluation.leads_hours


def predictions(dataset: pd.DataFrame, models: tuple[str, ...] = ("m",)) -> pd.DataFrame:
    """Last level plus a seeded wobble per lead, with the fold of each issue time."""
    rng = np.random.default_rng(1)
    fold_of = pd.Series("", index=dataset.index)
    for fold in contract.FOLDS:
        fold_of[contract.holdout_rows(dataset, fold).index] = fold.name
    frames = []
    for model in models:
        for lead in range(1, LEADS + 1):
            change = 0.0 if model == "persistence" else rng.normal(0, 3, len(dataset))
            frames.append(
                pd.DataFrame(
                    {
                        "issued_at": dataset[contract.ISSUED_AT],
                        "lead": lead,
                        "model": model,
                        "fold": fold_of,
                        "prediction": dataset[contract.KD_LAST_CM] + change,
                        "target": dataset[f"target_{lead}"],
                    }
                )
            )
    rows = pd.concat(frames, ignore_index=True)
    return rows[rows["fold"] != ""]


def test_calibration_lines_up_forecasts_inputs_and_truth_per_issue_time() -> None:
    dataset = eval_dataset(first_issue="2024-12-20T00:30Z", hours=5 * 24)
    rows = bands.calibration(predictions(dataset), dataset, LEADS)
    assert rows.levels.shape == rows.targets.shape == (len(dataset), LEADS)
    np.testing.assert_array_equal(rows.targets[:, 0], dataset["target_1"])
    np.testing.assert_array_equal(rows.last_level, dataset[contract.KD_LAST_CM])
    np.testing.assert_allclose(
        rows.icon_to_lead[:, 1], dataset["icon_mean_1"] + dataset["icon_mean_2"]
    )
    assert set(rows.folds) == {"F1"}


def test_scores_each_fold_with_a_table_fitted_on_the_folds_before() -> None:
    # Twelve days of F1, then four of F2: only F2 is scored.
    dataset = eval_dataset(first_issue="2024-12-20T00:30Z", hours=16 * 24)
    scores = bands.band_scores(predictions(dataset, ("persistence", "m")), dataset, CONFIG)
    assert list(scores.columns) == list(bands.BAND_SCORE_COLUMNS)
    assert set(scores["model"]) == {"m"}
    assert set(scores["fold"]) == {"F2", bands.ALL}
    assert set(scores["coverage_percent"]) == set(CONFIG.bands.coverages_percent)
    assert scores["lead"].max() == LEADS
    pooled = scores[(scores["fold"] == "F2") & (scores["situation"] == bands.ALL)]
    assert pooled["coverage"].between(0, 1).all()
    # Wider coverage, wider band.
    width = pooled.groupby("coverage_percent")["width"].mean()
    assert width.is_monotonic_increasing
