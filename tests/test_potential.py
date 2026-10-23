import csv
from datetime import date
from math import ceil, floor
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from ofinto.cli import app
from ofinto.config import PotentialConfig
from ofinto.services.aggregation import merge_data
from ofinto.services.import_csv import import_data
from ofinto.services.potential import estimate_potential
from ofinto.services.export import export_potential

AS_OF = date(2026, 10, 14)
TEST_DATA = Path(__file__).parent / "test_data" / "valid"


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "case.duckdb"
    import_data(TEST_DATA, path)
    with duckdb.connect(str(path)) as connection:
        connection.execute("UPDATE firmenkunden SET erste_bestellung = DATE '2021-01-01'")
        connection.execute("DELETE FROM bestellpositionen")
    return path


def run(database, tmp_path):
    merge_data(database, AS_OF)
    summary = estimate_potential(database, PotentialConfig(), AS_OF)
    export_potential(database, tmp_path / "exports")
    with duckdb.connect(str(database), read_only=True) as connection:
        cursor = connection.execute("SELECT * FROM company_potential ORDER BY account_id")
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return summary, rows


@pytest.mark.parametrize("tables,chairs,expected", [
    (0, 0, (35, 50)),
    (60, 0, (5, 20)),
    (0, 60, (5, 20)),
    (30, 30, (5, 20)),
    (100, 100, (0, 0)),
])
def test_half_workplaces_and_nonnegative_potential(database, tmp_path, tables, chairs, expected):
    with duckdb.connect(str(database)) as connection:
        connection.executemany("INSERT INTO bestellpositionen VALUES (?, ?, ?, ?, ?, ?)", [
            ("O-1", "Elevate", "Tisch", tables, 100, "CHF"),
            ("O-1", "Motion", "Stuhl", chairs, 100, "CHF"),
        ])
    summary, [row] = run(database, tmp_path)
    assert (row["potenzial_min"], row["potenzial_max"]) == expected
    assert (row["jahresbedarf_min"], row["jahresbedarf_max"]) == (7, 10)
    assert summary.top_count == int(expected[1] > 0)


@pytest.mark.parametrize("first", ["2026-10-14", "2026-07-01", "2025-10-14", "2024-02-29", "2022-01-01"])
def test_customer_specific_elapsed_time(database, tmp_path, first):
    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE firmenkunden SET erste_bestellung = ?", [first])
    _, [row] = run(database, tmp_path)
    years = min(5, (AS_OF - date.fromisoformat(first)).days / PotentialConfig().days_per_year)
    assert row["potenzial_min"] == floor(7 * years)
    assert row["potenzial_max"] == ceil(10 * years)


def test_partial_return_widens_interval_and_excludes_other_products(database, tmp_path):
    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE bestellungen SET status = 'teilretoure'")
        connection.execute("""INSERT INTO bestellpositionen VALUES
            ('O-1', 'Elevate', 'Tisch', 20, 100, 'CHF'),
            ('O-1', 'Motion', 'Stuhl', 10, 100, 'CHF'),
            ('O-1', 'Go', 'Stuhl', 500, 100, 'CHF'),
            ('O-1', 'Focus Pod S', 'Raumsystem', 500, 100, 'CHF')""")
    _, [row] = run(database, tmp_path)
    assert (row["potenzial_min"], row["potenzial_max"]) == (20, 50)
    assert "Teilretouren" in row["hinweise"]


@pytest.mark.parametrize("change,evaluated", [
    ("match_score = 0.85", True),
    ("match_score = 0.8499", False),
    ("match_score = NULL", True),  # Qualitätsentscheidung unverändert aus aggregate.
    ("stand = DATE '2024-10-14'", True),
    ("stand = DATE '2024-10-13'", False),
    ("stand = DATE '2026-10-15'", False),
    ("mitarbeitende_bezug = 'Konzern'", False),
    ("mitarbeitende_bezug = NULL", False),
    ("mitarbeitende = NULL", False),
])
def test_quality_and_reasons_come_from_aggregation(database, tmp_path, change, evaluated):
    with duckdb.connect(str(database)) as connection:
        connection.execute(f"UPDATE firmendaten_anreicherung SET {change}")
    summary, [row] = run(database, tmp_path)
    assert row["bewertbar"] is evaluated
    assert summary.excluded == int(not evaluated)
    assert (row["potenzial_min"] is None) is (not evaluated)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert (row["mitarbeiterbasis"], row["hinweise"]) == connection.execute(
            "SELECT mitarbeiterbasis, hinweise FROM company_profiles"
        ).fetchone()
    if not evaluated:
        assert row["hinweise"]
        with ((tmp_path / "exports") / "nicht_bewertbar.csv").open(newline="") as source:
            [excluded] = list(csv.DictReader(source))
        assert excluded["hinweise"] == row["hinweise"]


