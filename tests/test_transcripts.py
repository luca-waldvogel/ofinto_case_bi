from unittest.mock import MagicMock, Mock

import duckdb
import pytest
from typer.testing import CliRunner

from ofinto.cli import app
from ofinto.model import TranscriptSignals
from ofinto.clients import PromptClient
from ofinto.services import extract_transcripts, read_transcript


def signals(**overrides):
    return TranscriptSignals(**({
        "gespraechstyp": "Verkaufsgespräch", "kaufzeitpunkt": "0-3 Monate",
        "arbeitsplaetze": 3, "wettbewerber": [], "einwaende": ["Montage/Service"],
    } | overrides))


def write_transcript(directory, call_id="C01", body="Bonjour, trois postes à Genève."):
    source = directory / f"{call_id}.txt"
    source.write_text(
        "Title: Exemple\nDate: 2026-09-15T08:10:00.000Z\nDuration: 8.6\n"
        f"Participants: client@example.ch\n\nSentences:\n[00:01 - 00:10] Client: {body}\n",
        encoding="utf-8",
    )
    return source


def mock_client(result=None):
    client = MagicMock(spec=PromptClient)
    client.__enter__.return_value = client
    client.model = "test-model"
    client.run.return_value = result if result is not None else signals()
    return client


def test_fireflies_metadata(tmp_path):
    source = write_transcript(tmp_path)
    result = read_transcript(source)
    assert result.call_id == "C01"
    assert result.title == "Exemple"
    assert result.conversation_date.isoformat() == "2026-09-15T08:10:00+00:00"


@pytest.mark.parametrize("bad", [
    "Title: Exemple\nDate: invalide\nSentences:\nTexte",
    "Date: 2026-09-15T08:10:00Z\nSentences:\nTexte",
    "Title: Exemple\nDate: 2026-09-15T08:10:00\nSentences:\nTexte",
    "Title: Exemple\nDate: 2026-09-15T08:10:00Z\nSentences:\n",
])
def test_invalid_headers(tmp_path, bad):
    source = tmp_path / "C01.txt"
    source.write_text(bad)
    with pytest.raises(ValueError):
        read_transcript(source)


def test_each_run_extracts_and_replaces_existing_result(tmp_path, monkeypatch):
    source = write_transcript(tmp_path)
    database = tmp_path / "case.duckdb"
    client = mock_client()
    monkeypatch.setattr("ofinto.services.extraction.PromptClient", Mock(return_value=client))
    assert extract_transcripts(tmp_path, database).extracted == 1
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT call_id, arbeitsplaetze, einwaende FROM transcript_signals").fetchone() == (
            "C01", 3, ["Montage/Service"],
        )
    client.run.return_value = signals(arbeitsplaetze=7)
    assert extract_transcripts(tmp_path, database).extracted == 1
    assert client.run.call_count == 2
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT call_id, arbeitsplaetze FROM transcript_signals").fetchall() == [("C01", 7)]


def test_failed_refresh_preserves_values(tmp_path, monkeypatch):
    write_transcript(tmp_path)
    database = tmp_path / "case.duckdb"
    client = mock_client()
    monkeypatch.setattr("ofinto.services.extraction.PromptClient", Mock(return_value=client))
    extract_transcripts(tmp_path, database)
    client.run.side_effect = RuntimeError("API nicht erreichbar")
    summary = extract_transcripts(tmp_path, database)
    assert "C01" in summary.errors
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT arbeitsplaetze FROM transcript_signals").fetchone() == (3,)
    client.run.side_effect = None
    assert extract_transcripts(tmp_path, database).extracted == 1


def test_failures_do_not_stop_other_files(tmp_path, monkeypatch):
    write_transcript(tmp_path, "C01")
    write_transcript(tmp_path, "C02")
    write_transcript(tmp_path, "C03")
    (tmp_path / "C01.txt").write_text("ungültig")
    client = mock_client()
    monkeypatch.setattr("ofinto.services.extraction.PromptClient", Mock(return_value=client))
    client.run.side_effect = [RuntimeError("Fehler"), signals()]
    summary = extract_transcripts(tmp_path, tmp_path / "case.duckdb")
    assert summary.extracted == 1
    assert set(summary.errors) == {"C01", "C02"}


def test_cli_extraction_missing_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_transcript(tmp_path)
    result = CliRunner().invoke(app, [
        "extract-transcripts", "--transcript-dir", str(tmp_path), "--database", str(tmp_path / "case.duckdb"),
    ])
    assert result.exit_code == 1
    assert "OPENAI_API_KEY fehlt" in result.output


def test_cli_logs_file_progress(monkeypatch, tmp_path, caplog):
    write_transcript(tmp_path, body="SENSITIVE_TRANSCRIPT")
    client = mock_client()
    monkeypatch.setattr("ofinto.services.extraction.PromptClient", Mock(return_value=client))

    args = [
        "extract-transcripts", "--transcript-dir", str(tmp_path),
        "--database", str(tmp_path / "case.duckdb"),
    ]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert "[1/1] C01: starte Extraktion" in caplog.text
    assert "[1/1] C01: Ergebnis gespeichert" in caplog.text
    assert "Extraktion beendet" in caplog.text
    assert "SENSITIVE_TRANSCRIPT" not in result.output + caplog.text
    assert client.run.call_count == 1


def test_empty_transcript_directory(tmp_path):
    with pytest.raises(ValueError, match="Keine .txt"):
        extract_transcripts(tmp_path, tmp_path / "case.duckdb")
