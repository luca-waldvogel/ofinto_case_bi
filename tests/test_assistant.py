import json

import duckdb

from ofinto.programs.assistant import AnswerProgram, SQLProgram
from ofinto.services.assistant import answer_question


def test_assistant_passes_sql_results_to_answer_prompt(tmp_path, monkeypatch):
    database = tmp_path / "case.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE companies (name VARCHAR, category VARCHAR)")
        connection.execute("INSERT INTO companies VALUES ('Acme', 'Software')")

    class FakeClient:
        def __init__(self, program, config):
            self.program = program

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def run(self, prompt):
            if self.program is SQLProgram:
                assert "companies(name VARCHAR, category VARCHAR)" in prompt
                return "SELECT category, count(*) AS n FROM companies GROUP BY category"
            assert self.program is AnswerProgram
            assert json.loads(prompt)["ausführung"]["zeilen"] == [
                {"category": "Software", "n": 1},
            ]
            return "Es gibt eine Software-Firma."

    monkeypatch.setattr("ofinto.services.assistant.PromptClient", FakeClient)
    response = answer_question(database, "Wie viele Software-Firmen gibt es?")
    assert response.answer == "Es gibt eine Software-Firma."
