# kartensammlung-area-statistics-builds

Build-Pipelines und Datenartefakte für die generischen Gebietsstatistiken der Kartensammlung.

Die Geometrie-, Registry- und Statistik-Builds werden bewusst getrennt von der MapLibre-Runtime gepflegt.

## Architektur

Das Repo soll langfristig drei voneinander getrennte Aufgaben übernehmen:

- `geometry`: wiederverwendbare Gebietsgeometrien für Choroplethen und Beschriftungen
- `registry`: stabile Gebietsschlüssel und Crosswalks zwischen externen Codes
- `statistics`: normalisierte Zeitreihen aus World Bank, Eurostat, ILOSTAT und weiteren Quellen

Die Kartensammlung selbst enthält nur Runtime, Panel, Styling und Interaktion. Statistikwerte und Geometrien werden nicht in die MapLibre-Anwendung eingebaut.

## Länder-Geometrie

Der erste Build erzeugt einen globalen, für Statistik-Joins geeigneten Länder-Geometriesatz aus dem Overture-Maps-Theme `divisions`.

Der Zielbestand ist bewusst nicht mit Overtures politischer Klassifizierung `subtype=country` gleichgesetzt. Für statistische Daten ist der stabile Codesatz entscheidend: enthalten werden alle ISO-3166-1-Gebiete, unabhängig davon, ob Overture sie als `country` oder `dependency` klassifiziert, plus ausdrücklich geprüfte zusätzliche Gebiete wie Kosovo (`XK -> XKX`).

### Eingaben

- `division_area`, `subtype IN (country, dependency)`, `is_land=true` für Polygone
- `division`, `subtype IN (country, dependency)` für Labelpunkte und zusätzliche Metadaten
- ISO-3166-Codes aus `pycountry`
- explizit freigegebene Sonderfälle aus `config/country-code-overrides.json`
- explizit geprüfte, aber nicht als Statistikgebiete verwendete synthetische Overture-Codes aus `config/overture-excluded-country-codes.json`

Der Overture-Release wird standardmäßig dynamisch aus dem STAC-Katalog ermittelt. Für reproduzierbare Tests kann ein bestimmter Release mit `--release` vorgegeben werden.

### Statistikgebiete und Overture-Subtypes

Für jedes ISO-3166-1-alpha-2-Gebiet wird genau eine Overture-`division` gewählt. Der Build akzeptiert dafür die Subtypes `country` und `dependency`.

Beispiele:

```text
AT -> country:AUT -> Overture subtype=country
PR -> country:PRI -> Overture subtype=dependency
GL -> country:GRL -> Overture subtype=dependency
XK -> country:XKX -> geprüfter zusätzlicher Mapping-Fall
```

Der Overture-Subtype ist ausschließlich Quellmetadatum. Er bestimmt nicht, ob ein Gebiet in den Statistik-Layer aufgenommen wird, und wird nicht als eigene politische Bewertung der Kartensammlung interpretiert.

Wenn mehrere Overture-Varianten derselben Länderkennung vorhanden sind, wird zuerst eine Variante ohne politische Perspektivmarkierung gewählt. Bei gleicher Perspektivlage wird `country` vor `dependency` bevorzugt; danach entscheidet deterministisch die Overture-ID. Die Zahl tatsächlich notwendiger Perspective-Fallbacks wird in den Build-Metadaten ausgewiesen.

### Overture-Sondergebiete

Overture verwendet bei `subtype=country` neben ISO-Ländercodes auch eigene synthetische `X*`-Codes für umstrittene oder sonstige Sondergebiete. Diese Codes werden **nicht** automatisch in erfundene ISO-3-Codes übersetzt.

Der Layer `country` enthält daher nur:

- den vollständigen ISO-3166-1-Codesatz, soweit er über Overture `country` oder `dependency` repräsentiert wird
- ausdrücklich geprüfte zusätzliche Zuordnungen, derzeit `XK -> XKX` für Kosovo

Die übrigen aktuell bekannten synthetischen Overture-Codes werden bewusst vom Statistik-Ländersatz ausgeschlossen. Die Liste steht in `config/overture-excluded-country-codes.json`. Wenn Overture einen neuen solchen Code einführt, einen bekannten entfernt oder ein bisher synthetisches Gebiet künftig ISO-kompatibel wird, bricht der Build ab und verlangt eine bewusste Prüfung der Policy.

`scripts/inspect_overture_countries.py` zeigt die aktuellen synthetischen Overture-Ländereinträge und die `dependency`-Abdeckung mit Name, Wikidata-ID, Parent-ID und vorhandenen Landflächen an.

