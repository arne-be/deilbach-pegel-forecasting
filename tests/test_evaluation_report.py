import io
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


def test_colours_keep_persistence_grey_and_give_the_others_one_each_in_order() -> None:
    from pegel.evaluation.report_plots import MODEL_COLOURS, PERSISTENCE_COLOUR, colours

    palette = colours([PERSISTENCE, "ridge", "zeta"])
    assert palette == {
        PERSISTENCE: PERSISTENCE_COLOUR,
        "ridge": MODEL_COLOURS[0],
        "zeta": MODEL_COLOURS[1],
    }


def test_plotted_models_keep_persistence_and_the_best_that_beat_it() -> None:
    worse = _scores().query("model == 'ridge'").assign(model="worse", mae=lambda f: f["mae"] * 3)
    close = _scores().query("model == 'ridge'").assign(model="close", mae=lambda f: f["mae"] * 1.1)
    better = _scores().query("model == 'ridge'").assign(model="better", mae=lambda f: f["mae"] / 2)
    scores = pd.concat([_scores(), worse, close, better])
    # Only two models are plotted beside persistence; `worse` loses to it anyway.
    assert report_tables.plotted_models(scores) == [PERSISTENCE, "better", "ridge"]


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
        "folds better than persistence",
    ]
    assert list(table.loc[PERSISTENCE]) == ["12.5", "12.5", "24.0", "0.00", "-"]
    assert list(table.loc["ridge"]) == ["6.2", "6.2", "12.0", "0.50", "1 of 1"]


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
    plots = [Path("plots/x/error.png"), Path("plots/x/floods-seen.png")]
    text = report.section("2026-10-14-x", _run_info(), tables, plots, "n")
    assert text.startswith("## 2026-10-14-x\n\nLowest mean MAE")
    notes, headline, image = (
        text.index("**Notes:** n"),
        text.index("| model | mean MAE all (cm)"),
        text.index("![error](plots/x/error.png)"),
    )
    assert notes < headline < image < text.index(report.CAPTIONS["error"]) < text.index("<details>")
    assert "floods-seen" not in text  # no flood tables, no flood section
    assert "Subset `high_water`" in text
    assert "commit `0123456789ab` (dirty)" in text
    assert "Models: persistence, ridge" in text
    assert text.count("<details>") == text.count("</details>")


def test_main_writes_plots_and_appends_once(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "2026-10-14-x"
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps(_run_info()))
    _scores().to_csv(run / "scores.csv", index=False)
    (run / "bootstrap.csv").write_text("model,lead,n,mae_difference,low,high\n")
    events = {"start": START + pd.Timedelta(hours=20), "end": START + pd.Timedelta(hours=30)}
    event = {**events, "event": 1, "fold": "F1", "pre_event_cm": 90.0}
    pd.DataFrame([{**event, "peak_at": events["end"], "peak_cm": 110.0}]).to_csv(
        run / "events.csv", index=False
    )
    _peaks().to_csv(run / "peaks.csv", index=False)
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    log = report_dir / "experiments.md"
    log.write_text("# Experiment log\n")

    report.main([str(run), "--report-dir", str(report_dir), "--notes", "first"])

    plots = sorted(path.name for path in (report_dir / "plots" / run.name).iterdir())
    assert plots == ["error.png", "flood-size.png", "floods-seen.png"]
    text = log.read_text()
    assert text.startswith("# Experiment log\n\n## 2026-10-14-x\n")
    flood_section = text.index("### Flood forecasts")
    assert text.index("](plots/2026-10-14-x/error.png)") < flood_section
    assert flood_section < text.index("](plots/2026-10-14-x/floods-seen.png)")
    assert "replay.html" not in text
    with pytest.raises(ValueError, match="already has a section"):
        report.main([str(run), "--report-dir", str(report_dir)])


def _peak(
    model: str, event: int, lead: int, size: float, timing: int, **extra: object
) -> dict[str, object]:
    return {
        "model": model,
        "event": event,
        "fold": "F1",
        "lead_hours": lead,
        "size": size,
        "timing_hours": timing,
        "timing_at_least": extra.get("at_least", False),
        "predicted": size > 0.5,
    }


def _peaks() -> pd.DataFrame:
    rows = [
        _peak("ridge", 1, 6, 0.82, -2),
        _peak("ridge", 2, 6, 0.31, 5, at_least=True),
        _peak("ridge", 3, 6, 0.9, 0),
        _peak(PERSISTENCE, 1, 6, 0.6, -5),
        _peak(PERSISTENCE, 2, 6, 0.2, -5),
        _peak(PERSISTENCE, 3, 6, 0.4, -5),
    ]
    missing = {**_peak("ridge", 3, 24, 0, 0), "size": None, "timing_hours": None}
    rows += [
        _peak(model, event, 24, 0.1, -23) for model in ("ridge", PERSISTENCE) for event in (1, 2)
    ]
    rows += [missing, {**_peak(PERSISTENCE, 3, 24, 0.7, -23)}]
    peaks = pd.DataFrame(rows).astype({"timing_at_least": object, "predicted": object})
    peaks.loc[peaks["size"].isna(), ["timing_at_least", "predicted"]] = None
    # As the report reads it back from peaks.csv: booleans with NaN where missing.
    return pd.read_csv(io.StringIO(peaks.to_csv(index=False)))


