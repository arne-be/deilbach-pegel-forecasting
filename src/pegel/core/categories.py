"""Maps a water level to its flood category."""

from collections.abc import Sequence

from pegel.config import Category


def category_for(level_m: float, categories: Sequence[Category]) -> Category:
    """Return the highest category whose bound the level is strictly above.

    Expects categories ascending with an unbounded first one, as the config validates.
    A level exactly on a bound stays in the lower category (1.00 m is still category 1).
    """
    if not categories:
        raise ValueError("categories must not be empty")
    matching = categories[0]
    for category in categories[1:]:
        if category.above_m is None or level_m <= category.above_m:
            break
        matching = category
    return matching
