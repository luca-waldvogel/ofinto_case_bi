# ofinto BI: Firmenaggregation

Python ab 3.12 und [uv](https://docs.astral.sh/uv/) werden benötigt.

```sh
uv sync
uv run ofinto import
uv run ofinto ci
uv run pytest -q
uv run pyright
```

Die Datenbank ist standardmäßig `data/case.duckdb`. Die Befehle akzeptieren
`--database`; der Import zusätzlich `--data-dir`. Nach einem neuen Import
`run` (oder `ci`) erneut ausführen. Beide Befehle führen `aggregate`, `potential` und `export`
nacheinander aus; jeder Schritt kann auch einzeln aufgerufen werden.
Der Stichtag ist standardmäßig der 14. Oktober 2026 und kann mit
`--as-of YYYY-MM-DD` geändert werden.

## Was passiert?

`services/import_csv.py` liest die vier CSV-Dateien mit festgelegten Datentypen ein.
`merge_data()` in `ofinto/services/aggregation.py` erstellt die Firmenprofile:

1. Firmenstamm und Anreicherung über `account_id` verbinden. Alle Firmen bleiben
   enthalten, auch ohne Anreicherung oder Bestellungen.
2. Bestellungen und Tisch-/Bürostuhlmengen je Firma bis zum Stichtag aggregieren.
   Bestellungen werden getrennt von Positionen gezählt.

Die SQL-Aggregation bewertet dabei auch die Mitarbeiterbasis und ergänzt Hinweise.
`ofinto potential` berechnet aus diesen bewerteten Profilen das Potenzial.
`ofinto export` schreibt die gespeicherten Ergebnisse als CSV.

DuckDB übernimmt das Filtern und Aggregieren der großen Bestelltabellen,
das Verbinden der Quellen und die Qualitätsbewertung in `aggregation.py`.
Die Potenzialregeln stehen als reine Python-Funktion
`calculate_potential(company, as_of, config)` in `ofinto/services/potential.py`.
Die Regelparameter stehen im unveränderlichen `PotentialConfig`-Objekt aus
`ofinto/config.py`. `estimate_potential` erhält ein `PotentialConfig`-Objekt;
`calculate_potential` verwendet ohne Angabe die Standardwerte.
Die Potenzialfunktion lässt sich mit einem einzelnen Firmen-Dictionary ohne
Datenbank prüfen. Potenzialannahmen stehen in `PotentialConfig`; die
Qualitätsschwellen stehen direkt in der SQL-Aggregation.

`potential.py` liest die bewerteten Firmenprofile mit `fetchmany(1000)` und
schreibt die berechneten Ergebnisse blockweise mit `executemany()` in eine
temporäre DuckDB-Tabelle. Erst nach erfolgreicher Berechnung ersetzt diese die
Ergebnistabelle. Der Export liegt separat in `services/export.py`.

Die Aggregation speichert `company_profiles` mit Qualitätsbewertung;
`potential` speichert `company_potential`. Die ursprünglichen deutschen
Spaltennamen und Quellenwerte bleiben erhalten. Die Aggregation läuft lokal,
ohne API oder Modell. Die separate Transkriptextraktion ist unten beschrieben.

## Wie ist das Ergebnis zu lesen?

| Feld | Bedeutung |
|---|---|
| `anzahl_bestellungen`, `letzte_bestellung` | Wirksame Bestellungen bis zum Stichtag |
| `tische_min`, `tische_max` | Mengen von Tischen einschließlich Gestellen |
| `buerostuehle_min`, `buerostuehle_max` | Mengen der als Arbeitsplatzstühle eingeordneten Produkte |
| `teilretouren` | Anzahl Bestellungen mit unbekannten zurückgegebenen Positionen |
| `mitarbeiterbasis` | `verwendbar`, `eingeschränkt` oder `nicht verwendbar` |
| `hinweise` | Kurze Begründungen und Hinweise zu Teilretouren |

Für Teilretouren zählt die Menge nur zur Obergrenze, weil die behaltenen Produkte
unbekannt sind. Stornos und Vollretouren zählen nicht. Möbelmengen sind noch keine
Anzahl ausgestatteter Arbeitsplätze.

**Annahme:** Motion und Era werden als Arbeitsplatzstühle gezählt, Go als
Besprechungsstuhl ausgeschlossen. Die Liste `WORKPLACE_CHAIRS` in
`ofinto/services/aggregation.py` enthält diese Zuordnung und wird als Parameter
an SQL übergeben. Bei neuen Produkten oder Namensänderungen muss sie geprüft werden.

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

## Potenzial schätzen (Teil 1a)

```sh
uv run ofinto ci --database data/case.duckdb \
  --as-of 2026-10-14 --output-dir data/potential
```

`run` und `ci` führen Aggregation mit Qualitätsprüfung, Potenzialschätzung
und CSV-Export in dieser Reihenfolge aus. `potential` allein liest die bereits bewerteten
Firmenprofile und speichert `company_potential`; `export` erzeugt danach die
drei CSV-Dateien aus dieser Tabelle. Der Stichtag muss mit dem der gespeicherten
Profile übereinstimmen. Keine Transkripte,
Modellaufrufe oder zusätzlichen Abhängigkeiten werden benötigt. Ohne Optionen
gelten die im Beispiel gezeigten Werte.

### Rechenregeln und Bedeutung

Für Mitarbeiterzahl `M` und Kundenlaufzeit `J` gelten folgende Annahmen:

| Größe | Untergrenze | Obergrenze |
|---|---|---|
| Büroarbeitsplätze `W` | `0,7 × M` | `M` |
| Von ofinto gelieferte Arbeitsplatzäquivalente `O` | `0,5 × (tische_min + buerostuehle_min)` | `0,5 × (tische_max + buerostuehle_max)` |
| Zusätzliches Potenzial | `max(0; W_min × J / 10 − O_max)` | `max(0; W_max × J / 10 − O_min)` |
| Gesamter jährlicher Ersatzbedarf | `W_min / 10` | `W_max / 10` |

`J = min(5; Tage zwischen erste_bestellung und Stichtag / 365)`.
Angebrochene Jahre zählen anteilig. Maßgeblich ist das Feld `erste_bestellung`
im Firmenstamm, nicht das früheste Datum aus den Bestellzeilen. Im Case weichen
diese Angaben bei A-1053 voneinander ab. Bei fehlendem Erstbestelldatum oder einem
Datum nach dem Stichtag bricht `potential` mit einer Kunden-ID ab; vorherige
Potenzialergebnisse und Exporte bleiben erhalten. Die Firmenaggregation wurde
zu diesem Zeitpunkt bereits aktualisiert.

Die 0,7–1,0 Büroarbeitsplätze je Mitarbeiter gelten einheitlich für alle Branchen.
Ein ofinto-Tisch oder -Arbeitsstuhl deckt einen halben Arbeitsplatz ab: Ein nur
mit einem dieser Produkte ausgestatteter Platz behält 0,5 Arbeitsplatzäquivalente
Potenzial. Die Zuordnung von Tisch und Stuhl zu einzelnen Plätzen ist dafür
nicht erforderlich. Produktzuordnung und Teilretouren kommen aus der Aggregation.

Beispiel mit fest angenommenen 100 Arbeitsplätzen: Nach einem Jahr wären zehn
Plätze zu ersetzen. Sechs von ofinto gelieferte Arbeitsplatzäquivalente lassen
vier Plätze rechnerisches Potenzial. Nach fünf Jahren wären es bei 30 gelieferten
Äquivalenten noch 20. Die echte Berechnung verwendet die Arbeitsplatzbandbreite.

**Grenzen:** Der Ersatzzyklus beträgt zehn Jahre. Der nicht von ofinto gedeckte
Ersatzbedarf gilt als durch andere Anbieter ausgestattet. Deren Käufe werden
nicht beobachtet. Die Absatzlücke über die bisherige Kundenbeziehung ist ein
strukturelles Vergleichsszenario, keine Aussage zu unmittelbar bevorstehenden
Käufen oder Abschlusswahrscheinlichkeiten. Wachstum, Desk-Sharing und
branchenspezifische Büroanteile werden nicht gesondert modelliert. Die seit 2022
gelieferten Möbel gelten als weiterhin genutzt und innerhalb derselben
Produktgruppe verschiedenen Plätzen zugeordnet; wiederholte Ersatzkäufe und
ausgemusterte Möbel sind nicht erkennbar. Die Aggregation summiert die gesamte
vorhandene Bestellhistorie bis zum Stichtag. Bei einer künftigen Datenhistorie
von mehr als fünf Jahren muss das Mengenfenster auf die maximal fünfjährige
Vergleichsdauer abgestimmt werden.

### Bewertbarkeit, Ranking und Ausgaben

Nur `mitarbeiterbasis = verwendbar` wird berechnet. `eingeschränkt` und
`nicht verwendbar` bleiben ohne Potenzialzahl (`NULL`). Die vorhandenen
`hinweise` werden unverändert übernommen; es gibt keine weitere Qualitätslogik.
Damit gelten auch bestehende Grenzen der Aggregation, etwa die fehlende
Sonderbehandlung eines leeren Match-Scores. Ein berechnetes Potenzial von null
ist dagegen eine gültige Bewertung.

Die Ergebnistabelle und die Exporte enthalten nur Kunden-ID, Firmenname, Mitarbeiterzahl,
Erstbestellung, Stichtag, Mitarbeiterbasis, Hinweise, Bewertbarkeit,
`potenzial_min/max`, `jahresbedarf_min/max` und `regelversion = 1`.
Zwischenwerte und die übrigen Firmenprofildaten werden nicht übernommen.
Die Ergebnisbandbreiten sind ganze Zahlen: Untergrenzen werden ab-,
Obergrenzen aufgerundet. Es wird
kein jährliches Restpotenzial berechnet. Die Bandbreiten sind Szenarien und
keine statistischen Konfidenzintervalle.

Die Top 15 enthalten ausschließlich bewertbare Kunden mit positiver
Potenzialobergrenze. Sortiert wird nach gespeicherter Untergrenze absteigend,
danach Obergrenze absteigend, zuletzt Kunden-ID aufsteigend. Bei weniger als 15
Kandidaten fällt die Liste entsprechend kürzer aus.

| Datei im Ausgabeordner | Inhalt |
|---|---|
| `kundenpotenziale.csv` | Alle Kunden mit den wesentlichen Firmenangaben, Potenzial, Jahresbedarf, Status und Hinweisen |
| `top15.csv` | Bis zu 15 Kandidaten mit Rang und denselben Angaben |
| `nicht_bewertbar.csv` | Kunden-ID, Firmenname, Mitarbeiterbasis, unveränderte Hinweise, Stichtag und Regelversion |

Die CSVs sind UTF-8 mit Kopfzeile; fehlende Werte sind leer. Ungerundete
Berechnungsfelder werden nicht gespeichert.
Bestehende CSVs werden erst ersetzt, wenn alle
drei neuen Dateien erfolgreich geschrieben wurden. Die Datenbanktabelle und
die drei Dateiersetzungen bilden keine gemeinsame Transaktion; bei einem
Exportfehler meldet die CLI einen Fehler, und der Befehl kann erneut laufen.

Für die Case-Daten zum Standardstichtag entstehen **150 Zeilen: 73 bewertet,
77 nicht bewertbar**. `potential` zeigt die Zusammenfassung; `export` zeigt
Top 15 und Ausschlussliste.

### Prüfung und Skalierung

```sh
uv run pytest -q
uv run python -m benchmarks.potential --customers 10000 \
  --orders-per-customer 20 --items-per-order 5
```

Die Tests decken anteilige Kundenlaufzeiten, Fünfjahresgrenze, halbe
Arbeitsplatzäquivalente, Teilretouren, unveränderte Qualitätsgründe,
Ganzzahlintervalle, Rangfolge, Top-15-Grenze und wiederholbare Exporte ab.
Die Potenzialfunktion wird zusätzlich direkt ohne Datenbank getestet,
einschließlich exakter Ganzzahlrundung.

Der Lasttest erzeugt temporär **10'000 Kunden, 200'000 Bestellungen und
eine Million Positionen**, darunter 2'000 nicht bewertbare Kunden. Die Historie
enthält abgeschlossene Bestellungen, Teilretouren, Vollretouren, Stornos und
Bestellungen nach dem Stichtag. Tisch- und Arbeitsstuhlpositionen werden neben
Besprechungsstühlen, Kabinen und Zubehör verarbeitet.

Ein lokaler Lauf mit DuckDB 1.5.6 und Python 3.14.7 ergab:

| Messgröße | Ergebnis |
|---|---|
| Datenerzeugung, separat gemessen | 0,279 Sekunden |
| Aggregation mit Qualität, Potenzial und drei CSV-Exporte | 6,360 Sekunden |
| Maximaler Speicher des gesamten Prozesses | 237,7 MiB |
| Datenbankdatei | 9,8 MiB |
| CSV-Dateien zusammen | Rund 1,6 MB |

Der Benchmark prüft Tabellen- und Exportzeilenzahlen, Intervallgrenzen und
für eine Firma unabhängig berechnete Mengen sowie Potenziale. Die Größen
sind über die drei CLI-Optionen veränderbar. Der Speicherwert umfasst auch
Datenerzeugung und Validierung. Die synthetischen Daten enthalten viele
Wiederholungen und sind stark komprimierbar; die Messwerte sind keine
Laufzeitgarantie für reale Bestellhistorien. Hardware, Datenverteilung,
Textlängen und verfügbare Ressourcen beeinflussen das Ergebnis. `executemany()` ist einfach, bei großen
Datenmengen aber langsamer als ein Bulk-Import.

## Projektstruktur

```text
ofinto/
├── __main__.py             # python -m ofinto
├── cli.py                  # CLI-Befehle und Konsolenausgaben
├── config.py               # PromptClientConfig und Laden der Umgebungsvariablen
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
    ├── aggregation.py      # Firmenprofile und Bestellmengen
    ├── potential.py        # Potenzial berechnen und speichern
    ├── export.py           # Ranking und CSV-Exporte
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
OPENAI_TIMEOUT=60
OPENAI_MAX_RETRIES=2
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
Standard in der Konfiguration.
`OPENAI_TIMEOUT` setzt den Netzwerk-Timeout in Sekunden, `OPENAI_MAX_RETRIES`
die maximale Anzahl automatischer SDK-Retries.
`OPENAI_BASE_URL` kann auf einen kompatiblen lokalen Endpunkt zeigen; dieser muss
die Responses API einschließlich strukturierter Ausgaben unterstützen. Für lokale
Endpunkte verlangt der Client ebenfalls `OPENAI_API_KEY` (gegebenenfalls ein Dummywert).
Es gibt keinen automatischen Rückfall auf die öffentliche API.

```sh
uv run ofinto extract-transcripts --transcript-dir data/transkripte --database data/case.duckdb
```

`extract-transcripts` liest die Fireflies-Kopfzeilen lokal und sendet je Gespräch
das vollständige Transkript an das Modell. Gesprächszeitstempel werden nach UTC
umgerechnet; fehlt die Zeitzone, wird UTC angenommen. Die fünf Pflichtfelder werden separat
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
einheitliche Stichworte und das Zusammenfassen sinngleicher Nennungen.
Die Listen werden ohne zusätzliche Nachbereitung gespeichert.

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

In `ofinto/config.py` definiert `PromptClientConfig` Modell, Timeout, `max_retries`,
API-Schlüssel, optionalen API-Endpunkt (`base_url`) und die Antwortspeicherung
(`store`, standardmäßig `False`). Ohne übergebene Konfiguration lädt der Client
sie über `PromptClientConfig.from_env()` aus Umgebung und `.env`.
Eine explizite Konfiguration kann so angepasst und übergeben werden:

```python
from dataclasses import replace
from ofinto.config import PromptClientConfig

config = replace(PromptClientConfig.from_env(), timeout=120.0, max_retries=1)
with PromptClient(ExtractionProgram, config) as extraction:
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

Der Client erstellt im Konstruktor einen SDK-Transport mit den Werten aus seiner
Konfiguration (standardmäßig 60 Sekunden Timeout und zwei SDK-Retries) und verwendet ihn für weitere
Aufrufe wieder. Der `with`-Block schließt ihn am Ende, alternativ ist `close()` möglich.
Der Extraktionslauf verwendet einen Client für alle Gespräche. Fehler in Hooks,
ungültige Antworten und Ablehnungen lösen keine zusätzlichen Modellaufrufe aus.
Requests verwenden standardmäßig `store=False`; das ersetzt keine vertraglichen Regeln zur
API-Datenverarbeitung.

Die fiktiven Case-Daten dürfen laut Aufgabenstellung per API verarbeitet werden.
Bei echten Kundendaten muss auch die Modellinferenz lokal erfolgen.
Einlesen und Speichern laufen bereits lokal. Ein Wechsel des Endpunkts erfordert
erneute Prüfung der API-Kompatibilität und Extraktionsqualität.

Die Tests prüfen die wichtigsten Abläufe: Import mit Rollback, Aggregation mit
Retouren, Mitarbeiterbewertung, Konfiguration, Prompt-Aufrufe und Speicherung.
Modellantworten werden mit einfachen Mocks simuliert; die Tests benötigen keinen
API-Schlüssel. Die fachliche Prüfung erfolgt manuell anhand der gespeicherten
Ergebnisse und der Originaltranskripte.
