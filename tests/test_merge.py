from datetime import date
from pathlib import Path

import duckdb
import pytest

from ofinto.import_csv import import_data
from ofinto.merge import merge_data
from ofinto.model import (
    CLIENTS_TABLE,
    COMPANY_PROFILES_TABLE,
    ENRICHMENT_TABLE,
    ORDER_ITEMS_TABLE,
    ORDERS_TABLE,
)

TEST_DATA = Path(__file__).parent / 'test_data' / 'valid'


def test_order_quantities_and_returns(tmp_path):
    database = tmp_path / 'case.duckdb'
    import_data(TEST_DATA, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(f"""
            INSERT INTO "{ORDERS_TABLE}" VALUES
            ('O-2', 'A-1', '2026-02-01', 'ofinto.ch', 'CHF', 300, 'teilretoure', 50, 'Webshop'),
            ('O-3', 'A-1', '2026-03-01', 'ofinto.ch', 'CHF', 100, 'retoure', 100, 'Webshop'),
            ('O-4', 'A-1', '2026-04-01', 'ofinto.ch', 'CHF', 100, 'storniert', 0, 'Webshop'),
            ('O-5', 'A-1', '2027-01-01', 'ofinto.ch', 'CHF', 100, 'abgeschlossen', 0, 'Webshop');
            INSERT INTO "{ORDER_ITEMS_TABLE}" VALUES
            ('O-2', 'Elevate', 'Tisch', 3, 50, 'CHF'),
            ('O-2', 'Motion', 'Stuhl', 2, 50, 'CHF'),
            ('O-2', 'Go', 'Stuhl', 7, 10, 'CHF'),
            ('O-3', 'Elevate', 'Tisch', 10, 10, 'CHF'),
            ('O-4', 'Elevate', 'Tisch', 10, 10, 'CHF'),
            ('O-5', 'Elevate', 'Tisch', 10, 10, 'CHF')
        """)
    company, = merge_data(database)
    assert company['anzahl_bestellungen'] == 2  # Positionen vervielfachen Bestellungen nicht.
    assert company['letzte_bestellung'] == date(2026, 2, 1)
    assert (company['tische_min'], company['tische_max']) == (1, 4)
    assert (company['buerostuehle_min'], company['buerostuehle_max']) == (0, 2)
    assert 'Teilretouren' in company['hinweise']


def test_employee_basis_and_missing_enrichment(tmp_path):
    database = tmp_path / 'case.duckdb'
    import_data(TEST_DATA, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(f"""
            INSERT INTO "{CLIENTS_TABLE}"
            SELECT c.* REPLACE (id AS account_id) FROM "{CLIENTS_TABLE}" c
            CROSS JOIN (VALUES ('A-2'), ('A-3'), ('A-4')) AS accounts(id);
            INSERT INTO "{ENRICHMENT_TABLE}"
            SELECT * REPLACE ('A-2' AS account_id, 'Konzern' AS mitarbeitende_bezug,
                0.5 AS match_score)
            FROM "{ENRICHMENT_TABLE}" WHERE account_id = 'A-1';
            INSERT INTO "{ENRICHMENT_TABLE}"
            SELECT * REPLACE ('A-4' AS account_id, DATE '2020-01-01' AS stand)
            FROM "{ENRICHMENT_TABLE}" WHERE account_id = 'A-1';
            UPDATE "{ENRICHMENT_TABLE}"
            SET match_score = 0.5, gefundener_name = 'Abweichender Name'
            WHERE account_id = 'A-1'
        """)
    companies = {company['account_id']: company for company in merge_data(database)}
    assert len(companies) == 4
    assert companies['A-1']['mitarbeiterbasis'] == 'eingeschränkt'
    assert 'Match-Score unter 0.85' in companies['A-1']['hinweise']
    assert companies['A-2']['mitarbeiterbasis'] == 'nicht verwendbar'
    assert 'Konzern' in companies['A-2']['hinweise']
    assert companies['A-3']['mitarbeiterbasis'] == 'nicht verwendbar'
    assert companies['A-3']['anzahl_bestellungen'] == 0
    assert companies['A-4']['mitarbeiterbasis'] == 'eingeschränkt'
    assert companies['A-4']['mitarbeitende'] == 100  # Quellenwerte bleiben erhalten.
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(f'SELECT count(*) FROM "{COMPANY_PROFILES_TABLE}"').fetchone()[0] == 4


@pytest.mark.parametrize('score, expected', [
    (0.8499, 'eingeschränkt'),
    (0.85, 'verwendbar'),
    (0.95, 'verwendbar'),
])
def test_match_score_threshold(tmp_path, score, expected):
    database = tmp_path / 'case.duckdb'
    import_data(TEST_DATA, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(f'UPDATE "{ENRICHMENT_TABLE}" SET match_score = ?', [score])
    company, = merge_data(database)
    assert company['mitarbeiterbasis'] == expected
    assert ('Unsichere Firmenzuordnung: Match-Score unter 0.85' in company['hinweise']) == (score < 0.85)
