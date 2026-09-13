import json
from pathlib import Path

config_path = Path("config/who-indicators.json")
workflow_path = Path(".github/workflows/build-who-statistics.yml")

config = json.loads(config_path.read_text(encoding="utf-8"))
indicators = config["indicators"]
by_id = {item["id"]: item for item in indicators}

dtp3 = dict(by_id["immunization.dpt-percent"])
mcv1 = dict(by_id["immunization.measles-percent"])

wuenic_dataset = "WHO Global Health Observatory / WHO-UNICEF Estimates of National Immunization Coverage (WUENIC)"
coverage_url = "https://www.who.int/data/gho/data/themes/topics/immunization-coverage"
standard_breaks = [50, 70, 80, 90, 95, 99]
required_global = ["country:AUT", "country:DEU", "country:USA", "country:IND"]

dtp3.update({
	"sourceFormat": "gho-odata",
	"sourceIndicator": "WHS4_100",
	"sourceIndicatorName": "Diphtheria tetanus toxoid and pertussis third-dose (DTP3) immunization coverage among 1-year-olds (%) (WUENIC)",
	"sourceDataset": wuenic_dataset,
	"sourceUrl": "https://data.who.int/indicators/i/48D7D19/F8E084C",
	"downloadUrl": "https://ghoapi.azureedge.net/api/WHS4_100",
	"startYear": 1980,
	"endYear": 2025,
	"expectedReferenceYear": 2025,
	"title": "DTP3-Impfquote",
	"description": "Anteil der Einjährigen, die drei Dosen eines Diphtherie-, Tetanus- und Pertussis-haltigen Impfstoffs erhalten haben. Die harmonisierte WHO/UNICEF-Schätzung WUENIC ist die kanonische Direktquelle; World Bank WDI ergänzt ausschließlich die Historie vor 2000 und einzelne Länder-/Jahrlücken und wird als Fallback markiert.",
	"minAreasWithAnyValue": 190,
	"minAreasInDefaultYear": 190,
})
dtp3.pop("sourceUuid", None)

mcv1.update({
	"sourceDataset": wuenic_dataset,
	"title": "Masern-Impfquote (1. Dosis)",
	"description": "WHO/UNICEF-Schätzung WUENIC der MCV1-Impfquote, also des Anteils der Einjährigen mit mindestens einer Dosis eines masernhaltigen Impfstoffs. Der aktuelle direkte WHO-GHO-Stand ist kanonisch; World Bank WDI ergänzt ausschließlich die Historie vor 2000 und einzelne Länder-/Jahrlücken und wird als Fallback markiert.",
	"minAreasWithAnyValue": 190,
	"minAreasInDefaultYear": 190,
})

def vaccine(indicator_id, slug, source, source_name, title, description, start_year, *, min_areas=190, required=None, breaks=None):
	return {
		"id": indicator_id,
		"slug": slug,
		"sourceFormat": "gho-odata",
		"sourceIndicator": source,
		"sourceIndicatorName": source_name,
		"sourceDataset": wuenic_dataset,
		"sourceUrl": coverage_url,
		"downloadUrl": f"https://ghoapi.azureedge.net/api/{source}",
		"valueField": "RATE_PER_100_N",
		"confidenceIntervals": False,
		"startYear": start_year,
		"endYear": 2025,
		"expectedReferenceYear": 2025,
		"title": title,
		"description": description,
		"unit": {"id": "percent", "label": "Prozent", "symbol": "%"},
		"classification": {"type": "fixed", "breaks": breaks or standard_breaks},
		"valueRange": [0, 100],
		"minAreasWithAnyValue": min_areas,
		"minAreasInDefaultYear": min_areas,
		"requiredAreas": required or required_global,
	}

