import json
from unittest.mock import patch

import duckdb

from ofinto.programs.assistant import AnswerProgram, SQLProgram
from ofinto.services.assistant import answer_question, execute_sql


def make_database(tmp_path):
    database = tmp_path / "case.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE companies (name VARCHAR, category VARCHAR)")
        con.execute("INSERT INTO companies VALUES ('Acme', 'Software')")
    return database


def test_generated_select_runs_and_returns_rows_read_only(tmp_path):
    database = make_database(tmp_path)
    assert execute_sql(database, "SELECT category, count(*) AS n FROM companies GROUP BY category") == [
        {"category": "Software", "n": 1},
    ]
    try:
        execute_sql(database, "CREATE TABLE other AS SELECT 1")
    except duckdb.Error:
        pass
    with duckdb.connect(str(database), read_only=True) as con:
        assert con.execute("SHOW TABLES").fetchall() == [("companies",)]


def test_question_uses_schema_then_sends_query_result_to_answer_prompt(tmp_path, monkeypatch):
    database = make_database(tmp_path)
    programs = []

    class FakeClient:
        def __init__(self, program):
            self.program = program
            programs.append(program)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def run(self, prompt):
            if self.program is SQLProgram:
                assert "companies(name VARCHAR, category VARCHAR)" in prompt
                return "SELECT category, count(*) AS n FROM companies GROUP BY category"
            assert self.program is AnswerProgram
            payload = json.loads(prompt)
            assert payload["ausführung"]["zeilen"] == [{"category": "Software", "n": 1}]
            return "Es gibt eine Software-Firma."

    monkeypatch.setattr("ofinto.services.assistant.PromptClient", FakeClient)
    response = answer_question(database, "Wie viele Software-Firmen gibt es?")
    assert response.answer == "Es gibt eine Software-Firma."
    assert len(programs) == 2


def test_sql_error_is_passed_to_second_prompt(tmp_path, monkeypatch):
    database = make_database(tmp_path)

    class FakeClient:
        def __init__(self, program):
            self.program = program

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def run(self, prompt):
            if self.program is SQLProgram:
                return "SELECT missing_column FROM companies"
            assert "sql_fehler" in prompt
            return "Die Abfrage ist fehlgeschlagen."

    monkeypatch.setattr("ofinto.services.assistant.PromptClient", FakeClient)
    response = answer_question(database, "Frage?")
    assert response.error
    assert response.answer == "Die Abfrage ist fehlgeschlagen."
