import csv

import pytest

from ofinto_case_bi.schemas import SCHEMAS


@pytest.fixture
def csv_dir(tmp_path):
    rows = {
        "firmenkunden": ["A-1", "Beispiel AG", "Zürich", "0123", "CH", "Deutschschweiz",
                         "de", "", "Anna", "Webshop", "2026-01-02"],
        "firmendaten_anreicherung": ["A-1", "Beispiel AG", "Zürich", "CHE-123", "0.95",
                                    "100", "Standort", "1", "01.10", "2000", "2026-01-01"],
        "bestellungen": ["O-1", "A-1", "2026-01-02", "ofinto.ch", "CHF", "123.45",
                         "abgeschlossen", "0.0", "Webshop"],
        "bestellpositionen": ["O-1", "Elevate", "Tisch", "1", "123.45", "CHF"],
    }
    for table, row in rows.items():
        with (tmp_path / f"{table}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(SCHEMAS[table])
            writer.writerow(row)
    return tmp_path
