import pytest

from pegel.config import load_config
from pegel.core.categories import category_for

CATEGORIES = load_config().categories


@pytest.mark.parametrize(
    ("level_m", "expected_number"),
    [
        (1.00, 1),
        (1.001, 2),
        (1.20, 2),
        (1.201, 3),
        (1.40, 3),
        (1.401, 4),
        (1.80, 4),
        (1.801, 5),
        (3.0, 5),
    ],
)
def test_category_applies_strictly_above_its_bound(level_m: float, expected_number: int) -> None:
    assert category_for(level_m, CATEGORIES).number == expected_number


@pytest.mark.parametrize("level_m", [0.0, -0.1, -0.25])
def test_negative_and_zero_levels_are_category_one(level_m: float) -> None:
    assert category_for(level_m, CATEGORIES).number == 1


def test_empty_categories_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        category_for(0.5, [])
