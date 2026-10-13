"""Compare three outlier filters on the raw Kupferdreh levels.

Exploration only: reads the CSV from export.py, writes plots and a stats table
into this folder. Each method returns a boolean mask (True = outlier) and uses
nothing but the level series itself.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
SENSOR_CEILING_M = 2.95  # the gauge reports 2.98 m when it fails; no real level gets close

# Days with real high water or fast real rises, checked by eye. Flags within a
# day of these are lost real data, not removed spikes.
REAL_EVENT_DAYS = [
    "2023-06-22",
    "2023-12-22",
    "2024-01-04",
    "2024-08-18",
    "2024-11-19",
    "2025-09-09",
    "2026-05-31",
    "2026-06-02",
]

# Method parameters, picked with the sweep in README.md
HAMPEL_WINDOW = "9h"  # centred, so spikes up to 4 h long are still a minority
HAMPEL_K = 3.0
HAMPEL_MIN_DEVIATION_M = 0.15  # MAD is ~0 at low water, so set a floor
RATE_MAX_STEP_M_PER_H = 0.35
RATE_REANCHOR_AFTER = 8  # consecutive rejections before we trust the new level
EXCURSION_JUMP_M = 0.25
EXCURSION_MAX_HOURS = 14  # longest stuck run seen is 13 h
EXCURSION_RETURN_FRACTION = 0.25  # back within a quarter of the excursion height


def hampel(levels: pd.Series) -> pd.Series:
    """Outlier if it is far from the centred rolling median, in units of MAD."""
    rolling = levels.rolling(HAMPEL_WINDOW, center=True, min_periods=3)
    median = rolling.median()
    mad = (levels - median).abs().rolling(HAMPEL_WINDOW, center=True, min_periods=3).median()
    limit = np.maximum(HAMPEL_K * 1.4826 * mad, HAMPEL_MIN_DEVIATION_M)
    return (levels - median).abs() > limit


def rate_limit(levels: pd.Series) -> pd.Series:
    """Causal: outlier if it moved faster than the max rate from the last accepted value.

    After RATE_REANCHOR_AFTER rejections in a row the new level is accepted, so a
    real fast rise is only lost for its first few hours instead of forever.
    """
    flags = np.zeros(len(levels), dtype=bool)
    hours = (levels.index - levels.index[0]).total_seconds().to_numpy() / 3600
    values = levels.to_numpy()
    last_value, last_hour, rejected = values[0], hours[0], 0
    for i in range(1, len(values)):
        allowed = RATE_MAX_STEP_M_PER_H * max(hours[i] - last_hour, 1.0)
        if abs(values[i] - last_value) <= allowed or rejected >= RATE_REANCHOR_AFTER:
            last_value, last_hour, rejected = values[i], hours[i], 0
            continue
        flags[i] = True
        rejected += 1
    return pd.Series(flags, index=levels.index)


def excursion(levels: pd.Series) -> pd.Series:
    """Outlier if a jump of more than EXCURSION_JUMP_M is undone by a jump back
    within EXCURSION_MAX_HOURS.

    "Back" means a step in the opposite direction that lands close to the level
    before the excursion. Real floods fall at most ~0.2 m/h here, so a sharp
    step back only happens when the jump up was fake.
    """
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
        # Continue after the return point, so it becomes the next anchor and the
        # drop back from one spike can't start an "excursion" to the next spike
        i = j + 1 if flags[i] else i + 1
    return pd.Series(flags, index=levels.index)


METHODS = {"Hampel": hampel, "Rate limit": rate_limit, "Excursion": excursion}


def self_check() -> None:
    index = pd.date_range("2024-01-01", periods=30, freq="h", tz="UTC")
    flat = np.full(30, 0.2)
    spiky = flat.copy()
    spiky[[10, 15]] = 2.98  # two spikes: the good values between must stay
    spiky[20:22] = 1.5
    flood = np.concatenate([np.full(10, 0.2), np.linspace(0.2, 1.6, 6), np.full(14, 1.6)])
    for name, method in METHODS.items():
        found = method(pd.Series(spiky, index=index))
        assert list(np.flatnonzero(found)) == [10, 15, 20, 21], (name, np.flatnonzero(found))
        assert not method(pd.Series(flood, index=index)).any(), name


def load(path: Path) -> pd.Series:
    frame = pd.read_csv(path)
    # Timestamps mix whole and fractional seconds, so parse them as ISO 8601
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True, format="ISO8601")
    return frame.set_index("observed_at")["level_m"].sort_index()


def stats(levels: pd.Series, flags: dict[str, pd.Series]) -> pd.DataFrame:
    ceiling = levels >= SENSOR_CEILING_M
    real_events = pd.Series(False, index=levels.index)
    for day in REAL_EVENT_DAYS:
        middle = pd.Timestamp(day, tz="UTC")
        real_events[middle - pd.Timedelta("1D") : middle + pd.Timedelta("2D")] = True
    rows = {}
    for name, flagged in flags.items():
        kept = levels[~flagged]
        rows[name] = {
            "flagged": int(flagged.sum()),
            "flagged %": round(100 * flagged.mean(), 2),
            "2.98 m values caught": f"{int((flagged & ceiling).sum())} / {int(ceiling.sum())}",
            "removed in real events": int((flagged & real_events & ~ceiling).sum()),
            "jumps > 0.3 m left": int((kept.diff().abs() > 0.3).sum()),
            "jumps > 0.3 m left, plus 2.98 rule": int(
                (levels[~(flagged | ceiling)].diff().abs() > 0.3).sum()
            ),
            "max kept m": round(kept.max(), 2),
        }
    return pd.DataFrame(rows)


def agreement(flags: dict[str, pd.Series]) -> pd.DataFrame:
    names = list(flags)
    return pd.DataFrame(
        [[int((flags[a] & flags[b]).sum()) for b in names] for a in names],
        index=names,
        columns=names,
    )


def plot_window(
    levels: pd.Series, flags: dict[str, pd.Series], start: str, end: str, title: str, path: Path
) -> None:
    window = levels[start:end]
    fig, axes = plt.subplots(len(flags), 1, figsize=(11, 2.6 * len(flags)), sharex=True)
    for ax, (name, flagged) in zip(axes, flags.items(), strict=True):
        mask = flagged[start:end]
        ax.plot(window.index, window, color="#c8c8c8", lw=0.8, label="raw")
        ax.plot(window.index, window.where(~mask), color="#1f5fa8", lw=1.1, label="kept")
        ax.scatter(
            window.index[mask], window[mask], color="#d1495b", s=9, zorder=3, label="removed"
        )
        ax.set_title(f"{name}: {int(mask.sum())} removed", loc="left", fontsize=10)
        ax.set_ylabel("level (m)")
        ax.grid(alpha=0.3)
    axes[0].legend(loc="upper right", fontsize=8, ncol=3)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def plot_diffs(levels: pd.Series, flags: dict[str, pd.Series], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 4))
    bins = np.linspace(-3.2, 3.2, 129)
    ax.hist(levels.diff().dropna(), bins=bins, histtype="step", color="#999999", label="raw")
    for name, flagged in flags.items():
        ax.hist(levels[~flagged].diff().dropna(), bins=bins, histtype="step", label=name)
    ax.set_yscale("log")
    ax.set_xlabel("change between consecutive readings (m)")
    ax.set_ylabel("count (log)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main(csv_path: Path) -> None:
    self_check()
    levels = load(csv_path)
    flags = {name: method(levels) for name, method in METHODS.items()}
    print(stats(levels, flags).to_markdown())
    print()
    print(agreement(flags).to_markdown())
    plots = HERE / "plots"
    plots.mkdir(exist_ok=True)
    plot_diffs(levels, flags, plots / "diffs.png")
    for name, (start, end, title) in WINDOWS.items():
        plot_window(levels, flags, start, end, title, plots / f"{name}.png")


# Windows picked after a first look at the data; see README.md
WINDOWS: dict[str, tuple[str, str, str]] = {
    "full": ("2023-03-01", "2026-12-31", "Whole series"),
    "spikes-2023-08": ("2023-07-25", "2023-08-12", "Spike period, summer 2023"),
    "stuck-2023-09": ("2023-09-15", "2023-09-19", "13 hours stuck at 2.98 m"),
    "stuck-2023-12": ("2023-12-03", "2023-12-06", "6 hours stuck at 2.98 m, then a fake drop"),
    "spike-2025-02": ("2025-01-31", "2025-02-03", "3-hour spike at 2.7 m, after the 2.98 period"),
    "spikes-2026-09": ("2026-09-24", "2026-10-06", "Recent small spikes near the sensor floor"),
    "flood-2024-11": ("2024-11-17", "2024-11-22", "Highest real flood (1.23 m)"),
    "flood-2023-12": ("2023-12-20", "2024-01-06", "Long wet period, winter 2023/24"),
    "storm-2023-06": ("2023-06-21", "2023-06-24", "Fastest real rise (summer storm)"),
}


if __name__ == "__main__":
    main(Path(sys.argv[1]))