new_block = [
	vaccine(
		"immunization.dpt1-percent", "immunization-dpt1-percent", "VACCINECOVERAGE_DTP1",
		"Diphtheria tetanus toxoid and pertussis first-dose (DTP1) immunization coverage among 1-year-olds (%) (WUENIC)",
		"DTP1-Impfquote",
		"Anteil der Einjährigen, die mindestens eine Dosis eines Diphtherie-, Tetanus- und Pertussis-haltigen Impfstoffs erhalten haben; harmonisierte WHO/UNICEF-Schätzung WUENIC.",
		2000,
	),
	dtp3,
	vaccine(
		"immunization.hepatitis-b3-percent", "immunization-hepatitis-b3-percent", "WHS4_117",
		"Hepatitis B (HepB3) immunization coverage among 1-year-olds (%) (WUENIC)",
		"Hepatitis-B-Impfquote (3 Dosen)",
		"Anteil der Einjährigen, die drei Dosen eines Hepatitis-B-haltigen Impfstoffs erhalten haben; harmonisierte WHO/UNICEF-Schätzung WUENIC.",
		2000,
	),
	vaccine(
		"immunization.hib3-percent", "immunization-hib3-percent", "WHS4_129",
		"Hib (Hib3) immunization coverage among 1-year-olds (%) (WUENIC)",
		"Hib-Impfquote (3 Dosen)",
		"Anteil der Einjährigen, die drei Dosen eines Haemophilus-influenzae-Typ-b-haltigen Impfstoffs erhalten haben; harmonisierte WHO/UNICEF-Schätzung WUENIC.",
		2000,
	),
	mcv1,
	vaccine(
		"immunization.measles2-percent", "immunization-measles2-percent", "MCV2",
		"Measles-containing-vaccine second-dose (MCV2) immunization coverage by the locally recommended age (%) (WUENIC)",
		"Masern-Impfquote (2. Dosis)",
		"Anteil der Zielgruppe, die bis zum jeweils national empfohlenen Alter die zweite Dosis eines masernhaltigen Impfstoffs erhalten hat; harmonisierte WHO/UNICEF-Schätzung WUENIC.",
		2000,
	),
	vaccine(
		"immunization.pneumococcal-percent", "immunization-pneumococcal-percent", "PCV3",
		"Pneumococcal conjugate second or third-dose vaccines (PCVc) immunization coverage by the locally recommended age (%) (WUENIC)",
		"Pneumokokken-Impfquote",
		"Anteil der Zielgruppe, die die national vorgesehene zweite oder dritte Dosis eines Pneumokokken-Konjugatimpfstoffs erhalten hat; harmonisierte WHO/UNICEF-Schätzung WUENIC. Ein veröffentlichter Wert von 0 bleibt als echter Quellenwert erhalten.",
		2008,
	),
	vaccine(
		"immunization.polio-ipv1-percent", "immunization-polio-ipv1-percent", "VACCINECOVERAGE_IPV1",
		"Inactivated first-dose polio vaccine (IPV1) immunization coverage among 1-year-olds (%) (WUENIC)",
		"Polio-Impfquote (IPV1)",
		"Anteil der Einjährigen mit mindestens einer Dosis eines inaktivierten Polioimpfstoffs (IPV); harmonisierte WHO/UNICEF-Schätzung WUENIC.",
		2015,
	),
	vaccine(
		"immunization.polio-ipvc-percent", "immunization-polio-ipvc-percent", "WHS4_544",
		"Polio vaccine: inactivated second or third-dose polio vaccine (IPVc) immunization coverage by the locally recommended age (%) (WUENIC)",
		"Polio-Impfquote (IPVc)",
		"Anteil der Zielgruppe, die bis zum national empfohlenen Alter die vollständige zweite oder dritte Dosis des inaktivierten Polioimpfstoffs erhalten hat; harmonisierte WHO/UNICEF-Schätzung WUENIC.",
		2021,
	),
	vaccine(
		"immunization.rotavirus-percent", "immunization-rotavirus-percent", "ROTAC",
		"Rotavirus vaccines completed dose (RotaC) immunization coverage among 1-year-olds (%)",
		"Rotavirus-Impfquote",
		"Anteil der Einjährigen, die die für den verwendeten Rotavirus-Impfstoff vorgesehene Impfserie abgeschlossen haben; harmonisierte WHO/UNICEF-Schätzung.",
		2006,
	),
	vaccine(
		"immunization.hpv-girls-percent", "immunization-hpv-girls-percent", "SDGHPVRECEIVED",
		"HPV immunization coverage estimates among primary target cohort (9-14 years old girls) (%)",
		"HPV-Impfquote Mädchen (9–14)",
		"WHO-Schätzung des Anteils der primären HPV-Zielkohorte von Mädchen im Alter von 9 bis 14 Jahren, die gemäß der jeweiligen nationalen Definition gegen HPV geimpft wurde. Die Reihe ist breiter verfügbar als früher, aber noch nicht für alle Staaten vorhanden.",
		2010,
		min_areas=150,
		required=["country:AUT", "country:DEU", "country:USA"],
		breaks=[10, 25, 50, 70, 90, 95],
	),
]

immunization_ids = {"immunization.dpt-percent", "immunization.measles-percent"}
first_index = min(index for index, item in enumerate(indicators) if item["id"] in immunization_ids)
remaining = [item for item in indicators if item["id"] not in immunization_ids]
config["indicators"] = remaining[:first_index] + new_block + remaining[first_index:]
assert len(config["indicators"]) == 27
assert len({item["id"] for item in config["indicators"]}) == 27
assert len({item["slug"] for item in config["indicators"]}) == 27
config_path.write_text(json.dumps(config, ensure_ascii=False, indent="\t") + "\n", encoding="utf-8")

