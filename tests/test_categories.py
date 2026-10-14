import pytest

from pegel.config import load_config
from pegel.core.categories import category_for

CATEGORIES = load_config().categories


@pytest.mark.parametrize(
    ("level_cm", "expected_number"),
    [
        (145.0, 1),
        (145.1, 2),
        (165.0, 2),
        (165.1, 3),
        (185.0, 3),
        (185.1, 4),
        (225.0, 4),
        (225.1, 5),
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
