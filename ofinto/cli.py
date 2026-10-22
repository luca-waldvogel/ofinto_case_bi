import csv
import logging
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from .services import DEFAULT_AS_OF, import_data, merge_data
from .services import extract_transcripts as extract_signals


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
    """Firmen verbinden, Produktmengen aggregieren und Mitarbeiterbasis einordnen."""
    try:
        companies = merge_data(database, date.fromisoformat(as_of))
    except (duckdb.Error, OSError, ValueError) as error:
        typer.secho(f"Aggregation fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    typer.secho(f"Aggregation erfolgreich: {database} (Stichtag {as_of})", fg=typer.colors.GREEN)
    typer.echo(f"  company_profiles: {len(companies)} Firmen")
    for quality, count in Counter(company['mitarbeiterbasis'] for company in companies).items():
        typer.echo(f"  {quality}: {count}")
    for company in companies:
        if company['hinweise']:
            typer.echo(f"  {company['account_id']} | {company['firmenname']} | {company['mitarbeiterbasis']} | {company['hinweise']}")


@app.command("extract-transcripts")
def extract_transcripts(
    transcript_dir: Annotated[Path, typer.Option("--transcript-dir", exists=True, file_okay=False)] = Path("data/transkripte"),
    database: Annotated[Path, typer.Option("--database", dir_okay=False)] = Path("data/case.duckdb"),
    model: Annotated[str | None, typer.Option("--model", help="Überschreibt OPENAI_MODEL.")] = None,
) -> None:
    """Die fünf Pflichtsignale extrahieren und separat in DuckDB speichern."""
    try:
        summary = extract_signals(transcript_dir, database, model=model)
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
