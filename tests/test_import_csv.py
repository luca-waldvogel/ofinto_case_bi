from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from ofinto.model import SCHEMAS
from ofinto.services.import_csv import import_data

TEST_DATA = Path(__file__).parent / "test_data"


def read_tables(database):
    with duckdb.connect(str(database), read_only=True) as connection:
        return {
            table: connection.execute(f'SELECT * FROM "{table}"').fetchall()
            for table in SCHEMAS
        }


def test_import_stores_data_with_correct_types(tmp_path):
    database = tmp_path / "case.duckdb"

    counts = import_data(TEST_DATA / "valid", database)

    assert counts == {table: 1 for table in SCHEMAS}
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT account_id, plz FROM firmenkunden").fetchone() == ("A-1", "0123")
        assert connection.execute("SELECT bestelldatum, bestellwert_netto FROM bestellungen").fetchone() == (
            date(2026, 1, 2), Decimal("123.45"),
        )


def test_invalid_import_keeps_existing_data(tmp_path):
    database = tmp_path / "case.duckdb"
    import_data(TEST_DATA / "valid", database)
    before = read_tables(database)

    with pytest.raises(duckdb.Error):
        import_data(TEST_DATA / "invalid", database)

    assert read_tables(database) == before
