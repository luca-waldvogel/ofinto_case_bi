from unittest.mock import MagicMock
from unittest.mock import Mock

import duckdb
import pytest

from ofinto.clients import PromptClient
from ofinto.model import TranscriptSignals
from ofinto.services.extraction import extract_transcripts


def write_transcript(directory, call_id):
    path = directory / f"{call_id}.txt"
    path.write_text("""Title: Beispielgespräch
Date: 2026-09-15T08:10:00Z

Sentences:
[00:01 - 00:10] Kunde: Wir brauchen drei Arbeitsplätze.
""")


@pytest.fixture
def prompt_client(monkeypatch):
    client = MagicMock(spec=PromptClient)
    client.__enter__.return_value = client
    client.run.return_value = TranscriptSignals(
        gespraechstyp="Verkaufsgespräch",
        kaufzeitpunkt="0-3 Monate",
        arbeitsplaetze=3,
        wettbewerber=[],
        einwaende=["Preis"],
    )
    monkeypatch.setattr("ofinto.services.extraction.PromptClient", Mock(return_value=client))
    return client


def test_each_run_extracts_and_updates_results(tmp_path, prompt_client):
    write_transcript(tmp_path, "C01")
    database = tmp_path / "case.duckdb"

    assert extract_transcripts(tmp_path, database).extracted == 1
    prompt_client.run.return_value = prompt_client.run.return_value.model_copy(update={"arbeitsplaetze": 7})
    assert extract_transcripts(tmp_path, database).extracted == 1

    assert prompt_client.run.call_count == 2
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT call_id, title, arbeitsplaetze FROM transcript_signals",
        ).fetchall() == [("C01", "Beispielgespräch", 7)]


def test_error_keeps_old_result_and_continues(tmp_path, prompt_client):
    write_transcript(tmp_path, "C01")
    database = tmp_path / "case.duckdb"
    extract_transcripts(tmp_path, database)

    write_transcript(tmp_path, "C02")
    prompt_client.run.side_effect = [RuntimeError("API nicht erreichbar"), prompt_client.run.return_value]
    summary = extract_transcripts(tmp_path, database)

    assert summary.extracted == 1
    assert summary.errors == {"C01": "API nicht erreichbar"}
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT call_id, arbeitsplaetze FROM transcript_signals ORDER BY call_id",
        ).fetchall() == [("C01", 3), ("C02", 3)]
