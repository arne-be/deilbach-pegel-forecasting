"""The models the evaluation runs. Add one line per model.

Retired models are listed in docs/models.md and stay in git history.
"""

from functools import partial

from pegel.evaluation.harness import ModelFactory
from pegel.evaluation.models.curated import RAIN_CHANGE_V2, RIDGE_V2, RIDGE_V2_ALPHA, CuratedChange
from pegel.evaluation.models.persistence import Persistence
from pegel.evaluation.models.residual import ResidualTrees
from pegel.evaluation.models.simple import Upstream

MODELS: list[ModelFactory] = [
    Persistence,
    Upstream,
    partial(CuratedChange, name="rain_change:v2:split", inputs=RAIN_CHANGE_V2, split=True),
    partial(
        CuratedChange, name="ridge:change:v2", inputs=RIDGE_V2, split=True, alpha=RIDGE_V2_ALPHA
    ),
    partial(ResidualTrees, name="lgbm_residual:v1"),
    partial(ResidualTrees, name="lgbm_residual:v1:linear", linear_tree=True),
]
