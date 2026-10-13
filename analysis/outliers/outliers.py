"""Compare three live outlier filters on the raw Kupferdreh levels.

Exploration only: reads the CSV from export.py, writes plots and a stats table
into this folder. The filters are in methods.py and use nothing but the level
series itself.
"""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from methods import LIVE_FILTERS, excursion, run_live

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

WARM_UP = pd.Timedelta("48h")  # how much history a fresh filter gets in the replay check


def flags_for(levels: pd.Series) -> dict[str, pd.Series]:
    return {name: run_live(filter_class, levels) for name, filter_class in LIVE_FILTERS.items()}


def self_check() -> None:
    index = pd.date_range("2024-01-01", periods=30, freq="h", tz="UTC")
    spiky = np.full(30, 0.2)
    spiky[[10, 15]] = 2.98  # two spikes: the good values between must stay
    spiky[20:22] = 1.5
    flood = np.concatenate([np.full(10, 0.2), np.linspace(0.2, 1.6, 6), np.full(14, 1.6)])
    for name, flags in flags_for(pd.Series(spiky, index=index)).items():
        assert list(np.flatnonzero(flags)) == [10, 15, 20, 21], (name, np.flatnonzero(flags))
    for name, flags in flags_for(pd.Series(flood, index=index)).items():
        assert not flags.any(), (name, np.flatnonzero(flags))
    # A small spike may pass, but the true level after it must not be rejected
    small = np.full(30, 0.2)
    small[10] = 0.5
    for name, flags in flags_for(pd.Series(small, index=index)).items():
        assert not flags.iloc[11:].any(), (name, np.flatnonzero(flags))


def check_live(levels: pd.Series, flags: dict[str, pd.Series]) -> None:
    """Flags must not change when later readings are added: cut the series at
    a few points and compare with the full run."""
    for cut in np.linspace(len(levels) // 10, len(levels) - 1, 7).astype(int):
        for name, prefix_flags in flags_for(levels.iloc[:cut]).items():
            assert prefix_flags.equals(flags[name].iloc[:cut]), (name, cut)


def replay_mismatches(levels: pd.Series, flags: dict[str, pd.Series]) -> dict[str, int]:
    """Readings judged differently when each month starts from a fresh filter
    with only WARM_UP of history, as a stateless hourly job would."""
    mismatches = dict.fromkeys(flags, 0)
    for month_start in pd.date_range(levels.index[0].normalize(), levels.index[-1], freq="MS"):
        month = levels[month_start : month_start + pd.offsets.MonthBegin(1)].index
        if month.empty:
            continue
        replayed = flags_for(levels[month_start - WARM_UP : month[-1]])
        for name in flags:
            mismatches[name] += int((replayed[name][month] != flags[name][month]).sum())
    return mismatches


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
    flags = flags_for(levels)
    check_live(levels, flags)
    table = stats(levels, {**flags, "Excursion (offline reference)": excursion(levels)})
    print(table.to_markdown())
    print()
    print("replay mismatches:", replay_mismatches(levels, flags))
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
