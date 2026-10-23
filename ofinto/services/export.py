"""Potenzialtabelle als drei CSV-Dateien exportieren."""

from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from ..model.schemas import POTENTIAL_TABLE

TOP_ORDER = "potenzial_min DESC, potenzial_max DESC, account_id"


def export_potential(database: Path, output_dir: Path = Path("data/potential")) -> None:
    """Gespeicherte Potenziale sortieren und bestehende CSVs erst nach Erfolg ersetzen."""
    if not database.is_file():
        raise ValueError(f"Datenbank fehlt: {database}. Zuerst potential ausführen.")
    output_dir.mkdir(parents=True, exist_ok=True)
    queries = {
        "kundenpotenziale.csv": f"SELECT * FROM {POTENTIAL_TABLE} ORDER BY account_id",
        "top15.csv": f"""SELECT row_number() OVER (ORDER BY {TOP_ORDER}) AS rang,
            * FROM {POTENTIAL_TABLE}
            WHERE bewertbar AND potenzial_max > 0
            ORDER BY {TOP_ORDER} LIMIT 15""",
        "nicht_bewertbar.csv": f"""SELECT account_id, firmenname,
            mitarbeiterbasis, hinweise, stichtag, regelversion
            FROM {POTENTIAL_TABLE} WHERE NOT bewertbar ORDER BY account_id""",
    }
    with duckdb.connect(str(database)) as connection:
        with TemporaryDirectory(prefix=".potential-", dir=output_dir) as temporary:
            for filename, query in queries.items():
                target = Path(temporary) / filename
                connection.execute(
                    f"COPY ({query}) TO ? (FORMAT CSV, HEADER TRUE)", [str(target)],
                )
            for filename in queries:
                (Path(temporary) / filename).replace(output_dir / filename)
