# ofinto BI: Firmenaggregation

Python ab 3.12 und [uv](https://docs.astral.sh/uv/) werden benötigt.

```sh
uv sync
uv run ofinto import
uv run ofinto aggregate
uv run pytest -q
```

Die Datenbank ist standardmäßig `data/case.duckdb`. Beide Befehle akzeptieren
`--database`; der Import zusätzlich `--data-dir`. Nach einem neuen Import
`aggregate` erneut ausführen. Der Stichtag ist standardmäßig der dokumentierte
Datenstand 14. Oktober 2026, änderbar mit `--as-of YYYY-MM-DD`.

## Was passiert?

`import_csv.py` liest die vier CSV-Dateien mit festgelegten Datentypen ein.
`merge_data()` in `src/ofinto/merge.py` erledigt die gesamte Aggregation:

1. Firmenstamm und Anreicherung über `account_id` verbinden. Alle Firmen bleiben
   enthalten, auch ohne Anreicherung oder Bestellungen. Die bestehende Zuordnung
   wird übernommen; ein Match-Score unter 0.85 schränkt die Mitarbeiterbasis ein.
   Name und Ort werden nicht zusätzlich geprüft.
2. Bestellungen und Tisch-/Bürostuhlmengen je Firma aggregieren. Nur abgeschlossene
   Bestellungen und Teilretouren bis zum Stichtag zählen. Bestellungen werden
   getrennt von Positionen gezählt, um Doppelzählungen zu vermeiden.
3. Mitarbeiterbasis mit wenigen Regeln einordnen und verständliche Hinweise ergänzen.

Das Ergebnis steht in einer einzigen Tabelle `company_profiles` und wird auch
als Liste von Python-Dictionaries zurückgegeben. Die ursprünglichen deutschen
Spaltennamen und Quellenwerte bleiben erhalten. Transkriptsignale können später
über `account_id` ergänzt werden. Alles läuft lokal, ohne API oder Modell.

## Wie ist das Ergebnis zu lesen?

| Feld | Bedeutung |
|---|---|
| `anzahl_bestellungen`, `letzte_bestellung` | Wirksame Bestellungen bis zum Stichtag |
| `tische_min`, `tische_max` | Mengen von Tischen einschließlich Gestellen |
| `buerostuehle_min`, `buerostuehle_max` | Mengen von Motion/Era; Go wird als Besprechungsstuhl ausgelassen |
| `teilretouren` | Anzahl Bestellungen mit unbekannten zurückgegebenen Positionen |
| `mitarbeiterbasis` | `verwendbar`, `eingeschränkt` oder `nicht verwendbar` |
| `hinweise` | Kurze Begründungen und Hinweise zu Teilretouren |

Für Teilretouren zählt die Menge nur zur Obergrenze, weil die behaltenen Produkte
unbekannt sind. Stornos und Vollretouren zählen nicht. Möbelmengen sind noch keine
Anzahl ausgestatteter Arbeitsplätze.

Die Mitarbeiterbasis ist **nicht verwendbar**, wenn eine positive Mitarbeiterzahl
fehlt oder ihr Bezug nicht eindeutig `Standort` ist. Bei fehlendem Datum, einem
Datum nach dem Stichtag, Daten über zwei Jahre alt oder einem Match-Score unter
0.85 ist sie **eingeschränkt**. Genau 0.85 führt zu keiner Einschränkung.
Die Score-Schwelle ist eine vorläufige Annahme für den Case und nicht anhand
manuell bestätigter Zuordnungen kalibriert. Ein fehlender Score wird bisher nicht
gesondert bewertet.
Sonst ist sie **verwendbar**. Diese einfachen Regeln sind Annahmen für den Case,
keine Garantie für korrekte Daten. Teilretouren ändern die Mitarbeiterbewertung nicht.

Die Umsetzung setzt eindeutige Konto-/Bestell-IDs und gültige Mengen aus dem
Import voraus. Detaillierte Bestellprüfungen, Umsatzanalysen, separate Befundtabellen
und Potenzialschätzungen sind nicht Teil dieses Schritts.

Tests prüfen den bestehenden Import, die korrekte Aggregation mit Retouren und
die Einordnung der Mitarbeiterbasis einschließlich der Match-Score-Grenze.
