import csv
import json
import logging
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from .config import PotentialConfig
from .services.aggregation import DEFAULT_AS_OF
from .services.aggregation import merge_data
from .services.assistant import answer_question, evaluate_questions
from .services.extraction import extract_signals
from .services.export import export_aggregate, export_potential
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
    """Firmen aggregieren und die Profile als CSV exportieren."""
    output_path = database.parent / "results" / "aggregate" / "company_profiles.csv"
    try:
        companies = merge_data(database, date.fromisoformat(as_of))
        export_aggregate(database, output_path)
    except (duckdb.Error, OSError, ValueError) as error:
        typer.secho(f"Aggregation fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    typer.secho(f"Aggregation erfolgreich: {database} (Stichtag {as_of})", fg=typer.colors.GREEN)
    typer.echo(f"  company_profiles: {len(companies)} Firmen")
    typer.echo(f"  CSV-Export: {output_path}")


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
    output_dir: Annotated[Path, typer.Option("--output-dir", file_okay=False, resolve_path=True)] = Path("data/results/potential"),
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
    """Gesprächssignale extrahieren, speichern und als CSV exportieren."""
    try:
        summary = extract_signals(transcript_dir, database)
    except (duckdb.Error, OSError, ValueError, csv.Error) as error:
        typer.secho(f"Extraktion fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Extrahiert: {summary.extracted}; Fehler: {len(summary.errors)}")
    typer.echo(f"CSV-Export: {summary.csv_path}")
    for call_id, error in summary.errors.items():
        typer.secho(f"  {call_id}: {error}", fg=typer.colors.RED, err=True)
    if summary.errors:
        raise typer.Exit(code=1)


@app.command("ask")
def ask(
    question: Annotated[str, typer.Option("--question", help="Frage an die B2B-Daten.")],
    database: Annotated[Path, typer.Option("--database", dir_okay=False)] = Path("data/case.duckdb"),
    details: Annotated[
        bool,
        typer.Option("--details", help="Zusätzlich SQL-Abfrage und Ergebnisdaten ausgeben."),
    ] = False,
) -> None:
    """Eine Frage beantworten; mit --details auch SQL und Ergebnisdaten ausgeben."""
    try:
        result = answer_question(database, question)
    except (duckdb.Error, OSError, ValueError, RuntimeError) as error:
        typer.secho(f"Assistent fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    if details:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    else:
        # Direkt ausgeben, damit tatsächliche Zeilenumbrüche lesbar erscheinen.
        typer.echo(result.answer.replace("\\n", "\n"))


@app.command("evaluate-assistant")
def evaluate_assistant(
    questions_file: Annotated[Path, typer.Option("--questions-file", exists=True, dir_okay=False)] = Path("data/testfragen.csv"),
    output_file: Annotated[Path, typer.Option("--output-file", dir_okay=False)] = Path("data/results/assistant_evaluation.json"),
    database: Annotated[Path, typer.Option("--database", dir_okay=False)] = Path("data/case.duckdb"),
) -> None:
    """Die Case-Fragen über die freie Text-to-SQL-Abfrage auswerten."""
    try:
        evaluate_questions(database, questions_file, output_file)
    except (duckdb.Error, OSError, ValueError, RuntimeError, csv.Error) as error:
        typer.secho(f"Evaluation fehlgeschlagen: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Assistenten-Evaluation: {output_file}")


if __name__ == "__main__":
    app()