def test_flood_summary_table_counts_events_with_a_forecast_and_puts_persistence_first() -> None:
    false_alarms = pd.DataFrame({"model": ["ridge"], "count": [2], "per_month": [0.125]})
    table = report_tables.flood_summary_table(_peaks(), false_alarms)
    assert list(table.index) == [PERSISTENCE, "ridge"]
    assert list(table.columns) == ["24 h before", "6 h before", "false alarms / month"]
    assert table.loc["ridge", "6 h before"] == "2 of 3 · 82 % · \N{MINUS SIGN}1 h"
    assert table.loc["ridge", "24 h before"] == "0 of 2 · 10 % · —"
    assert table.loc[PERSISTENCE, "24 h before"] == "1 of 3 · 10 % · \N{MINUS SIGN}23 h"
    assert list(table["false alarms / month"]) == ["—", "0.12"]


def test_flood_grid_table_marks_predicted_missing_and_at_least_timings() -> None:
    events = pd.DataFrame(
        {
            "event": [1, 2, 3],
            "peak_at": [
                "2024-10-10 02:30:00+00:00",
                "2024-11-19 17:30:00+00:00",
                "2025-01-01 00:30:00+00:00",
            ],
            "peak_cm": [120.7, 165.0, 97.3],
        }
    )
    table = report_tables.flood_grid_table(_peaks(), events, "ridge")
    assert list(table.columns) == ["peak (UTC)", "peak cm", "24 h before", "6 h before"]
    assert list(table.loc[1]) == [
        "2024-10-10",
        "121",
        "✗ 10 % \N{MINUS SIGN}23 h",
        "✓ 82 % \N{MINUS SIGN}2 h",
    ]
    assert table.loc[2, "6 h before"] == "✗ 31 % ≥ +5 h"
    assert list(table.loc[3, ["24 h before", "6 h before"]]) == ["—", "✓ 90 % ±0 h"]


def test_flood_summary_names_the_best_model_against_persistence() -> None:
    assert report_tables.flood_summary(_peaks()) == [
        "Events predicted: ridge 2 of 3 at 6 h, 0 of 2 at 24 h; persistence 1 of 3 at 6 h,"
        " 1 of 3 at 24 h."
    ]


def test_section_points_to_the_replay_only_when_it_exists() -> None:
    events = pd.DataFrame({"event": [1, 2, 3], "peak_at": ["2025-01-01"] * 3, "peak_cm": 100.0})
    tables = {"scores": _scores(), "peaks": _peaks(), "events": events}
    with_replay = report.section("x", _run_info(), tables, [], replay=True)
    assert "`replay.html` in the run folder" in with_replay
    assert "<summary>Flood events: persistence</summary>" in with_replay
    assert "replay.html" not in report.section("x", _run_info(), tables, [])


def test_flood_titles_name_the_model_that_sees_most_against_persistence() -> None:
    from pegel.evaluation import report_plots

    models = [PERSISTENCE, "ridge"]
    seen = report_plots._seen(_peaks())
    # At 24 h ridge sees none of its 2 floods, persistence 1 of 3: persistence leads.
    assert (
        report_plots.seen_title(seen, models) == "persistence sees 1 of 3 floods coming 24 h ahead"
    )
    assert report_plots.seen_title(seen.drop(24, level="lead_hours"), models) == (
        "ridge sees 2 of 3 floods coming 6 h ahead; persistence 1"
    )
    lead = report_plots.size_lead(_peaks())
    sizes = _peaks()[_peaks()["lead_hours"] == lead].pivot(
        index="event", columns="model", values="size"
    )
    assert report_plots.size_title(sizes, models, lead) == (
        "6 h before the peak, ridge saw a median 82 % of the rise; persistence 40 %"
    )


def test_band_table_pools_leads_weighted_by_rows() -> None:
    rows = [
        ("m", "all", "calm", 1, 80, 100, 0.9, 2.0),
        ("m", "all", "calm", 2, 80, 300, 0.7, 4.0),
        ("m", "F2", "calm", 1, 80, 100, 0.0, 9.0),
    ]
    columns = ["model", "fold", "situation", "lead", "coverage_percent", "n", "coverage", "width"]
    table = report_tables.band_table(pd.DataFrame(rows, columns=columns))
    assert table.loc[("m", "calm"), "80 %"] == "75% / 3.5"
    assert table.loc[("m", "calm"), "n"] == 400
