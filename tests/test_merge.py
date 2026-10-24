import csv
from datetime import date
from pathlib import Path

import duckdb
from typer.testing import CliRunner

from ofinto.cli import app
from ofinto.services.aggregation import merge_data
from ofinto.services.import_csv import import_data

DATA = Path(__file__).parent / "test_data" / "valid"


def test_aggregate_filters_orders_and_exports_csv(tmp_path):
    database = tmp_path / "case.duckdb"
    import_data(DATA, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute("""
            INSERT INTO bestellungen VALUES
            ('O-2', 'A-1', '2026-02-01', 'ofinto.ch', 'CHF', 300, 'teilretoure', 50, 'Webshop'),
            ('O-3', 'A-1', '2026-03-01', 'ofinto.ch', 'CHF', 100, 'retoure', 100, 'Webshop'),
            ('O-4', 'A-1', '2026-04-01', 'ofinto.ch', 'CHF', 100, 'storniert', 0, 'Webshop'),
            ('O-5', 'A-1', '2027-01-01', 'ofinto.ch', 'CHF', 100, 'abgeschlossen', 0, 'Webshop');
            INSERT INTO bestellpositionen VALUES
            ('O-2', 'Elevate', 'Tisch', 3, 50, 'CHF'),
            ('O-2', 'Motion', 'Stuhl', 2, 50, 'CHF'),
            ('O-3', 'Elevate', 'Tisch', 10, 10, 'CHF'),
            ('O-4', 'Elevate', 'Tisch', 10, 10, 'CHF'),
            ('O-5', 'Elevate', 'Tisch', 10, 10, 'CHF')
        """)

    result = CliRunner().invoke(app, ["aggregate", "--database", str(database)])
    assert result.exit_code == 0, result.output
    assert "company_profiles: 1 Firmen" in result.output
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("""
            SELECT anzahl_bestellungen, letzte_bestellung, tische_min, tische_max,
                   buerostuehle_min, buerostuehle_max FROM company_profiles
        """).fetchone() == (2, date(2026, 2, 1), 1, 4, 0, 2)
    with (tmp_path / "results" / "aggregate" / "company_profiles.csv").open(newline="") as source:
        [row] = list(csv.DictReader(source))
    assert row["letzte_bestellung"] == "2026-02-01"


def test_aggregate_marks_low_match_score(tmp_path):
    database = tmp_path / "case.duckdb"
    import_data(DATA, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE firmendaten_anreicherung SET match_score = 0.8")
    assert merge_data(database) == 1
    with duckdb.connect(str(database), read_only=True) as connection:
        row = connection.execute(
            "SELECT mitarbeiterbasis, hinweise FROM company_profiles"
        ).fetchone()
    assert row is not None
    basis, reason = row
    assert basis == "eingeschränkt"
    assert "Match-Score" in reason
