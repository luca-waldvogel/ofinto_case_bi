from dataclasses import dataclass
from datetime import date
from math import ceil, floor
from pathlib import Path
from typing import Any

import duckdb

from ..config import PotentialConfig
from ..model import COMPANY_PROFILES_TABLE, POTENTIAL_SCHEMA, POTENTIAL_TABLE
from .aggregation import DEFAULT_AS_OF

BATCH_SIZE = 1000
PROFILE_COLUMNS = (
    "account_id", "firmenname", "mitarbeitende", "erste_bestellung",
    "letzte_bestellung", "stichtag", "mitarbeiterbasis", "hinweise",
)


def calculate_potential(
    company: dict[str, Any], as_of: date, config: PotentialConfig,
) -> dict[str, Any]:
    """Potenzial eines aggregierten Firmenprofils ohne Datenbankzugriff berechnen."""
    first_order: date | None = company["erste_bestellung"]
    if first_order is None or first_order > as_of:
        raise ValueError(
            f"Erstbestelldatum fehlt oder liegt nach dem Stichtag: {company['account_id']}"
        )
    result: dict[str, Any] = dict.fromkeys(POTENTIAL_SCHEMA)
    result.update(bewertbar=company["mitarbeiterbasis"] == "verwendbar",
                  regelversion=config.rule_version)
    if not result["bewertbar"]:
        return result

    employees: int | None = company["mitarbeitende"]
    if employees is None:
        raise ValueError(f"Mitarbeiterzahl fehlt für bewertbares Profil: {company['account_id']}")
    years = (as_of - first_order).days / config.days_per_year
    supplied_min = config.workplace_share_per_item * (company["tische_min"] + company["buerostuehle_min"])
    supplied_max = config.workplace_share_per_item * (company["tische_max"] + company["buerostuehle_max"])
    workplaces_min = config.workplaces_per_employee_min * employees
    workplaces_max = config.workplaces_per_employee_max * employees
    potential_min = max(0.0, float(workplaces_min) * years / config.replacement_years - float(supplied_max))
    potential_max = max(0.0, float(workplaces_max) * years / config.replacement_years - float(supplied_min))

    return {
        **result,
        "potenzial_min": floor(potential_min),
        "potenzial_max": ceil(potential_max),
        "jahresbedarf_min": floor(workplaces_min / config.replacement_years),
        "jahresbedarf_max": ceil(workplaces_max / config.replacement_years),
    }


@dataclass(frozen=True)
class PotentialSummary:
    total: int
    evaluated: int
    excluded: int
    top_count: int


def estimate_potential(
    database: Path,
    config: PotentialConfig,
    as_of: date = DEFAULT_AS_OF,
) -> PotentialSummary:
    """Bewertete Firmenprofile laden, Potenziale berechnen und speichern."""
    if not database.is_file():
        raise ValueError(f"Datenbank fehlt: {database}. Zuerst aggregate ausführen.")

    with duckdb.connect(str(database)) as connection:
        mismatched = connection.execute(
            f"SELECT count(*) FROM {COMPANY_PROFILES_TABLE} WHERE stichtag <> ?", [as_of],
        ).fetchall()[0][0]
        if mismatched:
            raise ValueError("Stichtag der Firmenprofile weicht vom gewählten Stichtag ab")
        reader = connection.cursor()
        reader.execute(f"SELECT * FROM {COMPANY_PROFILES_TABLE}")
        columns = [column[0] for column in reader.description]
        source_types = {name: str(data_type) for name, data_type, *_ in reader.description}
        fields = {name: source_types[name] for name in PROFILE_COLUMNS} | POTENTIAL_SCHEMA
        definitions = ", ".join(f'"{name}" {data_type}' for name, data_type in fields.items())
        placeholders = ", ".join("?" for _ in fields)
        connection.execute(f"CREATE OR REPLACE TEMP TABLE potential_results ({definitions})")
        while batch := reader.fetchmany(BATCH_SIZE):
            results = []
            for row in batch:
                company = dict(zip(columns, row))
                result = {**company, **calculate_potential(company, as_of, config)}
                results.append(tuple(result[name] for name in fields))
            connection.executemany(
                f"INSERT INTO potential_results VALUES ({placeholders})", results,
            )
        reader.close()
        connection.execute(f"""
            CREATE OR REPLACE TABLE {POTENTIAL_TABLE} AS SELECT * FROM potential_results
        """)
        total, evaluated, candidates = connection.execute(f"""
            SELECT count(*), count(*) FILTER (WHERE bewertbar),
                count(*) FILTER (WHERE bewertbar AND potenzial_max > 0)
            FROM {POTENTIAL_TABLE}
        """).fetchall()[0]
    return PotentialSummary(total, evaluated, total - evaluated, min(15, candidates))
