from pathlib import Path

from pegel.adapters.env_files import load_env_files, parse_env_file


def test_values_are_taken_literally() -> None:
    assert parse_env_file("PASSWORD=a$b c#d\n") == {"PASSWORD": "a$b c#d"}


def test_surrounding_quotes_are_removed() -> None:
    assert parse_env_file("NAME='x y'\n") == {"NAME": "x y"}


def test_comments_and_blank_lines_are_ignored() -> None:
    assert parse_env_file("# comment\n\nA=1\n") == {"A": "1"}


def test_env_local_overrides_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("A=from-env\n")
    (tmp_path / ".env.local").write_text("A=from-local\n")
    environ: dict[str, str] = {}
    load_env_files(tmp_path, environ)
    assert environ == {"A": "from-local"}


def test_real_environment_wins_over_files(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text("JOBS_DATABASE_URL=dev\n")
    environ = {"JOBS_DATABASE_URL": "prod-for-this-run"}
    load_env_files(tmp_path, environ)
    assert environ["JOBS_DATABASE_URL"] == "prod-for-this-run"


def test_empty_file_value_does_not_set_a_variable(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("JOBS_DATABASE_URL=\n")
    environ: dict[str, str] = {}
    load_env_files(tmp_path, environ)
    assert environ == {}


def test_missing_files_are_skipped(tmp_path: Path) -> None:
    assert load_env_files(tmp_path, {}) == []
