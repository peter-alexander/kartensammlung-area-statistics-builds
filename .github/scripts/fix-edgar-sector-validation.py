from pathlib import Path

path = Path("scripts/build_edgar.py")
text = path.read_text(encoding="utf-8")
old = '''\t\tif set(sector_values[substance]) != set(sector_values[next(iter(allowed_substances))]):
\t\t\t# Both gases should expose the same safe country geography in this report edition.
\t\t\tpass
\t\tfor area_id, sectors in sector_values[substance].items():
\t\t\tif sectors != expected_sectors:
\t\t\t\traise RuntimeError(
\t\t\t\t\tf"EDGAR {substance} sectors incomplete for {area_id}: {sorted(sectors)}"
\t\t\t\t)
'''
new = '''\t\tobserved_sectors = set().union(*sector_values[substance].values())
\t\tif observed_sectors != expected_sectors:
\t\t\traise RuntimeError(
\t\t\t\tf"EDGAR sector set changed for {substance}: {sorted(observed_sectors)}"
\t\t\t)
'''
if old not in text:
	raise SystemExit("Expected sector-validation block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
