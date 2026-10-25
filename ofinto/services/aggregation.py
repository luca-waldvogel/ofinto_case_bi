from datetime import date
from pathlib import Path

import duckdb

from ..model import (
    CLIENTS_TABLE,
    COMPANY_PROFILES_TABLE,
    ENRICHMENT_TABLE,
    ORDER_ITEMS_TABLE,
    ORDERS_TABLE,
)

DEFAULT_AS_OF = date(2026, 10, 14)

# Annahme für den Case: Motion und Era zählen als Arbeitsplatzstühle, Go als
# Besprechungsstuhl. Bei neuen Produkten oder Namensänderungen diese Liste prüfen.
WORKPLACE_CHAIRS = ["Motion", "Era"]


def merge_data(database: Path, as_of: date = DEFAULT_AS_OF) -> int:
    """Firmenprofile speichern und ihre Anzahl zurückgeben.

    Die account_id bestimmt die Zuordnung. Teilretouren liefern Mengenbereiche,
    weil unbekannt ist, welche Positionen zurückgegeben wurden.
    """
    if not database.is_file():
        raise ValueError(f'Datenbank fehlt: {database}. Zuerst importieren.')

    with duckdb.connect(str(database)) as connection:
        connection.execute(f"""
            CREATE OR REPLACE TABLE "{COMPANY_PROFILES_TABLE}" AS
            WITH active_orders AS (
                SELECT * FROM "{ORDERS_TABLE}"
                WHERE status IN ('abgeschlossen', 'teilretoure') AND bestelldatum <= ?
            ), order_totals AS (
                SELECT account_id, count(*) AS anzahl_bestellungen,
                    max(bestelldatum) AS letzte_bestellung,
                    count(*) FILTER (WHERE status = 'teilretoure') AS teilretouren
                FROM active_orders GROUP BY account_id
            ), item_totals AS (
                SELECT o.account_id,
                    coalesce(sum(i.menge) FILTER (
                        WHERE i.kategorie = 'Tisch' AND o.status = 'abgeschlossen'
                    ), 0) AS tische_min,
                    coalesce(sum(i.menge) FILTER (
                        WHERE i.kategorie = 'Tisch'
                    ), 0) AS tische_max,
                    coalesce(sum(i.menge) FILTER (
                        WHERE list_contains(?, i.produkt) AND o.status = 'abgeschlossen'
                    ), 0) AS buerostuehle_min,
                    coalesce(sum(i.menge) FILTER (
                        WHERE list_contains(?, i.produkt)
                    ), 0) AS buerostuehle_max
                FROM active_orders o JOIN "{ORDER_ITEMS_TABLE}" i USING (order_id)
                GROUP BY o.account_id
            ), companies AS (
                SELECT c.*, e.* EXCLUDE (account_id),
                    coalesce(o.anzahl_bestellungen, 0) AS anzahl_bestellungen,
                    o.letzte_bestellung, coalesce(o.teilretouren, 0) AS teilretouren,
                    coalesce(i.tische_min, 0) AS tische_min,
                    coalesce(i.tische_max, 0) AS tische_max,
                    coalesce(i.buerostuehle_min, 0) AS buerostuehle_min,
                    coalesce(i.buerostuehle_max, 0) AS buerostuehle_max
                FROM "{CLIENTS_TABLE}" c
                LEFT JOIN "{ENRICHMENT_TABLE}" e USING (account_id)
                LEFT JOIN order_totals o USING (account_id)
                LEFT JOIN item_totals i USING (account_id)
            )
            SELECT *,
                CASE
                    WHEN mitarbeitende IS NULL OR mitarbeitende <= 0
                        OR mitarbeitende_bezug IS DISTINCT FROM 'Standort'
                        THEN 'nicht verwendbar'
                    WHEN match_score IS NULL OR match_score < 0.85 THEN 'eingeschränkt'
                    WHEN stand IS NULL OR stand < stichtag - INTERVAL '2 years'
                        OR stand > stichtag THEN 'eingeschränkt'
                    ELSE 'verwendbar'
                END AS mitarbeiterbasis,
                concat_ws('; ',
                    CASE WHEN mitarbeitende IS NULL OR mitarbeitende <= 0
                        THEN 'Mitarbeiterzahl fehlt oder ist ungültig' END,
                    CASE WHEN mitarbeitende_bezug = 'Konzern'
                        THEN 'Mitarbeiterzahl bezieht sich auf den Konzern'
                        WHEN mitarbeitende_bezug IS DISTINCT FROM 'Standort'
                        THEN 'Bezug der Mitarbeiterzahl ist unklar' END,
                    CASE WHEN match_score IS NULL THEN 'Match-Score fehlt'
                        WHEN match_score < 0.85
                        THEN 'Unsichere Firmenzuordnung: Match-Score unter 0.85' END,
                    CASE WHEN stand IS NULL THEN 'Aktualisierungsdatum fehlt'
                        WHEN stand < stichtag - INTERVAL '2 years'
                        THEN 'Firmendaten älter als zwei Jahre'
                        WHEN stand > stichtag THEN 'Firmendaten liegen nach dem Stichtag' END,
                    CASE WHEN teilretouren > 0
                        THEN 'Teilretouren: behaltene Produktmengen unbekannt' END
                ) AS hinweise
            FROM companies CROSS JOIN (SELECT ?::DATE AS stichtag)
        """, [as_of, WORKPLACE_CHAIRS, WORKPLACE_CHAIRS, as_of])
        row = connection.execute(
            f'SELECT count(*) FROM "{COMPANY_PROFILES_TABLE}"'
        ).fetchone()
        return row[0] if row else 0
