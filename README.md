# ofinto BI – Firmenkunden und Verkaufsgespräche

Dieses Projekt wertet die fiktiven Case-Daten aus. Es erstellt Firmenprofile und Potenzialschätzungen, extrahiert Signale aus Verkaufsgesprächen und beantwortet Fragen zu den gespeicherten Daten. Die Case-Daten wurden nicht auf Git commited.

## Schnellstart

Voraussetzungen: Python ab 3.12 und `uv`. Die folgenden Befehle werden im Projektordner ausgeführt:

```sh
uv sync
uv run ofinto import
uv run ofinto run --output-dir data/results/potential
```

`import` lädt die vier Kunden- und Bestell-CSV-Dateien nach `data/case.duckdb`. `run` führt danach **Aggregation → Potenzialberechnung → CSV-Export** aus. Der Datenstichtag ist standardmäßig der **14.10.2026**; mit `--as-of YYYY-MM-DD` kann er geändert werden. Nach geänderten Quelldaten `import` und `run` erneut ausführen.

Für die Gesprächsauswertung und den Frageassistenten wird zusätzlich ein Modell benötigt. Für die fiktiven Case-Daten kann ein API-Schlüssel als `OPENAI_API_KEY` in einer lokalen `.env`-Datei oder als Umgebungsvariable gesetzt werden:

```sh
uv run ofinto extract-transcripts
uv run ofinto ask --question "Wie viele Bestellungen gab es 2025 je Währung?"
```

Mit `--details` zeigt `ask` zusätzlich die erzeugte SQL-Abfrage und ihre Ergebniszeilen. Ein kompatibler lokaler Modellendpunkt kann über `OPENAI_BASE_URL` eingestellt werden; bei echten Kundendaten muss die Modellverarbeitung intern erfolgen.

## Vorgehen

1. **Aggregieren:** Kunden, Firmendaten und wirksame Bestellungen werden über die Kunden-ID verbunden. Stornos und vollständige Retouren zählen bei den gelieferten Möbelmengen nicht; Teilretouren führen zu Mengenbandbreiten. Unzuverlässige Mitarbeiterzahlen werden mit einem Hinweis gekennzeichnet.
2. **Potenzial schätzen:** Aus der Mitarbeiterzahl werden 70–100 % Büroarbeitsplätze angenommen. Bei einem zehnjährigen Ersatzzyklus wird der erwartete Bedarf während der bisherigen Kundenbeziehung, höchstens fünf Jahre, mit den von ofinto gelieferten Tisch- und Stuhlmengen verglichen. Potenzial und Jahresbedarf werden als Bandbreiten ausgewiesen.
3. **Gespräche auswerten:** Ein Modell ermittelt Gesprächsart, Kaufzeitpunkt, Arbeitsplätze, Wettbewerber und Einwände aus den Transkripten. Die Ergebnisse werden in DuckDB gespeichert und als CSV exportiert.
4. **Fragen stellen:** Der Assistent erzeugt eine SQL-Abfrage, liest die Datenbank nur lesend und formuliert aus den Ergebniszeilen eine Antwort. Berechnete Zahlen sollten anhand der SQL-Abfrage und der Quelldaten geprüft werden.

## Ergebnisse

| Datei | Inhalt |
|---|---|
| `data/results/aggregate/company_profiles.csv` | Alle aggregierten Firmenprofile mit Qualitätsinformationen |
| `data/results/potential/kundenpotenziale.csv` | Potenzial und Jahresbedarf je Kunde |
| `data/results/potential/top15.csv` | Die 15 größten bewertbaren Potenziale |
| `data/results/potential/nicht_bewertbar.csv` | Nicht seriös bewertbare Firmen mit Begründung |
| `data/results/extraction/extrahierte_labels.csv` | Modelllabels für die Gespräche |
| `data/results/assistant_evaluation.json` | Antworten auf die Testfragen, falls `evaluate-assistant` ausgeführt wird |

Die Potenzialausgabe verwendet den mit `--output-dir` gewählten Ordner. `aggregate`, `potential` und `export` können auch einzeln aufgerufen werden. Die vollständige Befehlsübersicht zeigt `uv run ofinto --help`.

Für alle Testfragen auf einmal:

```sh
uv run ofinto evaluate-assistant
```
