from pathlib import Path

import duckdb
import pytest

from ofinto.services.import_csv import import_data
from ofinto.services.aggregation import merge_data

TEST_DATA = Path(__file__).parent / "test_data" / "valid"


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "case.duckdb"
    import_data(TEST_DATA, path)
    return path


def test_orders_respect_returns_and_cutoff(database):
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
            ('O-2', 'Go', 'Stuhl', 7, 10, 'CHF'),
            ('O-3', 'Elevate', 'Tisch', 10, 10, 'CHF'),
            ('O-4', 'Elevate', 'Tisch', 10, 10, 'CHF'),
            ('O-5', 'Elevate', 'Tisch', 10, 10, 'CHF')
        """)

    company = merge_data(database)[0]

    assert company["anzahl_bestellungen"] == 2
    assert (company["tische_min"], company["tische_max"]) == (1, 4)
    assert (company["buerostuehle_min"], company["buerostuehle_max"]) == (0, 2)


def test_employee_basis_depends_on_data_quality(database):
    assert merge_data(database)[0]["mitarbeiterbasis"] == "verwendbar"

    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE firmendaten_anreicherung SET stand = DATE '2020-01-01'")
    assert merge_data(database)[0]["mitarbeiterbasis"] == "eingeschränkt"

    with duckdb.connect(str(database)) as connection:
        connection.execute("DELETE FROM firmendaten_anreicherung")
    companies = merge_data(database)
    assert len(companies) == 1
    assert companies[0]["mitarbeiterbasis"] == "nicht verwendbar"


@pytest.mark.parametrize("score, expected", [
    (0.8499, "eingeschränkt"),
    (0.85, "verwendbar"),
])
def test_match_score_boundary(database, score, expected):
    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE firmendaten_anreicherung SET match_score = ?", [score])

    assert merge_data(database)[0]["mitarbeiterbasis"] == expected
