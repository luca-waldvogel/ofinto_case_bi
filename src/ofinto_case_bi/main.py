import csv
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from ofinto_case_bi.import_csv import import_data


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


if __name__ == "__main__":
    app()
