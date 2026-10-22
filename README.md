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

`services/import_csv.py` liest die vier CSV-Dateien mit festgelegten Datentypen ein.
`merge_data()` in `ofinto/services/aggregation.py` erledigt die gesamte Aggregation:

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
Spaltennamen und Quellenwerte bleiben erhalten. Die Aggregation läuft lokal,
ohne API oder Modell. Die separate Transkriptextraktion ist unten beschrieben.

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

## Projektstruktur

```text
ofinto/
├── __main__.py             # python -m ofinto
├── cli.py                  # CLI-Befehle und Konsolenausgaben
├── clients/
│   └── prompt.py           # Generischer PromptClient und OpenAI-Anbindung
├── model/
│   ├── schemas.py          # CSV-/DuckDB-Quellschemas
│   └── transcript.py       # Extraktionsmodell und Feldbeschreibungen
├── programs/
│   ├── base.py             # PromptProgram und Standard-Hooks
│   └── extraction.py       # Extraktionsprompts und fachliche Hooks
└── services/
    ├── import_csv.py       # CSV-Import
    ├── aggregation.py      # Firmenprofile und Mitarbeiterbasis
    └── extraction.py       # Fireflies einlesen, extrahieren und speichern
tests/                      # Tests und CSV-Fixtures
data/                       # Lokale Eingaben und erzeugte Ergebnisse
```

Das Python-Paket liegt direkt im Projektordner. `uv run ofinto …` und
`uv run python -m ofinto …` verwenden dieselbe CLI. Services koordinieren die
Anwendungsabläufe; Programme definieren Prompts und Hooks, Clients führen die
Modellaufrufe aus. Die Datenschemas liegen unabhängig davon unter `model`.

## Transkripte auswerten

Der Client lädt bei seiner Initialisierung automatisch `.env` aus dem aktuellen
Arbeitsverzeichnis. Im Projektordner enthält die Datei diese Konfiguration:

```dotenv
OPENAI_MODEL=gpt-5-mini
OPENAI_API_KEY=
```

Den eigenen API-Schlüssel in `OPENAI_API_KEY` eintragen. `.env` ist durch
`.gitignore` vom Repository ausgeschlossen. Bereits gesetzte Umgebungsvariablen
haben Vorrang vor den Werten aus der Datei. Alternativ den Schlüssel in der Shell
eingeben, ohne ihn in die Shell-History zu schreiben:

```sh
read -s 'OPENAI_API_KEY?OpenAI API-Key: '
export OPENAI_API_KEY
uv run ofinto extract-transcripts
```

Das Eingabebeispiel gilt für zsh. Der API-Schlüssel wird nicht im Repository gespeichert.
Das Modell ist standardmäßig `gpt-5-mini`. `OPENAI_MODEL` setzt einen anderen
Standard, `--model` überschreibt ihn für den jeweiligen Extraktionslauf.
`OPENAI_BASE_URL` kann auf einen kompatiblen lokalen Endpunkt zeigen; dieser muss
die Responses API einschließlich strukturierter Ausgaben unterstützen. Für lokale
Endpunkte verlangt der Client ebenfalls `OPENAI_API_KEY` (gegebenenfalls ein Dummywert).
Es gibt keinen automatischen Rückfall auf die öffentliche API.

```sh
uv run ofinto extract-transcripts --transcript-dir data/transkripte --database data/case.duckdb
uv run ofinto extract-transcripts --model gpt-5-mini
```

`extract-transcripts` liest die Fireflies-Kopfzeilen lokal und sendet je Gespräch
das vollständige Transkript an das Modell. Die fünf Pflichtfelder werden separat
in `transcript_signals` gespeichert:

| Feld | Bedeutung |
|---|---|
| `gespraechstyp` | Verkaufsgespräch, Reklamation, Information oder Sonstiges |
| `kaufzeitpunkt` | 0-3, 3-6, 6-12, >12 Monate oder unklar, ab Gesprächsdatum |
| `arbeitsplaetze` | Neu auszustattende Arbeitsplätze; `NULL` bei unbestimmter Menge, `0` bei ausdrücklich keinem neuen Bedarf |
| `wettbewerber` | Liste der konkret konkurrierenden Anbieter |
| `einwaende` | Freie Liste kurzer deutscher Stichworte zu Einwänden und Kaufhürden |

Mitarbeiterzahlen, historische Käufe, Kabinen und einzelne Ersatzstühle werden
nicht als neue vollständige Arbeitsplätze gezählt. Bei einem Ersatzprojekt zählt
die Anzahl neu auszustattender Arbeitsplätze. Optionale spätere Etappen werden
nicht zur konkretisierten ersten Etappe addiert.

Einwände sind nicht auf feste Kategorien beschränkt. Der Prompt fordert kurze,
einheitliche Stichworte und fasst sinngleiche Nennungen zusammen. Die Nachbereitung
bereinigt Leerraum, entfernt leere Einträge und Duplikate unabhängig von der
Groß-/Kleinschreibung und sortiert die Liste.

