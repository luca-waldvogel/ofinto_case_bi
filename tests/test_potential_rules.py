from datetime import date

from ofinto.config import PotentialConfig
from ofinto.services.potential import calculate_potential

AS_OF = date(2026, 10, 14)


def profile(**changes):
    values = {
        "account_id": "A-1",
        "mitarbeiterbasis": "verwendbar",
        "mitarbeitende": 100,
        "erste_bestellung": date(2020, 10, 14),
        "tische_min": 0,
        "tische_max": 0,
        "buerostuehle_min": 0,
        "buerostuehle_max": 0,
    }
    return values | changes


def test_potential_uses_full_customer_history_beyond_five_years():
    result = calculate_potential(profile(), AS_OF, PotentialConfig())
    assert (result["potenzial_min"], result["potenzial_max"]) == (42, 61)
    assert (result["jahresbedarf_min"], result["jahresbedarf_max"]) == (7, 10)
    assert result["regelversion"] == "2"


def test_uncertain_deliveries_widen_potential_interval():
    result = calculate_potential(profile(
        erste_bestellung=date(2025, 10, 14), tische_max=20,
    ), AS_OF, PotentialConfig())
    assert (result["potenzial_min"], result["potenzial_max"]) == (0, 10)
