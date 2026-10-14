"""The models the evaluation runs. Add one line per model."""

from functools import partial

from pegel.evaluation.harness import ModelFactory
from pegel.evaluation.models.persistence import Persistence
from pegel.evaluation.models.rain_change import RainChange

MODELS: list[ModelFactory] = [
    Persistence,
    RainChange,
    partial(RainChange, split=True),
]
