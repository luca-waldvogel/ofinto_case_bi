import csv
from pathlib import Path

import duckdb

from ofinto_case_bi.schemas import SCHEMAS


def validate_csv_header(source: Path, columns: dict[str, str]) -> None:
    """Nur die Kopfzeile auf erwartete Spalten und Reihenfolge prüfen."""
    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        if next(reader, None) != list(columns):
            raise ValueError(f"{source.name}: Spalten entsprechen nicht dem erwarteten Schema")


def import_data(data_dir: Path, database: Path) -> dict[str, int]:
    """Alle Tabellen ersetzen; bei jedem Fehler den gesamten Import zurückrollen."""
    counts = {}
    with duckdb.connect(str(database)) as connection:
        connection.execute("BEGIN TRANSACTION")
        try:
            for table, columns in SCHEMAS.items():
                source = data_dir / f"{table}.csv"
                validate_csv_header(source, columns)
                connection.execute(
                    f"""
                    CREATE OR REPLACE TABLE "{table}" AS
                    SELECT * FROM read_csv(
                        ?,
                        columns = ?,
                        header = true,
                        auto_detect = false,
                        dateformat = '%Y-%m-%d'
                    )
                    """,
                    [str(source), columns],
                )
                row = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()
                if row is None:
                    raise ValueError(f"{source.name}: Zeilenanzahl konnte nicht ermittelt werden")
                counts[table] = row[0]
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return counts
