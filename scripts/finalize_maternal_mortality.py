#!/usr/bin/env python3
from pathlib import Path

path = Path(".github/workflows/build-who-statistics.yml")
text = path.read_text(encoding="utf-8")

old_count = '          assert len(provider["indicators"]) == 8, len(provider["indicators"])'
new_count = '          assert len(provider["indicators"]) == 9, len(provider["indicators"])'
if text.count(old_count) != 1:
	raise SystemExit("Expected exactly one WHO indicator-count assertion")
text = text.replace(old_count, new_count, 1)

marker = '''          print(f"snapshot={provider['activeSnapshot']}")'''
maternal = '''          maternal = by_id["mortality.maternal-per-100000-live-births"]
          assert maternal["frequency"] == "annual"
          assert maternal["availableYears"] == list(range(1985, 2024)), maternal["availableYears"]
          assert maternal["defaultYear"] == 2023, maternal["defaultYear"]
          assert maternal["coverage"]["areasWithAnyValue"] == 195, maternal["coverage"]
          assert maternal["coverage"]["areasInDefaultYear"] == 195, maternal["coverage"]
          assert maternal["coverage"]["directObservations"] == 7605, maternal["coverage"]
          assert maternal["coverage"]["fallbackObservations"] == 0, maternal["coverage"]
          assert maternal["confidenceIntervals"] is True
          maternal_payload = json.loads(Path("dist/statistics/who", maternal["path"]).read_text(encoding="utf-8"))
          assert maternal_payload["source"]["providerId"] == "who"
          assert maternal_payload["source"]["indicator"] == "MDG_0000000026"
          assert maternal_payload["source"]["sourceFormat"] == "gho-odata"
          assert maternal_payload["source"]["timeCoverage"] == {"startYear": 1985, "endYear": 2023}
          assert "fallback" not in maternal_payload["source"]
          assert "indicatorUuid" not in maternal_payload["source"]
          assert maternal_payload["indicator"]["confidenceIntervals"]["available"] is True
          maternal_intervals = sum(
          \tlen(values) for values in maternal_payload["confidenceIntervals"]["values"].values()
          )
          assert maternal_intervals == 7605, maternal_intervals
          assert "country:COK" in maternal_payload["values"]["2023"]
          assert not maternal_payload.get("observationMetadata")

''' + marker
if text.count(marker) != 1:
	raise SystemExit("Expected exactly one WHO validation print marker")
text = text.replace(marker, maternal, 1)
path.write_text(text, encoding="utf-8")
