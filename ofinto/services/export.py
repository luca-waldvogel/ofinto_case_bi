import csv
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from ..model.schemas import COMPANY_PROFILES_TABLE, POTENTIAL_TABLE

TOP_ORDER = "potenzial_min DESC, potenzial_max DESC, account_id"


def export_extracted_labels(database: Path) -> Path:
    """Gespeicherte Gesprächssignale im Format der Referenzlabels exportieren."""
    output_path = database.parent / "results" / "extraction" / "extrahierte_labels.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "call_id", "gespraechstyp", "kaufzeitpunkt", "arbeitsplaetze",
        "wettbewerber", "einwaende",
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        result = connection.execute(
            f"SELECT {', '.join(columns)} FROM transcript_signals ORDER BY call_id"
        )
        with TemporaryDirectory(prefix=".extraction-", dir=output_path.parent) as temporary:
            target = Path(temporary) / output_path.name
            with target.open("w", newline="", encoding="utf-8") as destination:
                writer = csv.writer(destination)
                writer.writerow(columns)
                while batch := result.fetchmany(1000):
                    for call_id, kind, timing, workplaces, competitors, objections in batch:
                        writer.writerow((
                            call_id, kind, timing, workplaces,
                            "; ".join(competitors), "; ".join(objections),
                        ))
            target.replace(output_path)
    return output_path


def export_aggregate(database: Path, output_path: Path) -> None:
    """Die vollständigen Firmenprofile als CSV nach Kunden-ID exportieren."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database), read_only=True) as connection:
        with TemporaryDirectory(prefix=".aggregate-", dir=output_path.parent) as temporary:
            target = Path(temporary) / output_path.name
            connection.execute(
                f"COPY (SELECT * FROM {COMPANY_PROFILES_TABLE} ORDER BY account_id) "
                "TO ? (FORMAT CSV, HEADER TRUE)", [str(target)],
            )
            target.replace(output_path)


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
