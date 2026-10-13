import pytest

from pegel.config import load_config
from pegel.core.categories import category_for

CATEGORIES = load_config().categories


@pytest.mark.parametrize(
    ("level_cm", "expected_number"),
    [
        (100.0, 1),
        (100.1, 2),
        (120.0, 2),
        (120.1, 3),
        (140.0, 3),
        (140.1, 4),
        (180.0, 4),
        (180.1, 5),
        (300.0, 5),
    ],
)
def test_category_applies_strictly_above_its_bound(level_cm: float, expected_number: int) -> None:
    assert category_for(level_cm, CATEGORIES).number == expected_number


@pytest.mark.parametrize("level_cm", [0.0, -10.0, -25.0])
def test_negative_and_zero_levels_are_category_one(level_cm: float) -> None:
    assert category_for(level_cm, CATEGORIES).number == 1


def test_empty_categories_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        category_for(50.0, [])
