"""The models the evaluation runs. Add one line per model."""

from pegel.evaluation.harness import ModelFactory
from pegel.evaluation.models.persistence import Persistence

MODELS: list[ModelFactory] = [
    Persistence,
]
