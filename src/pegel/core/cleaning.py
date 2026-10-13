"""Live outlier filter for the gauge level: a Kalman filter on level and trend.

It sees one reading at a time, oldest first, and decides at once, using only that reading
and the ones it accepted before. That is all the hourly job has when a reading arrives, and
outliers never enter the state, so a spike can't drag the reference along. Why this filter
and these parameters: `analysis/outliers/README.md` on PR #34 (docs/outlier-exploration).

Three rules besides the Kalman gate:
- The allowed change grows with the time since the last accepted reading only up to
  `cap_hours`; otherwise a sensor stuck at an error value would be accepted after a while.
- A reading that fails the gate is still accepted if the level was there within the last
  `recent_hours`: that is the river coming back after a spike slipped through. The readings
  in between are forgotten, so a repeat of the spike isn't "seen recently".
- After `restart_after_hours` without an accepted reading the filter starts over, so a real
  change during a data gap can't lock it out.
"""

import math
from collections.abc import Sequence
from datetime import datetime

from pegel.config import CleaningSettings
from pegel.core.series import SeriesValue

SECONDS_PER_HOUR = 3600.0


class LevelFilter:
    """Decides reading by reading whether it is an outlier. Feed readings oldest first."""

    def __init__(self, settings: CleaningSettings) -> None:
        self.settings = settings
        self.measurement_variance = settings.measurement_noise_cm**2
        self.recent: list[tuple[datetime, float]] = []  # accepted (time, value)
        self.last_at: datetime | None = None
        # State: level and trend (cm/h), and its covariance [[p00, p01], [p10, p11]].
        self.level = 0.0
        self.trend = 0.0
        self.p00 = self.p01 = self.p10 = self.p11 = 0.0

    def is_outlier(self, at: datetime, value: float) -> bool:
        if self.last_at is None or _hours(at, self.last_at) > self.settings.restart_after_hours:
            self.recent.clear()
            self._restart(value)
        elif self._fits(at, value):
            self._update(at, value)
        elif self._returned_to_recent_level(at, value):
            self._restart(value)
        else:
            return True
        self.recent.append((at, value))
        self.last_at = at
        return False

    def _returned_to_recent_level(self, at: datetime, value: float) -> bool:
        recent_hours = self.settings.recent_hours
        self.recent = [(time, old) for time, old in self.recent if _hours(at, time) <= recent_hours]
        for index in range(len(self.recent) - 1, -1, -1):
            if abs(self.recent[index][1] - value) <= self.settings.recent_tolerance_cm:
                del self.recent[index + 1 :]
                return True
        return False

    def _predict(self, at: datetime) -> tuple[float, float, float, float, float, float]:
        """Predicted level, trend and covariance (p00, p01, p10, p11) at `at`."""
        assert self.last_at is not None
        # Capped: the trend isn't extrapolated, and the uncertainty doesn't grow, beyond it.
        g = min(max(_hours(at, self.last_at), 1.0), self.settings.cap_hours)
        q = self.settings.trend_noise
        # F P F^T + Q with F = [[1, g], [0, 1]], Q = q [[g^3/3, g^2/2], [g^2/2, g]]
        p00 = self.p00 + g * self.p10 + g * (self.p01 + g * self.p11) + q * (g**3 / 3)
        p01 = self.p01 + g * self.p11 + q * (g**2 / 2)
        p10 = self.p10 + g * self.p11 + q * (g**2 / 2)
        p11 = self.p11 + q * g
        return self.level + g * self.trend, self.trend, p00, p01, p10, p11

    def _fits(self, at: datetime, value: float) -> bool:
        level, _, p00, _, _, _ = self._predict(at)
        spread = p00 + self.measurement_variance
        limit = max(self.settings.gate_sigmas * math.sqrt(spread), self.settings.min_deviation_cm)
        return abs(value - level) <= limit

    def _update(self, at: datetime, value: float) -> None:
        level, trend, p00, p01, p10, p11 = self._predict(at)
        innovation_variance = p00 + self.measurement_variance
        gain_level, gain_trend = p00 / innovation_variance, p10 / innovation_variance
        residual = value - level
        self.level = level + gain_level * residual
        self.trend = trend + gain_trend * residual
        self.p00, self.p01 = p00 - gain_level * p00, p01 - gain_level * p01
        self.p10, self.p11 = p10 - gain_trend * p00, p11 - gain_trend * p01

    def _restart(self, value: float) -> None:
        self.level, self.trend = value, 0.0
        self.p00, self.p01 = self.measurement_variance, 0.0
        self.p10, self.p11 = 0.0, self.settings.trend_noise


def outlier_flags(values: Sequence[SeriesValue], settings: CleaningSettings) -> list[bool]:
    """Runs a fresh filter over `values` (oldest first); True marks an outlier."""
    level_filter = LevelFilter(settings)
    return [level_filter.is_outlier(value.valid_at, value.value) for value in values]


def _hours(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / SECONDS_PER_HOUR
