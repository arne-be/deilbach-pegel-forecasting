from datetime import UTC, datetime

import pandas as pd
import pytest
from eval_factory import eval_dataset, radar_areas
from pydantic import ValidationError

from pegel.config import load_config
from pegel.evaluation import contract

SETTINGS = load_config().evaluation


def _window_issue_times() -> pd.DataFrame:
    start = pd.Timestamp(SETTINGS.window_first_day, tz="UTC") + pd.Timedelta(minutes=30)
    end = pd.Timestamp(SETTINGS.window_last_day, tz="UTC") + pd.Timedelta(hours=24)
    return pd.DataFrame({contract.ISSUED_AT: pd.date_range(start, end, freq="h", inclusive="left")})


@pytest.mark.parametrize("fold", contract.FOLDS, ids=lambda fold: fold.name)
def test_no_training_target_reaches_into_the_test_period(fold: contract.Fold) -> None:
    train = contract.train_rows(_window_issue_times(), fold, SETTINGS)
    latest_target = train[contract.ISSUED_AT].max() + pd.Timedelta(
        hours=SETTINGS.leads_hours, minutes=SETTINGS.target_tolerance_minutes
    )
    assert latest_target < pd.Timestamp(fold.test_start, tz="UTC")


@pytest.mark.parametrize("fold", contract.FOLDS, ids=lambda fold: fold.name)
def test_training_starts_on_the_window_start(fold: contract.Fold) -> None:
    train = contract.train_rows(_window_issue_times(), fold, SETTINGS)
    assert train[contract.ISSUED_AT].min().date() == SETTINGS.window_first_day


def test_test_period_includes_its_first_and_last_day() -> None:
    fold = contract.FOLDS[0]
    test = contract.holdout_rows(_window_issue_times(), fold)
    days = (test[contract.ISSUED_AT].min().date(), test[contract.ISSUED_AT].max().date())
    assert days == (fold.test_start, fold.test_end)


def test_folds_are_ordered_and_lie_inside_the_window() -> None:
    bounds = [day for fold in contract.FOLDS for day in (fold.test_start, fold.test_end)]
    inside = SETTINGS.window_first_day <= bounds[0] and bounds[-1] <= SETTINGS.window_last_day
    assert inside and bounds == sorted(bounds)


def test_factory_matches_the_dataset_schema() -> None:
    expected = contract.dataset_columns(radar_areas(), SETTINGS.leads_hours)
    assert list(eval_dataset().columns) == expected


def test_dataset_column_names_are_unique() -> None:
    columns = contract.dataset_columns(radar_areas(), SETTINGS.leads_hours)
    assert len(columns) == len(set(columns))


def test_manifest_rejects_a_connection_string() -> None:
    with pytest.raises(ValidationError):
        contract.Manifest(
            window_first_day=SETTINGS.window_first_day,
            window_last_day=SETTINGS.window_last_day,
            config={},
            git_commit="abc",
            row_count=0,
            sha256="0",
            created_at=datetime(2026, 10, 14, tzinfo=UTC),
            database="postgresql://user:secret@host/db",
        )
