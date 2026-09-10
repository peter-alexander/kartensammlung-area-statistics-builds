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

Der Zielbestand ist bewusst nicht mit Overtures politischer Klassifizierung `subtype=country` gleichgesetzt. Für Statistik-Joins ist der stabile Codesatz entscheidend: enthalten werden alle 249 ISO-3166-1-Gebiete plus ausdrücklich geprüfte zusätzliche Gebiete, derzeit Kosovo (`XK -> XKX`). Der erwartete Gesamtbestand beträgt damit 250 Gebiete.

### Direkte Overture-Zuordnungen

Die meisten Gebiete können direkt aus genau einer Overture-`division` übernommen werden. Der Build akzeptiert dafür die Subtypes `country` und `dependency`.

Beispiele:

```text
AT -> country:AUT -> Overture subtype=country
PR -> country:PRI -> Overture subtype=dependency
GL -> country:GRL -> Overture subtype=dependency
XK -> country:XKX -> geprüfter zusätzlicher Mapping-Fall
```

Der Overture-Subtype ist ausschließlich Quellmetadatum. Er bestimmt nicht, ob ein Gebiet in den Statistik-Layer aufgenommen wird, und wird nicht als eigene politische Bewertung der Kartensammlung interpretiert.

Wenn mehrere Overture-Varianten derselben Länderkennung vorhanden sind, wird zuerst eine Variante ohne politische Perspektivmarkierung gewählt. Bei gleicher Perspektivlage wird `country` vor `dependency` bevorzugt; danach entscheidet deterministisch die Overture-ID. Die Zahl tatsächlich notwendiger Perspective-Fallbacks wird in den Build-Metadaten ausgewiesen.

### Zusammengesetzte ISO-Gebiete

Vier ISO-Gebiete entsprechen im aktuellen Overture-Datenmodell nicht genau einer geeigneten `country`-/`dependency`-Geometrie. Sie werden deshalb explizit in `config/country-compositions.json` definiert und ausschließlich aus überprüften Overture-Geometrien zusammengesetzt:

```text
BQ / BES = Bonaire (BQ) + Sint Eustatius (XE) + Saba (XS)
SJ / SJM = Svalbard (SJ) + Jan Mayen (XJ)
PS / PSE = Gaza Strip (XG) + West Bank (XW)
EH / ESH = Western Sahara, Overture region MA / Wikidata Q6250
```

Für diese Gebiete wird die Polygongeometrie mit `ST_Union_Agg` aus den Komponenten aufgebaut. Der Labelpunkt wird mit `ST_PointOnSurface` aus der fertigen Geometrie erzeugt. Dadurch bleibt auch bei MultiPolygon-Geometrien gewährleistet, dass der Punkt auf einer zugehörigen Landfläche liegt. DuckDB Spatial stellt beide Operationen direkt bereit.

Die Registry speichert bei zusammengesetzten Gebieten nicht nur `overtureSubtype=composite`, sondern auch die tatsächlich aufgelösten Overture-Komponenten mit ID, Subtype, Quellcode, Name, Wikidata und gegebenenfalls Parent-ID. Damit bleibt ein späterer Build nachvollziehbar, selbst wenn sich Overture-IDs oder die Klassifizierung ändern.

### Overture-Sondergebiete

Overture verwendet neben ISO-Ländercodes auch eigene synthetische `X*`-Codes für umstrittene oder sonstige Sondergebiete. Diese Codes werden **nicht** automatisch in erfundene ISO-3-Codes übersetzt.

Die aktuell bekannten synthetischen `country`-Codes stehen in `config/overture-excluded-country-codes.json`. Sie werden nicht als eigenständige Statistikgebiete ausgegeben. Einzelne dieser Geometrien dürfen jedoch ausdrücklich als Komponenten eines ISO-Gebiets verwendet werden, beispielsweise `XG` und `XW` für `PSE`.

Wenn Overture einen neuen synthetischen `country`-Code einführt, einen bekannten entfernt oder ein bisher synthetisches Gebiet künftig ISO-kompatibel wird, bricht der Build ab und verlangt eine bewusste Prüfung der Policy.

