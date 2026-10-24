import csv
from pathlib import Path

import duckdb
from typer.testing import CliRunner

from ofinto.cli import app
from ofinto.services.import_csv import import_data

DATA = Path(__file__).parent / "test_data" / "valid"


def test_run_exports_potential_and_last_order(tmp_path):
    database = tmp_path / "case.duckdb"
    output = tmp_path / "potential"
    import_data(DATA, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE firmenkunden SET erste_bestellung = DATE '2020-10-14'")

    result = CliRunner().invoke(app, [
        "run", "--database", str(database), "--output-dir", str(output),
    ])
    assert result.exit_code == 0, result.output
    with (output / "kundenpotenziale.csv").open(newline="") as source:
        [row] = list(csv.DictReader(source))
    assert row["letzte_bestellung"] == "2026-01-02"
    assert (row["potenzial_min"], row["potenzial_max"]) == ("41", "60")
    assert (row["jahresbedarf_min"], row["jahresbedarf_max"]) == ("7", "10")
    assert (output / "top15.csv").is_file()
    assert (output / "nicht_bewertbar.csv").is_file()
