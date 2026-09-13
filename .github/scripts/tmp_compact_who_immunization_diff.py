import json
import subprocess
from pathlib import Path

path = Path("config/who-indicators.json")
current = json.loads(path.read_text(encoding="utf-8"))
block = [item for item in current["indicators"] if str(item.get("id", "")).startswith("immunization.")]
assert len(block) == 11

base = subprocess.check_output(
	["git", "show", "origin/main:config/who-indicators.json"],
	text=True,
	encoding="utf-8",
)
start_marker = '\t\t{\n\t\t\t"id": "immunization.dpt-percent"'
end_marker = '\t\t{\n\t\t\t"id": "health-workforce.physicians-per-1000"'
start = base.index(start_marker)
end = base.index(end_marker, start)

rendered = json.dumps(block, ensure_ascii=False, indent="\t").splitlines()
replacement = "\n".join("\t" + line for line in rendered[1:-1]) + ",\n"
path.write_text(base[:start] + replacement + base[end:], encoding="utf-8")

check = json.loads(path.read_text(encoding="utf-8"))
ids = [item["id"] for item in check["indicators"]]
assert len(ids) == 27
assert len(set(ids)) == 27
assert [item["id"] for item in check["indicators"] if item["id"].startswith("immunization.")] == [item["id"] for item in block]
