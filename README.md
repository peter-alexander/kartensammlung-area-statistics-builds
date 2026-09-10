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

### Eingaben

- `division_area`, `subtype=country`, `is_land=true` für Länderpolygone
- `division`, `subtype=country` für Labelpunkte und zusätzliche Metadaten
- ISO-3166-Codes aus `pycountry`
- explizit freigegebene Sonderfälle aus `config/country-code-overrides.json`
- explizit geprüfte, aber nicht als Statistikländer verwendete Overture-Codes aus `config/overture-excluded-country-codes.json`

Der Overture-Release wird standardmäßig dynamisch aus dem STAC-Katalog ermittelt. Für reproduzierbare Tests kann ein bestimmter Release mit `--release` vorgegeben werden.

### Statistikländer und Overture-Sondergebiete

Overture verwendet bei `subtype=country` neben ISO-Ländercodes auch eigene synthetische `X*`-Codes für umstrittene oder sonstige Sondergebiete. Diese Codes werden **nicht** automatisch in erfundene ISO-3-Codes übersetzt.

Der Layer `country` enthält daher nur:

- Länder mit belastbarer ISO-3166-1-alpha-3-Zuordnung
- ausdrücklich geprüfte Sonderfälle, derzeit `XK -> XKX` für Kosovo

Die übrigen aktuell bekannten synthetischen Overture-Codes werden bewusst vom Statistik-Ländersatz ausgeschlossen. Die Liste steht in `config/overture-excluded-country-codes.json`. Wenn Overture einen neuen solchen Code einführt, einen bekannten entfernt oder ein bisher synthetisches Gebiet künftig ISO-kompatibel wird, bricht der Build ab und verlangt eine bewusste Prüfung der Policy.

`scripts/inspect_overture_countries.py` kann die aktuellen synthetischen Overture-Ländereinträge mit Name, Wikidata-ID, GERS-ID und vorhandenen Landflächen ausgeben.

### Gebietsschlüssel

Für Länder gilt:

```text
country:<ISO-3166-1 alpha-3>
```

Beispiele:

```text
country:AUT
country:DEU
country:FRA
country:XKX
```

Die gleiche `area_id` wird sowohl im Polygon- als auch im Label-Layer verwendet.

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

Die Build-Metadaten dokumentieren zusätzlich, welche überprüften Overture-Sondergebiete aus dem Statistik-Ländersatz ausgeschlossen wurden.

## Aktualisierung

`.github/workflows/build-country-geometry.yml` läuft automatisch am 28. jedes Monats und kann zusätzlich manuell gestartet werden. Overture veröffentlicht das Divisions-Theme monatlich; der Workflow fragt jeweils den aktuellen Release ab.

Der Workflow baut Tippecanoe reproduzierbar aus einer festgelegten Version und prüft den Download per SHA-256. Die eigentlichen Overture-Daten werden mit DuckDB direkt aus den cloud-gehosteten GeoParquet-Dateien gelesen, sodass nicht das vollständige globale Dataset heruntergeladen werden muss.

Die fertigen Dateien werden vorerst als GitHub-Actions-Artefakt gespeichert. Die dauerhafte öffentliche Auslieferung wird separat festgelegt, damit Build und Hosting nicht unnötig gekoppelt werden.

## Validierung

Der Länderbuild bricht unter anderem ab, wenn:

- ein nicht ausdrücklich behandelter Overture-Ländercode keine ISO-3-Zuordnung besitzt,
- sich die überprüfte Menge der ausgeschlossenen synthetischen Overture-Codes ändert,
- für ein Statistikland kein Landpolygon vorhanden ist,
- mehrere Landpolygone für dieselbe kanonische Länder-ID entstehen,
- Polygon- und Labelanzahl voneinander abweichen,
- die globale Länderanzahl außerhalb eines plausiblen Bereichs liegt,
- `country:AUT` fehlt,
- der explizit freigegebene Kosovo-Schlüssel `country:XKX` fehlt.

Bei mehreren Overture-`division`-Varianten derselben Länderkennung wird zuerst eine Variante ohne politische Perspektivmarkierung gewählt. Nur wenn keine solche Variante existiert, wird deterministisch eine alternative Variante verwendet; die Zahl dieser Fallbacks wird in den Build-Metadaten ausgewiesen.

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

Synthetische Overture-Ländereinträge prüfen:

```bash
python scripts/inspect_overture_countries.py --release 2026-08-19.0
```

## Lizenz und Attribution

Das Overture-Theme `divisions` wird unter ODbL veröffentlicht und enthält unter anderem OpenStreetMap-Daten. Die PMTiles erhalten deshalb die Attribution:

```text
© OpenStreetMap contributors, Overture Maps Foundation
```

Weitere Datenquellen und Statistikdatensätze bekommen jeweils eigene Quellen- und Lizenzmetadaten.
