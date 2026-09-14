# OECD PISA source policy

## Kanonische Quelle

Für die Länderstatistiken werden die von der OECD veröffentlichten aggregierten PISA-Mittelwerte verwendet. Es werden keine Mittelwerte aus den Schüler-Mikrodaten neu berechnet.

Aktuelle Grundlage ist **PISA 2025 Results (Volume I): Future-Ready Students**, veröffentlicht am 8. September 2026. Die Produktionsdaten stammen aus **Annex B1A** über den offiziellen Statlink `https://stat.link/mrq53f`.

Verwendet werden ausschließlich:

- `Table I.B1.2a.36` – Naturwissenschaften, PISA 2006–2025
- `Table I.B1.2a.37` – Lesen, PISA 2000–2025
- `Table I.B1.2a.38` – Mathematik, PISA 2003–2025

Die separaten 2025-Tabellen `I.B1.2a.1`, `I.B1.2a.2` und `I.B1.2a.3` werden nicht als zweite Datenquelle publiziert. Der Builder verwendet sie als Integritätsprüfung und verlangt, dass ihre numerischen 2025-Werte exakt mit den jeweiligen Trendtabellen übereinstimmen.

## Zeitachse

PISA ist keine jährliche Statistik. Ausgegeben werden nur tatsächlich veröffentlichte PISA-Zyklen. Zwischenjahre werden weder interpoliert noch mit dem letzten bekannten Wert aufgefüllt.

Die OECD-Zyklusbezeichnungen bleiben unverändert. Historische Sonderfälle wie PISA 2000+, PISA 2009+ oder PISA for Development können in einem späteren Kalenderjahr durchgeführt worden sein; für die Kartensammlung zählt das von der OECD veröffentlichte Zyklusjahr.

## Gebietszuordnung

OECD-PISA-„countries and economies“ werden nur dann auf eine Länderfläche gelegt, wenn die Einheit räumlich dem Gebiet der Kartensammlung entspricht.

Eigenständig erhalten bleiben insbesondere:

- Hong Kong (China) → `country:HKG`
- Macao (China) → `country:MAC`
- Chinese Taipei → `country:TWN`
- Palestinian Authority → `country:PSE`
- Kosovo → `country:XKX`

Diese Einheiten werden nicht auf einen anderen Staat umgebogen.

Nicht als Ganzstaatenwerte dargestellt werden Teilstichproben, für die keine gleichwertige Ländergeometrie existiert:

- B-S-J-Z (China)
- Dushanbe (Tajikistan)
- Kurdistan Region (Iraq)
- Ukrainian regions (17 of 27)

Neue oder nicht mehr auflösbare Quellnamen führen zu einem Build-Abbruch und müssen bewusst geprüft werden.

## Stichprobenhinweise

Ein Stern `*` am OECD-Ländernamen kennzeichnet PISA-2025-Fälle mit einem Stichproben-/Teilnahmestandard-Hinweis der OECD. Diese Werte werden nicht entfernt oder verändert. Der Builder speichert die betroffenen Einheiten explizit in den Quellmetadaten, damit der Hinweis in der Runtime später sichtbar gemacht werden kann.

## Lizenz

PISA 2025 Results (Volume I) ist von der OECD unter **Creative Commons Attribution 4.0 International (CC BY 4.0)** veröffentlicht. Die Kartensammlung nennt OECD und die konkrete Publikation als Quelle und Attribution.
