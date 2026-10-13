"""Live outlier filters for the Kupferdreh level.

Each filter sees one reading at a time, oldest first, and decides at once
whether it is an outlier, using only that reading and the ones it accepted
before. That is all the hourly job has when a new reading arrives. Outliers
never enter a filter's state, so a spike can't drag the reference along.

Each filter has its own test for a plausible reading (`fits`). Three rules
are shared, in LiveFilter:
- A jump doesn't become plausible just because time passes: the allowed
  change grows with the time since the last accepted reading, but only up to
  CAP_HOURS. Otherwise a sensor stuck at 2.98 m would be accepted after a
  few hours.
- A reading that fails the test is still accepted if the level was there
  within the last RECENT_HOURS. That is the river coming back after a spike
  slipped through; without this rule the true level would look like an
  impossible fall and be rejected for hours. The readings in between are
  forgotten, so a repeat of the spike isn't "seen recently".
- After LOCK_HOURS without an accepted reading the filter starts over from
  the new reading, so a real change during a data gap can't lock it out.
"""

from collections import deque

import numpy as np
import pandas as pd

CAP_HOURS = 3.0
LOCK_HOURS = 16.0  # longest stuck run seen is 13 h
RECENT_HOURS = 12.0
RECENT_TOLERANCE_M = 0.03

# Step Hampel
HAMPEL_STEPS = 6  # recent accepted steps that form the reference
HAMPEL_K = 4.0
HAMPEL_MIN_RATE_M_PER_H = 0.35  # MAD is ~0 at low water, so set a floor

# Rate envelope: the river rises fast but falls slowly (max ~0.2 m/h seen)
RISE_M_PER_H = 0.4
FALL_M_PER_H = 0.25

# Kalman filter with level and trend
KALMAN_SLOPE_NOISE = 0.005  # (m/h)^2 per hour: how fast the trend may change
KALMAN_MEASUREMENT_NOISE = 0.02**2  # m^2
KALMAN_K = 4.0
KALMAN_MIN_DEVIATION_M = 0.15

# Offline reference from the first comparison: needs to see the return of a
# spike, so it can't decide when a reading arrives
EXCURSION_JUMP_M = 0.25
EXCURSION_MAX_HOURS = 14
EXCURSION_RETURN_FRACTION = 0.25


class LiveFilter:
    """Shared rules; subclasses say what fits and how their state moves on."""

    def __init__(self) -> None:
        self.recent: list[tuple[float, float]] = []  # accepted (hour, value)
        self.last_value = 0.0
        self.last_hour = -np.inf

    def is_outlier(self, hour: float, value: float) -> bool:
        if hour - self.last_hour > LOCK_HOURS:
            self.recent.clear()
            self.restart(value)
        elif self.fits(hour, value):
            self.update(hour, value)
        elif self.returned_to_recent_level(hour, value):
            self.restart(value)
        else:
            return True
        self.recent.append((hour, value))
        self.last_value, self.last_hour = value, hour
        return False

    def returned_to_recent_level(self, hour: float, value: float) -> bool:
        self.recent = [(h, v) for h, v in self.recent if hour - h <= RECENT_HOURS]
        for index in range(len(self.recent) - 1, -1, -1):
            if abs(self.recent[index][1] - value) <= RECENT_TOLERANCE_M:
                del self.recent[index + 1 :]
                return True
        return False

    def hours_since_last(self, hour: float) -> float:
        return min(max(hour - self.last_hour, 1.0), CAP_HOURS)

    def fits(self, hour: float, value: float) -> bool:
        raise NotImplementedError

    def update(self, hour: float, value: float) -> None:
        """Move the state on after an accepted reading that fits."""

    def restart(self, value: float) -> None:
        """Start again from `value` (after a lock or a return to a recent level)."""


class StepHampel(LiveFilter):
    """Hampel test on the rate of change: outlier if the step from the last
    accepted reading is far from the median of the recent steps, in units of
    MAD. A steady rise counts as normal, a sudden jump doesn't."""

    def __init__(self) -> None:
        super().__init__()
        self.rates: deque[float] = deque(maxlen=HAMPEL_STEPS)

    def fits(self, hour: float, value: float) -> bool:
        if len(self.rates) < HAMPEL_STEPS:
            return True
        hours = self.hours_since_last(hour)
        median = float(np.median(self.rates))
        mad = float(np.median(np.abs(np.array(self.rates) - median)))
        limit = max(HAMPEL_K * 1.4826 * mad, HAMPEL_MIN_RATE_M_PER_H) * hours
        return abs(value - (self.last_value + median * hours)) <= limit

    def update(self, hour: float, value: float) -> None:
        self.rates.append((value - self.last_value) / max(hour - self.last_hour, 1.0))


