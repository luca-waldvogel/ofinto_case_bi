import duckdb
from typer.testing import CliRunner

from ofinto_case_bi.main import app
from ofinto_case_bi.schemas import SCHEMAS


def test_help_lists_import_command():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "import" in result.output


def test_cli_imports_to_requested_database(csv_dir):
    database = csv_dir / "custom.duckdb"
    result = CliRunner().invoke(
        app, ["import", "--data-dir", str(csv_dir), "--database", str(database)]
    )
    assert result.exit_code == 0, result.output
    with duckdb.connect(str(database), read_only=True) as connection:
        for table in SCHEMAS:
            row = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()
            assert row is not None, f"Table {table} should return a row"
            assert row[0] == 1, f"Table {table} should have 1 row"


def test_cli_reports_missing_source(csv_dir):
    (csv_dir / "firmenkunden.csv").unlink()
    result = CliRunner().invoke(
        app, ["import", "--data-dir", str(csv_dir), "--database", str(csv_dir / "case.duckdb")]
    )
    assert result.exit_code == 1
    assert "Import fehlgeschlagen" in result.output
