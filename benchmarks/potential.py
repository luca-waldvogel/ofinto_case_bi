"""Lokaler Lasttest: python -m benchmarks.potential (standardmäßig 10 Mio. Positionen)."""

import argparse
import csv
import json
import resource
import sys
from datetime import date
from math import ceil, floor
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import duckdb

from ofinto.config import PotentialConfig
from ofinto.services.aggregation import DEFAULT_AS_OF, merge_data
from ofinto.services.import_csv import import_data
from ofinto.services.potential import estimate_potential
from ofinto.services.export import export_potential


def generate_data(database: Path, customers: int, orders_per_customer: int,
                  items_per_order: int) -> None:
    """Große Rohdatentabellen direkt in DuckDB erzeugen, ohne Python-Zeilenlisten."""
    fixture = Path(__file__).resolve().parents[1] / "tests/test_data/valid"
    import_data(fixture, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute("""CREATE OR REPLACE TABLE firmenkunden AS
            SELECT * EXCLUDE (i) REPLACE (
                concat(account_id, '-', i) AS account_id,
                make_date(2022 + (i % 5)::INTEGER, 1, 2) AS erste_bestellung
            ) FROM firmenkunden CROSS JOIN range(?) AS sequence(i)
        """, [customers])
        connection.execute("""CREATE OR REPLACE TABLE firmendaten_anreicherung AS
            SELECT * EXCLUDE (i) REPLACE (
                concat(account_id, '-', i) AS account_id,
                CASE WHEN i % 5 = 0 THEN 0.6 ELSE 0.95 END AS match_score
            ) FROM firmendaten_anreicherung CROSS JOIN range(?) AS sequence(i)
        """, [customers])
        connection.execute("""CREATE OR REPLACE TABLE bestellungen AS
            SELECT * EXCLUDE (i, j) REPLACE (
                concat(order_id, '-', i, '-', j) AS order_id,
                concat(account_id, '-', i) AS account_id,
                CASE WHEN j % 20 = 19 THEN DATE '2026-10-21'
                    ELSE make_date(2022 + (i % 5)::INTEGER, 1, 2)
                        + ((j * date_diff('day',
                            make_date(2022 + (i % 5)::INTEGER, 1, 2),
                            DATE '2026-09-30')) // ?)::INTEGER
                END AS bestelldatum,
                CASE WHEN j % 20 BETWEEN 12 AND 14 THEN 'teilretoure'
                    WHEN j % 20 BETWEEN 15 AND 16 THEN 'retoure'
                    WHEN j % 20 BETWEEN 17 AND 18 THEN 'storniert'
                    ELSE 'abgeschlossen' END AS status
            ) FROM bestellungen CROSS JOIN range(?) AS customers(i)
                CROSS JOIN range(?) AS orders(j)
        """, [orders_per_customer, customers, orders_per_customer])
        connection.execute("""CREATE OR REPLACE TABLE bestellpositionen AS
            SELECT o.order_id,
                CASE k % 5 WHEN 0 THEN 'Elevate' WHEN 1 THEN 'Motion'
                    WHEN 2 THEN 'Go' WHEN 3 THEN 'Focus Pod S'
                    ELSE 'Monitorarm Duo' END AS produkt,
                CASE k % 5 WHEN 0 THEN 'Tisch' WHEN 1 THEN 'Stuhl'
                    WHEN 2 THEN 'Stuhl' WHEN 3 THEN 'Raumsystem'
                    ELSE 'Zubehör' END AS kategorie,
                1::BIGINT AS menge, 100::DECIMAL(18,2) AS stueckpreis_netto,
                o.waehrung
            FROM bestellungen o CROSS JOIN range(?) AS positions(k)
        """, [items_per_order])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customers", type=int, default=100_000)
    parser.add_argument("--orders-per-customer", type=int, default=20)
    parser.add_argument("--items-per-order", type=int, default=5)
    args = parser.parse_args()
    if min(args.customers, args.orders_per_customer, args.items_per_order) <= 0:
        parser.error("Alle Größen müssen positiv sein")
    with TemporaryDirectory(prefix="ofinto-benchmark-") as temporary:
        root = Path(temporary)
        database = root / "case.duckdb"
        print("Erzeuge synthetische Bestellhistorie …", file=sys.stderr, flush=True)
        generation_start = perf_counter()
        generate_data(database, args.customers, args.orders_per_customer, args.items_per_order)
        generation_seconds = perf_counter() - generation_start
        print("Berechne Aggregation, Python-Regeln und CSV-Exporte …", file=sys.stderr, flush=True)
        start = perf_counter()
        merge_data(database)
        summary = estimate_potential(database, PotentialConfig())
        export_potential(database, root / "exports")
        elapsed = perf_counter() - start
        # Unabhängige Gegenrechnung für die erste bewertbare Firma (i = 1).
        active = [j for j in range(args.orders_per_customer)
                  if j % 20 < 15]
        complete = [j for j in active if j % 20 < 12]
        tables_per_order = sum(k % 5 == 0 for k in range(args.items_per_order))
        chairs_per_order = sum(k % 5 == 1 for k in range(args.items_per_order))
        with duckdb.connect(str(database), read_only=True) as connection:
            assert summary.total == args.customers
            assert summary.excluded == (args.customers + 4) // 5
            assert summary.evaluated + summary.excluded == args.customers
            for table, count in [
                ("bestellungen", args.customers * args.orders_per_customer),
                ("bestellpositionen", args.customers * args.orders_per_customer * args.items_per_order),
                ("company_potential", args.customers),
            ]:
                count_row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
                assert count_row is not None
                assert count_row[0] == count
            invalid_row = connection.execute("""SELECT count(*) FROM company_potential
                WHERE bewertbar AND (potenzial_min < 0 OR potenzial_min > potenzial_max
                    OR potenzial_min IS NULL OR potenzial_max IS NULL)
            """).fetchone()
            assert invalid_row is not None
            assert invalid_row[0] == 0
            if args.customers > 1:
                row = connection.execute("""SELECT anzahl_bestellungen,
                    tische_min, tische_max, buerostuehle_min, buerostuehle_max,
                    p.potenzial_min, p.potenzial_max
                    FROM company_profiles JOIN company_potential p USING (account_id)
                    WHERE account_id = 'A-1-1'""").fetchone()
                assert row is not None
                expected_years = (DEFAULT_AS_OF - date(2023, 1, 2)).days / PotentialConfig().days_per_year
                supplied_min = len(complete) * (tables_per_order + chairs_per_order) * 0.5
                supplied_max = len(active) * (tables_per_order + chairs_per_order) * 0.5
                assert row[:5] == (len(active), len(complete) * tables_per_order,
                                   len(active) * tables_per_order,
                                   len(complete) * chairs_per_order,
                                   len(active) * chairs_per_order)
                assert row[5] == floor(max(0, 70 * expected_years / 10 - supplied_max))
                assert row[6] == ceil(max(0, 100 * expected_years / 10 - supplied_min))
        expected_counts = {"kundenpotenziale.csv": summary.total,
                           "nicht_bewertbar.csv": summary.excluded,
                           "top15.csv": summary.top_count}
        for name, expected in expected_counts.items():
            with ((root / "exports") / name).open(newline="", encoding="utf-8") as source:
                assert sum(1 for _ in csv.DictReader(source)) == expected
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_mib = peak / (1024 ** 2 if sys.platform == "darwin" else 1024)
        print(json.dumps({
            "customers": summary.total, "evaluated": summary.evaluated,
            "excluded": summary.excluded,
            "orders": args.customers * args.orders_per_customer,
            "order_items": args.customers * args.orders_per_customer * args.items_per_order,
            "generation_seconds": round(generation_seconds, 3),
            "analysis_and_export_seconds": round(elapsed, 3),
            "process_peak_mib": round(peak_mib, 1),
            "database_mib": round(database.stat().st_size / 1024 ** 2, 1),
            "csv_bytes": sum(p.stat().st_size for p in (root / "exports").glob("*.csv")),
            "validation": "passed",
        }, indent=2))


if __name__ == "__main__":
    main()
