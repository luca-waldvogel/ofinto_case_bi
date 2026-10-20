import csv
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from .import_csv import import_data
from .merge import DEFAULT_AS_OF, merge_data


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """ofinto BI: lokale Daten importieren und analysieren."""


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
            typer.echo(f"  {company['account_id']} | {company['firmenname']} | {company['hinweise']}")


if __name__ == "__main__":
    app()