def test_ranking_uses_rounded_values_and_exports_are_repeatable(database, tmp_path):
    with duckdb.connect(str(database)) as connection:
        connection.execute("""INSERT INTO firmenkunden
            SELECT * REPLACE ('A-2' AS account_id, DATE '2022-01-01' AS erste_bestellung)
            FROM firmenkunden;
            INSERT INTO firmendaten_anreicherung
            SELECT * REPLACE ('A-2' AS account_id) FROM firmendaten_anreicherung;
            UPDATE firmenkunden SET erste_bestellung = DATE '2022-01-02' WHERE account_id = 'A-1';
        """)
    summary, _ = run(database, tmp_path)
    with ((tmp_path / "exports") / "top15.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    assert [row["account_id"] for row in rows] == ["A-1", "A-2"]
    assert rows[0]["potenzial_min"] == rows[1]["potenzial_min"]
    assert rows[0]["potenzial_max"] == rows[1]["potenzial_max"]
    before = {path.name: path.read_bytes() for path in (tmp_path / "exports").glob("*.csv")}
    run(database, tmp_path)
    assert before == {path.name: path.read_bytes() for path in (tmp_path / "exports").glob("*.csv")}


def test_top15_limit_and_account_tiebreak(database, tmp_path):
    with duckdb.connect(str(database)) as connection:
        connection.execute("""INSERT INTO firmenkunden
            SELECT * EXCLUDE (i) REPLACE (concat('B-', lpad(i::VARCHAR, 2, '0')) AS account_id)
            FROM firmenkunden CROSS JOIN range(20) AS sequence(i);
            INSERT INTO firmendaten_anreicherung
            SELECT * EXCLUDE (i) REPLACE (concat('B-', lpad(i::VARCHAR, 2, '0')) AS account_id)
            FROM firmendaten_anreicherung CROSS JOIN range(20) AS sequence(i);
        """)
    summary, _ = run(database, tmp_path)
    assert summary.top_count == 15
    assert summary.total == 21
    with ((tmp_path / "exports") / "top15.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    assert [row["account_id"] for row in rows] == ["A-1"] + [f"B-{i:02}" for i in range(14)]


@pytest.mark.parametrize("first", [None, "2027-01-01"])
def test_invalid_first_date_keeps_previous_potential(database, tmp_path, first):
    run(database, tmp_path)
    with duckdb.connect(str(database)) as connection:
        before = connection.execute("SELECT * FROM company_potential").fetchall()
        connection.execute("UPDATE firmenkunden SET erste_bestellung = ?", [first])
    with pytest.raises(ValueError, match="Erstbestelldatum"):
        run(database, tmp_path)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT * FROM company_potential").fetchall() == before


def test_cli_exports_and_errors(database, tmp_path):
    runner = CliRunner()
    output = tmp_path / "output with spaces"
    result = runner.invoke(app, ["ci", "--database", str(database), "--output-dir", str(output)])
    assert result.exit_code == 0, result.output
    assert "1 bewertet; 0 nicht bewertbar" in result.output
    assert "Beispiel AG" in result.output
    with (output / "kundenpotenziale.csv").open(newline="") as source:
        [row] = list(csv.DictReader(source))
    assert set(row) == {
        "account_id", "firmenname", "mitarbeitende", "erste_bestellung", "stichtag",
        "mitarbeiterbasis", "hinweise", "bewertbar", "potenzial_min", "potenzial_max",
        "jahresbedarf_min", "jahresbedarf_max", "regelversion",
    }
    with duckdb.connect(str(database), read_only=True) as connection:
        columns = connection.execute("SELECT * FROM company_potential LIMIT 0").description
        assert {column[0] for column in columns} == set(row)
    for field in ["potenzial_min", "potenzial_max", "jahresbedarf_min", "jahresbedarf_max"]:
        assert str(int(row[field])) == row[field]
    assert runner.invoke(app, ["potential", "--database", str(database), "--as-of", "invalid"]).exit_code == 1
    assert runner.invoke(app, ["potential", "--database", str(tmp_path / "missing.duckdb")]).exit_code == 1


def test_estimate_passes_config_to_calculation_and_exports(database, tmp_path):
    config = PotentialConfig(rule_version="custom", replacement_years=5)
    merge_data(database, AS_OF)
    summary = estimate_potential(database, config, AS_OF)
    export_potential(database, tmp_path / "exports")
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT potenzial_min, potenzial_max, regelversion FROM company_potential"
        ).fetchone() == (70, 100, "custom")
    with ((tmp_path / "exports") / "kundenpotenziale.csv").open(newline="") as source:
        [row] = list(csv.DictReader(source))
    assert (row["potenzial_min"], row["potenzial_max"], row["regelversion"]) == ("70", "100", "custom")


def test_potential_requires_aggregation_and_matching_stichtag(database, tmp_path):
    with pytest.raises(duckdb.Error):
        estimate_potential(database, PotentialConfig(), AS_OF)
    merge_data(database, AS_OF)
    with pytest.raises(ValueError, match="Stichtag"):
        estimate_potential(database, PotentialConfig(), date(2026, 10, 13))


def test_cli_steps_use_saved_profiles(database, tmp_path):
    runner = CliRunner()
    base = ["--database", str(database)]
    assert runner.invoke(app, ["aggregate", *base]).exit_code == 0
    with duckdb.connect(str(database)) as connection:
        columns = [column[0] for column in connection.execute(
            "SELECT * FROM company_profiles LIMIT 0"
        ).description]
    assert "mitarbeiterbasis" in columns
    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE firmendaten_anreicherung SET mitarbeitende = 1000")
    result = runner.invoke(app, ["potential", *base])
    assert result.exit_code == 0, result.output
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT mitarbeitende, potenzial_min, potenzial_max FROM company_potential"
        ).fetchone() == (100, 35, 50)


def test_export_is_independent_from_calculation(database, tmp_path):
    merge_data(database, AS_OF)
    estimate_potential(database, PotentialConfig(), AS_OF)
    output = tmp_path / "exports"
    assert not output.exists()
    result = CliRunner().invoke(app, ["export", "--database", str(database), "--output-dir", str(output)])
    assert result.exit_code == 0, result.output
    assert (output / "kundenpotenziale.csv").is_file()
    assert (output / "top15.csv").is_file()
    assert (output / "nicht_bewertbar.csv").is_file()
