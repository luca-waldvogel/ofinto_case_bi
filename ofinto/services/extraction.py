import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from ..programs import ExtractionProgram
from ..clients import PromptClient
from ..config import ExtractionPromptConfig
from .export import export_extracted_labels

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
        conversation_date = conversation_date.replace(tzinfo=timezone.utc)
    return Transcript(
        source.stem, title, conversation_date.astimezone(timezone.utc), text,
    )


@dataclass
class ExtractionSummary:
    extracted: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    csv_path: Path | None = None


def extract_signals(
    transcript_dir: Path,
    database: Path,
) -> ExtractionSummary:
    logger.info(f"Suche Transkripte in {transcript_dir}")
    sources = sorted(transcript_dir.glob("*.txt"))
    if not sources:
        raise ValueError(f"Keine .txt-Transkripte gefunden: {transcript_dir}")
    config = ExtractionPromptConfig.from_env()
    client = PromptClient(ExtractionProgram, config)
    summary = ExtractionSummary()
    logger.info(f"Extraktion startet: {len(sources)} Dateien; Modell={config.model}")
    with client, duckdb.connect(str(database)) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS transcript_signals (
                call_id VARCHAR PRIMARY KEY, title VARCHAR NOT NULL,
                conversation_date TIMESTAMPTZ NOT NULL,
                gespraechstyp VARCHAR NOT NULL, kaufzeitpunkt VARCHAR NOT NULL,
                arbeitsplaetze BIGINT, wettbewerber VARCHAR[] NOT NULL,
                einwaende VARCHAR[] NOT NULL
            )
        """)
        for index, source in enumerate(sources, start=1):
            progress = f"[{index}/{len(sources)}] {source.stem}"
            try:
                logger.info(f"{progress}: starte Extraktion")
                transcript = read_transcript(source)
                result = client.run(transcript.text)
                connection.execute("""
                    INSERT OR REPLACE INTO transcript_signals (
                        call_id, title, conversation_date, gespraechstyp, kaufzeitpunkt,
                        arbeitsplaetze, wettbewerber, einwaende
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    transcript.call_id, transcript.title, transcript.conversation_date,
                    result.gespraechstyp, result.kaufzeitpunkt, result.arbeitsplaetze,
                    result.wettbewerber, result.einwaende,
                ])
                summary.extracted += 1
                logger.info(f"{progress}: Ergebnis gespeichert")
            except (OSError, ValueError, RuntimeError, duckdb.Error) as error:
                summary.errors[source.stem] = str(error)
                logger.error(f"{progress}: fehlgeschlagen: {error}")
    logger.info(
        f"Extraktion beendet: {summary.extracted} extrahiert, {len(summary.errors)} Fehler"
    )
    summary.csv_path = export_extracted_labels(database)
    return summary
