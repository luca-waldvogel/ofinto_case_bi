import csv
import logging
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from .config import PotentialConfig
from .services.aggregation import DEFAULT_AS_OF
from .services.aggregation import merge_data
from .services.extraction import extract_transcripts as extract_signals
from .services.export import export_potential
from .services.import_csv import import_data
from .services.potential import estimate_potential


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """ofinto BI: lokale Daten importieren und analysieren."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("ofinto").setLevel(logging.INFO)
    logging.getLogger("openai._base_client").setLevel(logging.INFO)


@app.command("import")
def import_csv(
    data_dir: Annotated[
        Path,
        typer.Option(
            "--data-dir",
            exists=True,
            file_okay=False,
            resolve_path=True,
            help="Ordner mit den vier Quell-CSV-Dateien.",
        ),
    ] = Path("data"),
    database: Annotated[
        Path,
        typer.Option(
            "--database",
            dir_okay=False,
            resolve_path=True,
            help="DuckDB-Zieldatei. Der übergeordnete Ordner muss existieren.",
        ),
    ] = Path("data/case.duckdb"),
) -> None:
    """Die vier CSV-Tabellen importieren und vorhandene Tabellen atomar ersetzen."""
    try:
        counts = import_data(data_dir, database)
    except (duckdb.Error, OSError, ValueError, csv.Error) as error:
        typer.secho(f"Import fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    typer.secho(f"Import erfolgreich: {database}", fg=typer.colors.GREEN)
    for table, count in counts.items():
        typer.echo(f"  {table}: {count} Zeilen importiert")


@app.command("aggregate")
def aggregate(
    database: Annotated[Path, typer.Option("--database", dir_okay=False, resolve_path=True)] = Path("data/case.duckdb"),
    as_of: Annotated[str, typer.Option("--as-of", help="Stichtag im Format YYYY-MM-DD.")] = DEFAULT_AS_OF.isoformat(),
) -> None:
    """Firmen verbinden und Produktmengen aggregieren."""
    try:
        companies = merge_data(database, date.fromisoformat(as_of))
    except (duckdb.Error, OSError, ValueError) as error:
        typer.secho(f"Aggregation fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    typer.secho(f"Aggregation erfolgreich: {database} (Stichtag {as_of})", fg=typer.colors.GREEN)
    typer.echo(f"  company_profiles: {len(companies)} Firmen")


@app.command("potential")
def potential(
    database: Annotated[Path, typer.Option("--database", dir_okay=False, resolve_path=True)] = Path("data/case.duckdb"),
    as_of: Annotated[str, typer.Option("--as-of", help="Stichtag im Format YYYY-MM-DD.")] = DEFAULT_AS_OF.isoformat(),
) -> None:
    """Potenzial seit Erstbestellung berechnen und in DuckDB speichern."""
    try:
        config = PotentialConfig()
        summary = estimate_potential(database, config, date.fromisoformat(as_of))
        typer.echo(f"Potenzialschätzung: {summary.total} Kunden; "
                   f"{summary.evaluated} bewertet; {summary.excluded} nicht bewertbar")
        typer.echo(f"Stichtag: {as_of}; Regelversion {config.rule_version}; Top-Kandidaten: {summary.top_count}")
    except (duckdb.Error, OSError, ValueError, KeyError) as error:
        typer.secho(f"Potenzialschätzung fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


@app.command("export")
def export(
    database: Annotated[Path, typer.Option("--database", dir_okay=False, resolve_path=True)] = Path("data/case.duckdb"),
    output_dir: Annotated[Path, typer.Option("--output-dir", file_okay=False, resolve_path=True)] = Path("data/potential"),
) -> None:
    """Gespeicherte Potenziale als CSV exportieren."""
    try:
        export_potential(database, output_dir)
        typer.echo(f"Exporte: {output_dir}")
        typer.echo("Top 15 | Konto | Firma | Potenzial (Plätze) | Jahresbedarf (Plätze)")
        with (output_dir / "top15.csv").open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                typer.echo(f"  {row['rang']} | {row['account_id']} | {row['firmenname']} | "
                           f"{row['potenzial_min']}–{row['potenzial_max']} | "
                           f"{row['jahresbedarf_min']}–{row['jahresbedarf_max']}")
        typer.echo("Nicht seriös bewertbare Kunden | Mitarbeiterbasis | Begründung")
        with (output_dir / "nicht_bewertbar.csv").open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                typer.echo(f"  {row['account_id']} | {row['firmenname']} | "
                           f"{row['mitarbeiterbasis']} | {row['hinweise']}")
    except (duckdb.Error, OSError, ValueError, csv.Error) as error:
        typer.secho(f"Export fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


@app.command("ci")
@app.command("run")
def run(
    database: Annotated[Path, typer.Option("--database", dir_okay=False, resolve_path=True)] = Path("data/case.duckdb"),
    as_of: Annotated[str, typer.Option("--as-of", help="Stichtag im Format YYYY-MM-DD.")] = DEFAULT_AS_OF.isoformat(),
    output_dir: Annotated[Path, typer.Option("--output-dir", file_okay=False, resolve_path=True)] = Path("data/potential"),
) -> None:
    """aggregate, potential und export nacheinander ausführen."""
    aggregate(database, as_of)
    potential(database, as_of)
    export(database, output_dir)


@app.command("extract-transcripts")
def extract_transcripts(
    transcript_dir: Annotated[Path, typer.Option("--transcript-dir", exists=True, file_okay=False)] = Path("data/transkripte"),
    database: Annotated[Path, typer.Option("--database", dir_okay=False)] = Path("data/case.duckdb"),
) -> None:
    """Die fünf Pflichtsignale extrahieren und separat in DuckDB speichern."""
    try:
        summary = extract_signals(transcript_dir, database)
    except (duckdb.Error, OSError, ValueError) as error:
        typer.secho(f"Extraktion fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Extrahiert: {summary.extracted}; Fehler: {len(summary.errors)}")
    for call_id, error in summary.errors.items():
        typer.secho(f"  {call_id}: {error}", fg=typer.colors.RED, err=True)
    if summary.errors:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