workflow = workflow_path.read_text(encoding="utf-8")
old_count = 'assert len(provider["indicators"]) == 18, len(provider["indicators"])'
assert old_count in workflow
workflow = workflow.replace(old_count, 'assert len(provider["indicators"]) == 27, len(provider["indicators"])', 1)

start = workflow.index('          dtp = by_id["immunization.dpt-percent"]')
end = workflow.index('          measles = by_id["immunization.measles-percent"]', start)

replacement = '''          dtp = by_id["immunization.dpt-percent"]
          assert dtp["frequency"] == "annual"
          assert dtp["availableYears"] == list(range(1980, 2026)), dtp["availableYears"]
          assert dtp["defaultYear"] == 2025, dtp["defaultYear"]
          assert dtp["coverage"]["areasInDefaultYear"] >= 190, dtp["coverage"]
          assert dtp["coverage"]["directObservations"] >= 5000, dtp["coverage"]
          assert dtp["coverage"]["fallbackObservations"] >= 3000, dtp["coverage"]
          assert dtp["confidenceIntervals"] is False
          dtp_payload = json.loads(Path("dist/statistics/who", dtp["path"]).read_text(encoding="utf-8"))
          assert dtp_payload["source"]["providerId"] == "who"
          assert dtp_payload["source"]["indicator"] == "WHS4_100"
          assert dtp_payload["source"]["sourceFormat"] == "gho-odata"
          assert dtp_payload["source"]["fallback"]["indicator"] == "SH.IMM.IDPT"
          assert dtp_payload["source"]["timeCoverage"] == {"startYear": 2000, "endYear": 2025}
          assert "indicatorUuid" not in dtp_payload["source"]
          assert dtp_payload["indicator"]["confidenceIntervals"] == {"available": False}
          assert dtp_payload.get("observationMetadata")

          immunization_expected = {
          \t"immunization.dpt1-percent": {"source": "VACCINECOVERAGE_DTP1", "start": 2000, "minDirect": 5000, "minCoverage": 190},
          \t"immunization.hepatitis-b3-percent": {"source": "WHS4_117", "start": 2000, "minDirect": 5000, "minCoverage": 190},
          \t"immunization.hib3-percent": {"source": "WHS4_129", "start": 2000, "minDirect": 5000, "minCoverage": 190},
          \t"immunization.measles2-percent": {"source": "MCV2", "start": 2000, "minDirect": 5000, "minCoverage": 190},
          \t"immunization.pneumococcal-percent": {"source": "PCV3", "start": 2008, "minDirect": 3400, "minCoverage": 190},
          \t"immunization.polio-ipv1-percent": {"source": "VACCINECOVERAGE_IPV1", "start": 2015, "minDirect": 2100, "minCoverage": 190},
          \t"immunization.polio-ipvc-percent": {"source": "WHS4_544", "start": 2021, "minDirect": 950, "minCoverage": 190},
          \t"immunization.rotavirus-percent": {"source": "ROTAC", "start": 2006, "minDirect": 3800, "minCoverage": 190},
          \t"immunization.hpv-girls-percent": {"source": "SDGHPVRECEIVED", "start": 2010, "minDirect": 2500, "minCoverage": 150},
          }
          for indicator_id, expected in immunization_expected.items():
          \titem = by_id[indicator_id]
          \tassert item["frequency"] == "annual", (indicator_id, item["frequency"])
          \tassert item["availableYears"][0] == expected["start"], (indicator_id, item["availableYears"])
          \tassert item["availableYears"][-1] == 2025, (indicator_id, item["availableYears"])
          \tassert item["defaultYear"] == 2025, (indicator_id, item["defaultYear"])
          \tassert item["coverage"]["areasInDefaultYear"] >= expected["minCoverage"], (indicator_id, item["coverage"])
          \tassert item["coverage"]["directObservations"] >= expected["minDirect"], (indicator_id, item["coverage"])
          \tassert item["coverage"]["fallbackObservations"] == 0, (indicator_id, item["coverage"])
          \tassert item["confidenceIntervals"] is False
          \tpayload = json.loads(Path("dist/statistics/who", item["path"]).read_text(encoding="utf-8"))
          \tassert payload["source"]["providerId"] == "who"
          \tassert payload["source"]["indicator"] == expected["source"]
          \tassert payload["source"]["sourceFormat"] == "gho-odata"
          \tassert payload["source"]["timeCoverage"] == {"startYear": expected["start"], "endYear": 2025}
          \tassert "fallback" not in payload["source"]
          \tassert "indicatorUuid" not in payload["source"]
          \tassert payload["indicator"]["confidenceIntervals"] == {"available": False}
          \tassert not payload.get("observationMetadata")

'''
workflow = workflow[:start] + replacement + workflow[end:]
workflow_path.write_text(workflow, encoding="utf-8")