class RateEnvelope(LiveFilter):
    """Outlier if it rose or fell faster than physically plausible since the
    last accepted reading."""

    def fits(self, hour: float, value: float) -> bool:
        hours = self.hours_since_last(hour)
        return -FALL_M_PER_H * hours <= value - self.last_value <= RISE_M_PER_H * hours


class KalmanGate(LiveFilter):
    """Outlier if the reading is far from the level the filter predicted.

    The state is level and trend, so on a rising limb the prediction rises too
    and real floods pass, while a jump against the trend is caught.
    """

    def __init__(self) -> None:
        super().__init__()
        self.state = np.zeros(2)
        self.covariance = np.eye(2)

    def predict(self, hour: float) -> tuple[np.ndarray, np.ndarray]:
        # Capped like the other filters: the trend isn't extrapolated, and the
        # uncertainty doesn't grow, beyond CAP_HOURS
        g = self.hours_since_last(hour)
        transition = np.array([[1.0, g], [0.0, 1.0]])
        noise = KALMAN_SLOPE_NOISE * np.array([[g**3 / 3, g**2 / 2], [g**2 / 2, g]])
        return transition @ self.state, transition @ self.covariance @ transition.T + noise

    def fits(self, hour: float, value: float) -> bool:
        state, covariance = self.predict(hour)
        spread = covariance[0, 0] + KALMAN_MEASUREMENT_NOISE
        return abs(value - state[0]) <= max(KALMAN_K * np.sqrt(spread), KALMAN_MIN_DEVIATION_M)

    def update(self, hour: float, value: float) -> None:
        state, covariance = self.predict(hour)
        gain = covariance[:, 0] / (covariance[0, 0] + KALMAN_MEASUREMENT_NOISE)
        self.state = state + gain * (value - state[0])
        self.covariance = covariance - np.outer(gain, covariance[0, :])

    def restart(self, value: float) -> None:
        self.state = np.array([value, 0.0])
        self.covariance = np.diag([KALMAN_MEASUREMENT_NOISE, KALMAN_SLOPE_NOISE])


LIVE_FILTERS = {
    "Step Hampel": StepHampel,
    "Rate envelope": RateEnvelope,
    "Kalman": KalmanGate,
}


def run_live(filter_class: type[LiveFilter], levels: pd.Series) -> pd.Series:
    """Feed the readings one by one, as the hourly job would."""
    live_filter = filter_class()
    hours = (levels.index - pd.Timestamp(0, tz="UTC")).total_seconds().to_numpy() / 3600
    flags = [live_filter.is_outlier(h, v) for h, v in zip(hours, levels.to_numpy(), strict=True)]
    return pd.Series(flags, index=levels.index)


def excursion(levels: pd.Series) -> pd.Series:
    """Offline: outlier if a jump of more than EXCURSION_JUMP_M is undone by a
    sharp step back within EXCURSION_MAX_HOURS."""
    flags = np.zeros(len(levels), dtype=bool)
    values = levels.to_numpy()
    times = levels.index
    i = 1
    while i < len(values):
        before = values[i - 1]
        direction = np.sign(values[i] - before)
        if abs(values[i] - before) <= EXCURSION_JUMP_M:
            i += 1
            continue
        end = times[i - 1] + pd.Timedelta(hours=EXCURSION_MAX_HOURS + 1)
        height = abs(values[i] - before)
        j = i + 1
        while j < len(values) and times[j] <= end:
            step_back = (values[j - 1] - values[j]) * direction
            if step_back > EXCURSION_JUMP_M and (
                abs(values[j] - before) < EXCURSION_RETURN_FRACTION * height
            ):
                flags[i:j] = True
                break
            height = max(height, abs(values[j] - before))
            j += 1
        # Continue after the return point, so it becomes the next anchor
        i = j + 1 if flags[i] else i + 1
    return pd.Series(flags, index=levels.index)
