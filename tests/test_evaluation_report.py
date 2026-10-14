import json
from pathlib import Path

import pandas as pd
import pytest

from pegel.evaluation import report
from pegel.evaluation.metrics import PERSISTENCE

LEADS = 24
START = pd.Timestamp("2024-10-01T00:30Z")


def _scores() -> pd.DataFrame:
    rows = [
        {
            "model": model,
            "fold": fold,
            "subset": subset,
            "lead": lead,
            "n": 10,
            "mae": lead * factor,
            "rmse": lead * factor,
            "bias": 0.0,
            "skill": 1 - factor,
        }
        for model, factor in ((PERSISTENCE, 1.0), ("ridge", 0.5))
        for fold in ("F1", "all")
        for subset in ("all", "high_water")
        for lead in range(1, LEADS + 1)
    ]
    return pd.DataFrame(rows)


def _alarms() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"model": m, "lead": lead, "threshold_cm": t, "hits": 2, "misses": 1, "false_alarms": 0}
            for m in ("ridge", PERSISTENCE)
            for lead in range(1, LEADS + 1)
            for t in (95.0, 145.0)
        ]
    )


def _warnings() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "model": [PERSISTENCE, PERSISTENCE, "ridge"],
            "threshold_cm": [95.0, 95.0, 95.0],
            "crossing_at": ["2024-10-02T00:30Z"] * 3,
            "first_warning_at": [None, None, "2024-10-01T18:30Z"],
            "warning_hours": [float("nan"), float("nan"), 6.0],
            "re_crossing": [False, False, False],
        }
    )


def test_lead_table_takes_pooled_scores_and_means_over_all_leads() -> None:
    table = report.lead_table(_scores(), "all")
    assert list(table.index) == [PERSISTENCE, "ridge"]
    assert list(table.columns) == [
        "+1 h",
        "+3 h",
        "+6 h",
        "+12 h",
        "+24 h",
        "mean 1-24 h",
        "mean skill",
    ]
    assert table.loc["ridge", "+6 h"] == 3.0
    assert table.loc[PERSISTENCE, "mean 1-24 h"] == pytest.approx(12.5)
    assert table.loc["ridge", "mean skill"] == pytest.approx(0.5)


def test_alarm_table_puts_persistence_first() -> None:
    table = report.alarm_table(_alarms())
    assert list(table.index) == [
        (PERSISTENCE, 95.0),
        (PERSISTENCE, 145.0),
        ("ridge", 95.0),
        ("ridge", 145.0),
    ]
    assert table.loc[(PERSISTENCE, 95.0), "+12 h"] == "2 / 1 / 0"


def test_warning_table_counts_warned_crossings() -> None:
    table = report.warning_table(_warnings())
    assert table.loc[(PERSISTENCE, 95.0), "crossings"] == 2
    assert table.loc[(PERSISTENCE, 95.0), "warned"] == 0
    assert table.loc[("ridge", 95.0), "median hours ahead"] == 6.0


def test_mark_re_crossings_flags_a_level_above_threshold_within_a_day() -> None:
    observed = pd.Series(
        [100.0, 90.0, 90.0, 100.0], index=pd.date_range(START, periods=4, freq="h")
    )
    warnings = pd.DataFrame(
        {
            "model": [PERSISTENCE, PERSISTENCE],
            "threshold_cm": [95.0, 95.0],
            "crossing_at": [str(START), str(START + pd.Timedelta(hours=3))],
            "warning_hours": [float("nan"), 3.0],
        }
    )
    marked = report.mark_re_crossings(warnings, observed)
    assert list(marked["re_crossing"]) == [False, True]
    table = report.warning_table(marked)
    assert table.loc[(PERSISTENCE, 95.0), "crossings"] == 1
    assert table.loc[(PERSISTENCE, 95.0), "warned"] == 0
    assert table.loc[(PERSISTENCE, 95.0), "re-crossings warned"] == 1
    assert pd.isna(table.loc[(PERSISTENCE, 95.0), "median hours ahead"])


def test_peak_and_lag_tables_keep_leads_6_and_12() -> None:
    peaks = pd.DataFrame(
        {
            "event": [1, 2, 1, 1],
            "model": ["ridge", "ridge", "ridge", PERSISTENCE],
            "lead": [6, 6, 1, 6],
            "height_error_cm": [-10.0, 4.0, 0.0, -20.0],
            "at_peak_error_cm": [-10.0, 2.0, 0.0, -20.0],
            "timing_error_hours": [1.0, 3.0, 0.0, float("nan")],
        }
    )
    table = report.peak_table(peaks)
    assert list(table.index) == [(PERSISTENCE, 6), ("ridge", 6)]
    assert table.loc[("ridge", 6), "mean abs height error (cm)"] == 7.0
    assert table.loc[("ridge", 6), "mean timing error (h)"] == 2.0
    lag = pd.DataFrame(
        {"model": [PERSISTENCE] * 3, "lead": [1, 6, 12], "n": 5, "shift_hours": [1, 6, 12]}
    )
    assert list(report.lag_table(lag).loc[PERSISTENCE]) == [6, 12]


