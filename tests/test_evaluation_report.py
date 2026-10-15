import json
from pathlib import Path

import pandas as pd
import pytest

from pegel.evaluation import report, report_tables
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


def test_lead_table_takes_pooled_scores_and_means_over_all_leads() -> None:
    table = report_tables.lead_table(_scores(), "all")
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


def test_lag_table_keeps_leads_6_and_12() -> None:
    lag = pd.DataFrame(
        {"model": [PERSISTENCE] * 3, "lead": [1, 6, 12], "n": 5, "shift_hours": [1, 6, 12]}
    )
    assert list(report_tables.lag_table(lag).loc[PERSISTENCE]) == [6, 12]


def test_colours_follow_the_registry_and_keep_persistence_grey() -> None:
    from pegel.evaluation.report_plots import MODEL_COLOURS, PERSISTENCE_COLOUR, colours

    palette = colours(["zeta", "ridge", PERSISTENCE], ["persistence", "ridge"])
    assert palette[PERSISTENCE] == PERSISTENCE_COLOUR
    assert palette["ridge"] == MODEL_COLOURS[0]
    assert palette["zeta"] == MODEL_COLOURS[1]
    assert colours(["ridge"], ["persistence", "ridge"])["ridge"] == MODEL_COLOURS[0]


def test_colours_give_the_newest_of_many_models_dark_shades() -> None:
    from pegel.evaluation.report_plots import MODEL_COLOURS, colours

    registered = [PERSISTENCE, *(f"model_{i}" for i in range(11))]
    palette = colours(registered, registered)
    dark, light = MODEL_COLOURS[:9], MODEL_COLOURS[9:]
    # 11 models, 9 dark shades: the two oldest get light ones, the rest all dark in order.
    assert [palette["model_0"], palette["model_1"]] == light[:2]
    assert [palette[f"model_{i}"] for i in range(2, 11)] == dark
    assert len(set(map(str, palette.values()))) == len(palette)


def test_markdown_table_formats_floats_and_missing_values() -> None:
    table = pd.DataFrame({"mae": [1.234, float("nan")]}, index=pd.Index(["a", "b"], name="model"))
    assert report_tables.markdown_table(table).splitlines() == [
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


def test_headline_table_has_one_formatted_row_per_model() -> None:
    table = report_tables.headline_table(_scores())
    assert list(table.columns) == [
        "mean MAE all (cm)",
        "mean MAE high water (cm)",
        "MAE +24 h high water (cm)",
        "skill +24 h high water",
    ]
    assert list(table.loc[PERSISTENCE]) == ["12.5", "12.5", "24.0", "0.00"]
    assert list(table.loc["ridge"]) == ["6.2", "6.2", "12.0", "0.50"]


def test_summary_names_the_best_model() -> None:
    assert report_tables.summary(_scores()) == [
        "Lowest mean MAE over leads 1-24 h: ridge over all issue times (6.2 cm; persistence"
        " 12.5 cm), ridge at high water (6.2 cm; persistence 12.5 cm)."
    ]
    zeta_scores = _scores().query("model == 'ridge'").assign(model="zeta")
    three = report_tables.summary(pd.concat([_scores(), zeta_scores]))
    # zeta scores the same as ridge, so both are named.
    assert three[0].startswith(
        "Lowest mean MAE over leads 1-24 h: ridge and zeta over all issue times (6.2 cm;"
    )
    alone = _scores()[_scores()["model"] == PERSISTENCE]
    assert report_tables.summary(alone) == [
        "Mean MAE of persistence over leads 1-24 h: 12.5 cm over all issue times, 12.5 cm at"
        " high water."
    ]


def test_section_puts_summary_and_headline_first_and_folds_the_details() -> None:
    tables = {"scores": _scores()}
    plots = [Path("plots/x/mae.png"), Path("plots/x/event-1-a.png")]
    text = report.section("2026-10-14-x", _run_info(), tables, plots, "n")
    assert text.startswith("## 2026-10-14-x\n\nLowest mean MAE")
    notes, headline, image = (
        text.index("**Notes:** n"),
        text.index("| model | mean MAE all (cm)"),
        text.index("![mae](plots/x/mae.png)"),
    )
    assert notes < headline < image < text.index("<details>")
    assert "<summary>Flood events: observed level and forecasts (1 plots)</summary>" in text
    assert "Subset `high_water`" in text
    assert "commit `0123456789ab` (dirty)" in text
    assert "Models: persistence, ridge" in text
    assert text.count("<details>") == text.count("</details>")


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
    assert plots == [
        "event-1-2024-10-02.png",
        "mae-folds.png",
        "mae.png",
        "skill.png",
    ]
    text = log.read_text()
    assert text.startswith("# Experiment log\n\n## 2026-10-14-x\n")
    assert "](plots/2026-10-14-x/event-1-2024-10-02.png)" in text
    with pytest.raises(ValueError, match="already has a section"):
        report.main([str(run), "--report-dir", str(report_dir)])
