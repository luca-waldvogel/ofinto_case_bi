from datetime import date
from decimal import Decimal

import duckdb
import pytest

from ofinto_case_bi.import_csv import import_data
from ofinto_case_bi.schemas import SCHEMAS


def read_tables(database):
    with duckdb.connect(str(database), read_only=True) as connection:
        return {
            table: connection.execute(f'SELECT * FROM "{table}"').fetchall()
            for table in SCHEMAS
        }


def test_import_preserves_types_and_replaces_existing_data(csv_dir):
    database = csv_dir / "case.duckdb"
    assert import_data(csv_dir, database) == dict.fromkeys(SCHEMAS, 1)
    tables = read_tables(database)
    customer = tables["firmenkunden"][0]
    assert customer[3] == "0123"
    assert customer[7] is None
    assert customer[-1] == date(2026, 1, 2)
    assert tables["bestellungen"][0][5] == Decimal("123.45")
    assert tables["firmendaten_anreicherung"][0][8] == "01.10"

    source = csv_dir / "firmenkunden.csv"
    source.write_text(source.read_text(encoding="utf-8").replace("Beispiel AG", "Neue AG"), encoding="utf-8")
    assert import_data(csv_dir, database) == dict.fromkeys(SCHEMAS, 1)
    assert read_tables(database)["firmenkunden"][0][1] == "Neue AG"


@pytest.mark.parametrize("invalid_input", ["header", "quantity", "columns"])
def test_failed_import_preserves_all_existing_tables(csv_dir, invalid_input):
    database = csv_dir / "case.duckdb"
    import_data(csv_dir, database)
    before = read_tables(database)

    source = csv_dir / "firmenkunden.csv"
    source.write_text(source.read_text(encoding="utf-8").replace("Beispiel AG", "Neue AG"), encoding="utf-8")
    source = csv_dir / "bestellpositionen.csv"
    text = source.read_text(encoding="utf-8")
    if invalid_input == "header":
        text = text.replace("order_id", "wrong_column", 1)
    elif invalid_input == "quantity":
        text = text.replace(",1,123.45,", ",invalid,123.45,")
    else:
        text = text.replace(",1,123.45,CHF", ",1,123.45")
    source.write_text(text, encoding="utf-8")

    with pytest.raises((duckdb.Error, ValueError)):
        import_data(csv_dir, database)
    assert read_tables(database) == before
