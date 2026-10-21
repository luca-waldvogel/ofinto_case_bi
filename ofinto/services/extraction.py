"""Transkripte lokal laden, auswerten und Ergebnisse speichern."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from ..programs.extraction import ExtractionProgram
from ..clients.prompt import PromptClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcript:
    call_id: str
    title: str
    conversation_date: datetime
    text: str


def read_transcript(source: Path) -> Transcript:
    text = source.read_text(encoding="utf-8-sig")
    headers, separator, body = text.partition("Sentences:")
    if not separator or not body.strip():
        raise ValueError("Fireflies-Abschnitt Sentences fehlt oder ist leer")
    metadata = dict(
        line.split(":", 1) for line in headers.splitlines() if ":" in line
    )
    title = metadata.get("Title", "").strip()
    if not title:
        raise ValueError("Title fehlt")
    date_text = metadata.get("Date", "").strip()
    try:
        conversation_date = datetime.fromisoformat(date_text)
    except ValueError as error:
        raise ValueError("Date fehlt oder ist kein ISO-Zeitstempel") from error
    if conversation_date.tzinfo is None:
        raise ValueError("Date benötigt eine Zeitzone")
    return Transcript(
        source.stem, title, conversation_date.astimezone(timezone.utc), text,
    )


@dataclass
class ExtractionSummary:
    extracted: int = 0
    errors: dict[str, str] = field(default_factory=dict)


def extract_transcripts(
    transcript_dir: Path,
    database: Path,
    *,
    model: str | None = None,
) -> ExtractionSummary:
    logger.info("Suche Transkripte in %s", transcript_dir)
    sources = sorted(transcript_dir.glob("*.txt"))
    if not sources:
        raise ValueError(f"Keine .txt-Transkripte gefunden: {transcript_dir}")
    client = PromptClient(ExtractionProgram, model=model)
    summary = ExtractionSummary()
    logger.info("Extraktion startet: %d Dateien; Modell=%s", len(sources), client.model)
    with client, duckdb.connect(str(database)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS transcript_signals (
                call_id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL,
                conversation_date TIMESTAMPTZ NOT NULL,
                gespraechstyp VARCHAR NOT NULL, kaufzeitpunkt VARCHAR NOT NULL,
                arbeitsplaetze BIGINT, wettbewerber VARCHAR[] NOT NULL,
                einwaende VARCHAR[] NOT NULL,
                model VARCHAR NOT NULL, response_model VARCHAR,
                processed_at TIMESTAMPTZ NOT NULL, usage JSON
            )
        """)
        for index, source in enumerate(sources, start=1):
            progress = f"[{index}/{len(sources)}] {source.stem}"
            try:
                logger.info("%s: starte Extraktion", progress)
                transcript = read_transcript(source)
                result = client.run(transcript.text)
                connection.execute("""
                    INSERT OR REPLACE INTO transcript_signals (
                        call_id, title, conversation_date, gespraechstyp, kaufzeitpunkt,
                        arbeitsplaetze, wettbewerber, einwaende, model, response_model,
                        processed_at, usage
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    transcript.call_id, transcript.title, transcript.conversation_date,
                    result.gespraechstyp, result.kaufzeitpunkt, result.arbeitsplaetze,
                    result.wettbewerber, result.einwaende, client.model,
                    client.response_model, datetime.now(timezone.utc),
                    json.dumps(client.usage),
                ])
                summary.extracted += 1
                logger.info("%s: Ergebnis gespeichert", progress)
            except (OSError, ValueError, RuntimeError, duckdb.Error) as error:
                summary.errors[source.stem] = str(error)
                logger.error("%s: fehlgeschlagen: %s", progress, error)
    logger.info(
        "Extraktion beendet: %d extrahiert, %d Fehler",
        summary.extracted, len(summary.errors),
    )
    return summary