### Gebietsschlüssel

Für Länder und ISO-3166-1-Territorien gilt einheitlich:

```text
country:<ISO-3166-1 alpha-3>
```

Beispiele:

```text
country:AUT
country:DEU
country:PRI
country:GRL
country:XKX
```

Die gleiche `area_id` wird sowohl im Polygon- als auch im Label-Layer verwendet. Ein abhängiges Gebiet bleibt damit eine eigenständig joinbare Statistikfläche; die Overture-Abhängigkeit wird nur als Metadatum geführt.

### Ausgaben

`dist/world-admin.pmtiles`

Vector Source-Layer:

```text
country
country_label
```

Beide Layer enthalten derzeit:

```text
area_id
name
iso2
iso3
wikidata
overture_id
overture_subtype
overture_parent_id
```

Zusätzlich werden erzeugt:

```text
dist/area-registry-countries.json
dist/build-metadata.json
```

Das Länderregister verwendet bereits den Vertrag:

```text
kartensammlung.area-registry/v1
```

Jeder Registry-Eintrag enthält zusätzlich `metadata.overtureSubtype` und, falls vorhanden, `metadata.overtureParentId`. Die Build-Metadaten dokumentieren außerdem die Anzahl der aus `country` bzw. `dependency` übernommenen Statistikgebiete und die überprüften, ausgeschlossenen synthetischen Overture-Ländereinträge.

## Aktualisierung

`.github/workflows/build-country-geometry.yml` läuft automatisch am 28. jedes Monats und kann zusätzlich manuell gestartet werden. Overture veröffentlicht das Divisions-Theme monatlich; der Workflow fragt jeweils den aktuellen Release ab.

Der Workflow baut Tippecanoe reproduzierbar aus einer festgelegten Version und prüft den Download per SHA-256. Die eigentlichen Overture-Daten werden mit DuckDB direkt aus den cloud-gehosteten GeoParquet-Dateien gelesen, sodass nicht das vollständige globale Dataset heruntergeladen werden muss.

Die fertigen Dateien werden vorerst als GitHub-Actions-Artefakt gespeichert. Die dauerhafte öffentliche Auslieferung wird separat festgelegt, damit Build und Hosting nicht unnötig gekoppelt werden.

## Validierung

Der Länderbuild bricht unter anderem ab, wenn:

- ein ISO-3166-1-Code plus die ausdrücklich freigegebenen Zusatzcodes nicht über Overture `country` oder `dependency` abgedeckt ist,
- ein nicht ausdrücklich behandelter synthetischer Overture-`country`-Code keine ISO-3-Zuordnung besitzt,
- sich die überprüfte Menge der ausgeschlossenen synthetischen Overture-Codes ändert,
- für ein Statistikgebiet kein Landpolygon vorhanden ist,
- mehrere Landpolygone für dieselbe kanonische Länder-ID entstehen,
- eine Labelgeometrie fehlt,
- Polygon- und Labelanzahl voneinander abweichen,
- die erzeugte Anzahl nicht exakt dem erwarteten ISO-/Override-Codesatz entspricht,
- `country:AUT` fehlt,
- der explizit freigegebene Kosovo-Schlüssel `country:XKX` fehlt,
- `country:PRI` nicht als Overture-`dependency` übernommen wird.

Damit bemerken wir Änderungen am Overture-Datenmodell oder an der Länderabdeckung früh, statt stillschweigend Statistikwerte ohne Geometrie zu erzeugen.

## Lokaler Build

Benötigt werden Python und Tippecanoe. Tippecanoe 2.17 oder neuer kann PMTiles direkt erzeugen.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/build_countries.py
```

Nur Extraktion und Validierung, ohne PMTiles-Erzeugung:

```bash
python scripts/build_countries.py --skip-tiles
```

Bestimmten Overture-Release verwenden:

```bash
python scripts/build_countries.py --release 2026-08-19.0
```

Country-/Dependency-Abdeckung und synthetische Overture-Ländereinträge prüfen:

```bash
python scripts/inspect_overture_countries.py --release 2026-08-19.0
```

## Lizenz und Attribution

Das Overture-Theme `divisions` wird unter ODbL veröffentlicht und enthält unter anderem OpenStreetMap-Daten. Die PMTiles erhalten deshalb die Attribution:

```text
© OpenStreetMap contributors, Overture Maps Foundation
```

Weitere Datenquellen und Statistikdatensätze bekommen jeweils eigene Quellen- und Lizenzmetadaten.