def test_colours_follow_the_registry_and_keep_persistence_grey() -> None:
    from pegel.evaluation.report_plots import MODEL_COLOURS, PERSISTENCE_COLOUR, colours

    palette = colours(["zeta", "ridge", PERSISTENCE], ["persistence", "ridge"])
    assert palette[PERSISTENCE] == PERSISTENCE_COLOUR
    assert palette["ridge"] == MODEL_COLOURS[0]
    assert palette["zeta"] == MODEL_COLOURS[1]
    assert colours(["ridge"], ["persistence", "ridge"])["ridge"] == MODEL_COLOURS[0]


def test_markdown_table_formats_floats_and_missing_values() -> None:
    table = pd.DataFrame({"mae": [1.234, float("nan")]}, index=pd.Index(["a", "b"], name="model"))
    assert report.markdown_table(table).splitlines() == [
        "| model | mae |",
        "|---|---|",
        "| a | 1.23 |",
        "| b | - |",
    ]


def test_read_csv_gives_empty_frame_for_missing_or_empty_files(tmp_path: Path) -> None:
    (tmp_path / "empty.csv").write_text("")
    assert report.read_csv(tmp_path / "missing.csv").empty
    assert report.read_csv(tmp_path / "empty.csv").empty


def _run_info() -> dict[str, object]:
    return {
        "dataset_sha256": "ab" * 32,
        "git_commit": "0123456789abcdef",
        "dirty": True,
        "models": ["ridge", PERSISTENCE],
        "created_at": "2026-10-14T16:10:18+00:00",
        "settings": {
            "window_first_day": "2024-02-01",
            "window_last_day": "2026-04-12",
            "leads_hours": LEADS,
            "high_water_cm": 75.0,
            "flood_cm": 95.0,
            "target_tolerance_minutes": 10,
        },
    }


def test_section_lists_run_facts_tables_and_plots() -> None:
    tables = {"scores": _scores(), "alarms": _alarms(), "warnings": pd.DataFrame()}
    text = report.section("2026-10-14-x", _run_info(), tables, [Path("plots/x/mae.png")], "n")
    assert text.startswith("## 2026-10-14-x\n")
    assert "commit `0123456789ab` (dirty)" in text
    assert "Models: persistence, ridge" in text
    assert "Subset `high_water`" in text
    assert "### Alarms" in text
    assert "### Warnings" not in text
    assert "![mae](plots/x/mae.png)" in text
    assert text.endswith("**Notes:** n\n")


def _predictions() -> pd.DataFrame:
    issued = pd.date_range(START, periods=72, freq="h")
    observed = pd.Series(range(72), index=issued, dtype=float) + 80
    rows = [
        {
            "issued_at": at,
            "lead": lead,
            "model": model,
            "fold": "F1",
            "prediction": observed[at],
            "target": observed.get(at + pd.Timedelta(hours=lead), float("nan")),
        }
        for model in (PERSISTENCE, "ridge")
        for at in issued
        for lead in range(1, LEADS + 1)
    ]
    return pd.DataFrame(rows)


def test_main_writes_plots_and_appends_once(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "2026-10-14-x"
    run.mkdir(parents=True)
    _predictions().to_parquet(run / "predictions.parquet")
    (run / "run.json").write_text(json.dumps(_run_info()))
    _scores().to_csv(run / "scores.csv", index=False)
    _alarms().to_csv(run / "alarms.csv", index=False)
    (run / "bootstrap.csv").write_text("model,lead,n,mae_difference,low,high\n")
    events = {"start": START + pd.Timedelta(hours=20), "end": START + pd.Timedelta(hours=30)}
    pd.DataFrame([{**events, "peak_at": events["end"], "peak_cm": 110.0}]).to_csv(
        run / "events.csv", index=False
    )
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    log = report_dir / "experiments.md"
    log.write_text("# Experiment log\n")

    report.main([str(run), "--report-dir", str(report_dir), "--notes", "first"])

    plots = sorted(path.name for path in (report_dir / "plots" / run.name).iterdir())
    assert plots == ["event-1-2024-10-02.png", "mae-folds.png", "mae.png", "skill.png"]
    text = log.read_text()
    assert text.startswith("# Experiment log\n\n## 2026-10-14-x\n")
    assert "](plots/2026-10-14-x/event-1-2024-10-02.png)" in text
    with pytest.raises(ValueError, match="already has a section"):
        report.main([str(run), "--report-dir", str(report_dir)])
