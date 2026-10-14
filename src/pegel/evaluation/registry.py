"""The models the evaluation runs. Add one line per model."""

from pegel.evaluation.harness import ModelFactory
from pegel.evaluation.models.persistence import Persistence
from pegel.evaluation.models.simple import DampedTrend, Recession, Upstream

MODELS: list[ModelFactory] = [
    Persistence,
    Recession,
    DampedTrend,
    Upstream,
]
