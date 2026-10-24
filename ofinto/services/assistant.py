from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from ..clients import PromptClient
from ..config import AssistantPromptConfig
from ..programs import AnswerProgram, SQLProgram

FIELD_DESCRIPTIONS = {
    "account_id": "Eindeutige Kunden-ID; verbindet Kundendaten, Bestellungen und Profile.",
    "land_rechnung": "Land der Rechnungsadresse; kein Regions- oder Sprachmerkmal.",
    "region": "Verkaufsregion des Kunden, z. B. Romandie; kein Sprach- oder Landescode.",
    "sprache": "Bevorzugte Korrespondenzsprache, z. B. de oder fr; keine Region.",
    "bestelldatum": "Datum der Bestellung.",
    "bestellwert_netto": "Nettowert einer Bestellung in der zugehörigen Währung.",
    "waehrung": "Währung des Bestell- oder Positionsbetrags; Währungen nicht addieren.",
    "retourenwert": "Erfasster Retourenwert der Bestellung.",
    "status": "Bestellstatus; Profile berücksichtigen abgeschlossene Bestellungen und Teilretouren.",
    "match_score": "Qualität der Zuordnung externer Firmendaten zum Kunden; höher bedeutet sicherer.",
    "mitarbeitende": "Mitarbeiterzahl aus externen Firmendaten; Bezug in mitarbeitende_bezug beachten.",
    "mitarbeitende_bezug": "Gibt an, ob die Mitarbeiterzahl den Standort oder Konzern beschreibt.",
    "stand": "Datum, zu dem externe Firmendaten aktualisiert wurden.",
    "stichtag": "Datenstichtag des aggregierten Firmenprofils.",
    "letzte_bestellung": "Datum der letzten berücksichtigten Bestellung im Profil.",
    "anzahl_bestellungen": "Anzahl der im Profil berücksichtigten Bestellungen.",
    "hinweise": "Qualitätshinweise oder Einschränkungen zum Profil bzw. Potenzial.",
    "potenzial_min": "Untere Schätzung der noch nicht versorgten Arbeitsplätze über den Beobachtungszeitraum.",
    "potenzial_max": "Obere Schätzung der noch nicht versorgten Arbeitsplätze über den Beobachtungszeitraum.",
    "jahresbedarf_min": "Untere Schätzung des jährlichen Ersatzbedarfs an Arbeitsplätzen.",
    "jahresbedarf_max": "Obere Schätzung des jährlichen Ersatzbedarfs an Arbeitsplätzen.",
    "bewertbar": "Gibt an, ob die regelbasierte Potenzialschätzung ausreichend verlässliche Eingangsdaten hat.",
    "regelversion": "Version der Regeln, mit denen das Potenzial berechnet wurde.",
}


@dataclass
class AssistantAnswer:
    answer: str
    sql: str
    result: list[dict[str, Any]]
    data_as_of: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def database_schema(database: Path) -> tuple[str, str | None]:
    """Tabellen und Spalten sowie, falls vorhanden, den Datenstichtag lesen."""
    if not database.is_file():
        raise ValueError(f"Datenbank fehlt: {database}")
    
    with duckdb.connect(str(database), read_only=True) as con:
        tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
        lines = []
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"' # TODO: WHY?
            columns = con.execute(f"DESCRIBE {quoted}").fetchall()
            fields = ", ".join(
                f"{name} {kind}"
                + (f" -- {FIELD_DESCRIPTIONS[name]}" if name in FIELD_DESCRIPTIONS else "")
                for name, kind, *_ in columns
            )
            lines.append(f"{table}({fields})")
        data_as_of = None
        if "company_profiles" in tables:
            row = con.execute("SELECT max(stichtag) FROM company_profiles").fetchone()
            if row and row[0]:
                data_as_of = row[0].isoformat()
    return "\n".join(lines), data_as_of


def execute_sql(database: Path, sql: str) -> list[dict[str, Any]]:
    """Die modellgenerierte Abfrage direkt read-only ausführen und maximal 100 Zeilen lesen."""
    with duckdb.connect(str(database), read_only=True) as con:
        # Verhindert Dateizugriffe aus SQL; es gibt keine eigene SQL-Prüfschicht.
        con.execute("SET enable_external_access = false")
        result = con.execute(sql)
        columns = [item[0] for item in result.description or []]
        return [dict(zip(columns, (_value(value) for value in row)))
                for row in result.fetchmany(100)]


def answer_question(database: Path, question: str) -> AssistantAnswer:
    if not question.strip():
        raise ValueError("Frage ist leer")
    schema, data_as_of = database_schema(database)
    sql_config = AssistantPromptConfig.from_env()
    with PromptClient(SQLProgram, sql_config) as client:
        sql = client.run(f"{schema}\n\nFrage: {question}")

    error = None
    try:
        result = execute_sql(database, sql)
        execution = {"zeilen": result, "abgeschnitten": len(result) == 100}
    except Exception as exception:
        result = []
        error = f"{type(exception).__name__}: {exception}"
        execution = {"sql_fehler": error, "zeilen": []}

    response_input = json.dumps({
        "frage": question,
        "datenstichtag": data_as_of,
        "sql": sql,
        "ausführung": execution,
    }, ensure_ascii=False, default=str)
    answer_config = AssistantPromptConfig.from_env()
    with PromptClient(AnswerProgram, answer_config) as client:
        answer = client.run(response_input)

    return AssistantAnswer(answer, sql, result, data_as_of, error)


def evaluate_questions(database: Path, questions_file: Path, output_file: Path) -> None:
    with questions_file.open(newline="", encoding="utf-8-sig") as source:
        questions = list(csv.DictReader(source))
    results = []
    for row in questions:
        answer = answer_question(database, row["frage"])
        results.append({"frage_id": row["frage_id"], "frage": row["frage"], **answer.to_dict()})
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n",
                           encoding="utf-8")