Zusätzlich enthält die Tabelle nur Gesprächs-ID, Titel und Gesprächsdatum.
Firmenprofile werden nicht verändert. Mitarbeiterdaten, Zukunftspläne,
Quellenbelege und die Zuordnung zu Firmenkonten folgen in einem weiteren Schritt.

Jeder Aufruf wertet alle Transkripte erneut mit dem Modell aus. Erfolgreiche
Ergebnisse ersetzen den bisherigen Datensatz derselben `call_id`.
Einzelne Fehler stoppen die anderen Gespräche nicht, führen aber zum Exitcode 1.
Alte Ergebnisse bleiben bei einem fehlgeschlagenen Aktualisierungsversuch erhalten.
Fehler werden in den Logs und am Ende des Laufs ausgegeben.

Die Ergebnisse werden manuell anhand der Transkripte und gegebenenfalls der
mitgelieferten Labels geprüft. Zum Anzeigen in DuckDB:

```sh
uv run python - <<'PY'
import duckdb

with duckdb.connect("data/case.duckdb", read_only=True) as con:
    con.sql("""
        SELECT call_id, title, gespraechstyp, kaufzeitpunkt,
               arbeitsplaetze, wettbewerber, einwaende
        FROM transcript_signals ORDER BY call_id
    """).show(max_rows=20)
PY
```

Der Extraktionsbefehl schreibt Fortschrittslogs ohne Zeitmessung sofort auf stderr:
Datei und Fortschritt (`[1/20] C01`), Start und Ende des API-Aufrufs,
Speichern des Ergebnisses sowie Fehler.
Auch automatische SDK-Retries werden angezeigt. Der Netzwerk-Timeout beträgt
60 Sekunden pro Netzwerkoperation; mit bis zu zwei Retries kann eine Anfrage
mehrere Minuten dauern. Transkriptinhalte,
Prompts, API-Schlüssel und vollständige Modellantworten werden nicht protokolliert.

```sh
uv run ofinto extract-transcripts 2> extraction.log
```

Bei einem bereits laufenden Prozess greifen neue Logs erst nach einem Neustart.

## Weitere Prompt-Programme

Jedes Programm definiert in einer eigenen Python-Datei Systemprompt, Userprompt,
Rückgabetyp und optional Vor-/Nachbereitung:

```python
from ofinto.clients import PromptClient
from ofinto.programs import ExtractionProgram

with PromptClient(ExtractionProgram) as extraction:
    signals = extraction.run(transcript)
```

Die Basis `PromptProgram[InputT, OutputT]` stellt die Hooks `prepare(input)`,
`render_user_prompt(prepared_input)` und `postprocess(result)` bereit.
`run` führt sie automatisch in dieser Reihenfolge um den Modellaufruf aus und
übernimmt die vom SDK validierte Antwort und gibt das Ergebnis der Nachbereitung
direkt zurück. `postprocess()` ist für die Gültigkeit seiner Änderungen verantwortlich.
Standardmäßig reichen die
Hooks Werte unverändert durch und setzen `{input}` im Userprompt ein.
Programme benötigen keine Konstruktorparameter und halten keinen veränderlichen
Zustand zwischen Aufrufen. Eingabeklammern werden nicht erneut als Template ausgewertet.

Pydantic-Ausgabemodelle beschreiben jedes Feld mit `Field(description=...)`.
Der Client übergibt das Modell an `responses.parse(text_format=...)`; das SDK
übermittelt die Beschreibungen im JSON-Schema. Sie werden nicht zusätzlich in die
Prompts geschrieben. `return_type=str` verwendet denselben Client für reine
Textantworten über `responses.create(...)`.

Der Client erstellt im Konstruktor einen SDK-Transport
mit 60 Sekunden Timeout und maximal zwei SDK-Retries und verwendet ihn für weitere
Aufrufe wieder. Der `with`-Block schließt ihn am Ende, alternativ ist `close()` möglich.
Der Extraktionslauf verwendet einen Client für alle Gespräche. Fehler in Hooks,
ungültige Antworten und Ablehnungen lösen keine zusätzlichen Modellaufrufe aus.
Requests verwenden `store=False`; das ersetzt keine vertraglichen Regeln zur
API-Datenverarbeitung.

Die fiktiven Case-Daten dürfen laut Aufgabenstellung per API verarbeitet werden.
Bei echten Kundendaten muss auch die Modellinferenz lokal erfolgen.
Einlesen und Speichern laufen bereits lokal. Ein Wechsel des Endpunkts erfordert
erneute Prüfung der API-Kompatibilität und Extraktionsqualität.

Die Tests verwenden simulierte Antworten einschließlich eines HTTP-Mocktransports,
der die echte SDK-Schemaübermittlung prüft. Sie benötigen keinen API-Schlüssel und
belegen keine fachliche Modellgüte. Die fachliche Prüfung erfolgt manuell anhand
der gespeicherten Ergebnisse und der Originaltranskripte.