`scripts/inspect_overture_countries.py` zeigt die synthetischen Overture-Ländereinträge, die `dependency`-Abdeckung sowie gezielte Kandidaten für derzeit nicht direkt abgedeckte ISO-Gebiete.

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
country:BES
country:SJM
country:PSE
country:ESH
country:XKX
```

Die gleiche `area_id` wird sowohl im Polygon- als auch im Label-Layer verwendet.

### Eingaben

- Overture Maps `division` und `division_area`
- `is_land=true` für alle Polygonkomponenten
- ISO-3166-Codes aus `pycountry`
- `config/country-code-overrides.json` für ausdrücklich freigegebene Zusatzcodes
- `config/country-compositions.json` für überprüfte Zusammensetzungen
- `config/overture-excluded-country-codes.json` für synthetische Overture-`country`-Codes, die nicht eigenständig ausgegeben werden

Der Overture-Release wird standardmäßig dynamisch aus dem STAC-Katalog ermittelt. Für reproduzierbare Tests kann ein bestimmter Release mit `--release` vorgegeben werden.

### Ausgaben

`dist/world-admin.pmtiles`

Vector Source-Layer:

```text
country
country_label
```

Beide Layer enthalten:

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

Bei zusammengesetzten Gebieten ist `overture_id` leer und `overture_subtype` gleich `composite`; die Einzelkomponenten stehen vollständig in der Registry.

Zusätzlich werden erzeugt:

```text
dist/area-registry-countries.json
dist/build-metadata.json
```

Das Länderregister verwendet den Vertrag:

```text
kartensammlung.area-registry/v1
```

## Aktualisierung

`.github/workflows/build-country-geometry.yml` läuft automatisch am 28. jedes Monats und kann zusätzlich manuell gestartet werden. Overture veröffentlicht das Divisions-Theme monatlich; der Workflow fragt jeweils den aktuellen Release ab.

Der Workflow baut Tippecanoe reproduzierbar aus einer festgelegten Version und prüft den Download per SHA-256. Die Overture-Daten werden mit DuckDB direkt aus den cloud-gehosteten GeoParquet-Dateien gelesen, sodass nicht das vollständige globale Dataset heruntergeladen werden muss.

Die fertigen Dateien werden vorerst als GitHub-Actions-Artefakt gespeichert. Bei einem fehlgeschlagenen Lauf werden die Coverage- und Build-Diagnosen separat als Actions-Artefakt hochgeladen.

Die dauerhafte öffentliche Auslieferung wird separat festgelegt, damit Build und Hosting nicht unnötig gekoppelt werden.

## Validierung

Der Länderbuild bricht unter anderem ab, wenn:

- ein erwartetes direktes ISO-/Zusatzgebiet keine Overture-`country`-/`dependency`-Division besitzt,
- eine konfigurierte Komponente eines zusammengesetzten Gebiets nicht mehr gefunden wird,
- eine direkte Division oder eine Komponente nicht genau eine `is_land=true`-Geometrie besitzt,
- ein nicht ausdrücklich behandelter synthetischer Overture-`country`-Code auftaucht,
- sich die überprüfte Menge der synthetischen Overture-`country`-Codes ändert,
- eine direkte Labelgeometrie fehlt,
- Polygon- und Labelanzahl voneinander abweichen,
- der fertige Bestand nicht exakt dem ISO-/Override-Codesatz entspricht,
- einer der Sanity-Checks `AUT`, `XKX`, `BES`, `SJM`, `PSE`, `ESH` oder `PRI` fehlschlägt.

Damit bemerken wir Änderungen am Overture-Datenmodell oder an der Länderabdeckung früh, statt stillschweigend Statistikwerte ohne passende Geometrie zu erzeugen.

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

Coverage und Sonderfälle prüfen:

```bash
python scripts/inspect_overture_countries.py --release 2026-08-19.0
```

## Lizenz und Attribution

Das Overture-Theme `divisions` wird unter ODbL veröffentlicht und enthält unter anderem OpenStreetMap-Daten. Die PMTiles erhalten deshalb die Attribution:

```text
© OpenStreetMap contributors, Overture Maps Foundation
```

Weitere Datenquellen und Statistikdatensätze bekommen jeweils eigene Quellen- und Lizenzmetadaten.
