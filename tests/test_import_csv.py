from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from ofinto.services.import_csv import import_data
from ofinto.model import (
    CLIENTS_TABLE,
    ENRICHMENT_TABLE,
    ORDER_ITEMS_TABLE,
    ORDERS_TABLE,
    SCHEMAS,
)


TEST_DATA = Path(__file__).parent / "test_data"


def read_tables(database):
    """Alle Tabellen für den Vergleich vor und nach dem Import lesen."""
    with duckdb.connect(str(database), read_only=True) as connection:
        return {
            table: connection.execute(f'SELECT * FROM "{table}"').fetchall()
            for table in SCHEMAS
        }


def test_import_returns_expected_data(tmp_path):
    database = tmp_path / "case.duckdb"

    counts = import_data(TEST_DATA / "valid", database)

    assert counts == {
        CLIENTS_TABLE: 1,
        ENRICHMENT_TABLE: 1,
        ORDERS_TABLE: 1,
        ORDER_ITEMS_TABLE: 1,
    }, "Jede Tabelle muss genau eine Zeile enthalten"

    # Vollständige Zeilen prüfen, einschließlich Datentypen und leerer Felder.
    assert read_tables(database) == {
        CLIENTS_TABLE: [
            ("A-1", "Beispiel AG", "Zürich", "0123", "CH", "Deutschschweiz",
             "de", None, "Anna", "Webshop", date(2026, 1, 2)),
        ],
        ENRICHMENT_TABLE: [
            ("A-1", "Beispiel AG", "Zürich", "CHE-123", 0.95, 100,
             "Standort", 1, "01.10", 2000, date(2026, 1, 1)),
        ],
        ORDERS_TABLE: [
            ("O-1", "A-1", date(2026, 1, 2), "ofinto.ch", "CHF",
             Decimal("123.45"), "abgeschlossen", Decimal("0.00"), "Webshop"),
        ],
        ORDER_ITEMS_TABLE: [
            ("O-1", "Elevate", "Tisch", 1, Decimal("123.45"), "CHF"),
        ],
    }, "Die importierten Daten müssen den erwarteten Werten entsprechen"


def test_failed_import_rolls_back_all_changes(tmp_path):
    database = tmp_path / "case.duckdb"
    import_data(TEST_DATA / "valid", database)
    before = read_tables(database)

    # Der zweite Datensatz ändert zuerst den Firmennamen auf „Neue AG“.
    # Erst die letzte Tabelle scheitert an der ungültigen Menge „ungueltig“.
    with pytest.raises(duckdb.Error):
        import_data(TEST_DATA / "invalid", database)

    # Auch die bereits importierte Namensänderung muss zurückgerollt werden.
    assert read_tables(database) == before, (
        "Nach dem Fehler müssen alle Tabellen unverändert sein"
    )
