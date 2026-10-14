"""The models the evaluation runs. Add one line per model."""

from functools import partial

from pegel.evaluation.harness import ModelFactory
from pegel.evaluation.models.persistence import Persistence
from pegel.evaluation.models.ridge import Ridge
from pegel.evaluation.models.simple import DampedTrend, Recession, Upstream

MODELS: list[ModelFactory] = [
    Persistence,
    Recession,
    DampedTrend,
    Upstream,
    partial(Ridge, kind="level"),
    partial(Ridge, kind="change"),
    partial(Ridge, kind="level", with_icon=False),
    partial(Ridge, kind="change", with_icon=False),
]
