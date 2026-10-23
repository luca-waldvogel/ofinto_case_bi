"""Potenzialregeln direkt in Python prüfen, ohne Datenbank-Fixtures."""

from datetime import date
from decimal import Decimal

import pytest

from ofinto.config import PotentialConfig
from ofinto.services.potential import calculate_potential


def profile(**changes):
    return {
        "account_id": "A-1", "mitarbeitende": 100,
        "mitarbeitende_bezug": "Standort", "match_score": 0.95,
        "stand": date(2026, 1, 1), "teilretouren": 0,
        "mitarbeiterbasis": "verwendbar", "erste_bestellung": date(2021, 1, 1),
        "tische_min": 0, "tische_max": 0,
        "buerostuehle_min": 0, "buerostuehle_max": 0, **changes,
    }


def test_decimal_workplace_bounds_do_not_round_down_exact_integers():
    result = calculate_potential(profile(mitarbeitende=90), date(2026, 10, 14), PotentialConfig())
    assert (result["potenzial_min"], result["potenzial_max"]) == (31, 45)


def test_one_year_customer_does_not_get_five_year_potential():
    result = calculate_potential(profile(
        erste_bestellung=date(2025, 10, 14), tische_min=6, tische_max=6,
        buerostuehle_min=6, buerostuehle_max=6,
    ), date(2026, 10, 14), PotentialConfig())
    assert (result["potenzial_min"], result["potenzial_max"]) == (1, 4)


@pytest.mark.parametrize("days_per_year,expected", [(365.25, (9, 19)), (10000, (1, 4))])
def test_potential_uses_custom_config(days_per_year, expected):
    config = PotentialConfig(
        rule_version="custom",
        workplaces_per_employee_min=Decimal("0.2"),
        workplaces_per_employee_max=Decimal("0.4"),
        workplace_share_per_item=Decimal("0.25"),
        replacement_years=2,
        max_observation_years=1,
        days_per_year=days_per_year,
    )
    result = calculate_potential(profile(tische_min=4, tische_max=4), date(2026, 10, 14), config)
    assert (result["potenzial_min"], result["potenzial_max"]) == expected
    assert (result["jahresbedarf_min"], result["jahresbedarf_max"]) == (10, 20)
    assert result["regelversion"] == "custom"


def test_evaluable_profile_requires_employee_count():
    with pytest.raises(ValueError, match="Mitarbeiterzahl fehlt"):
        calculate_potential(profile(mitarbeitende=None), date(2026, 10, 14), PotentialConfig())
