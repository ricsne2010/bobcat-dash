#!/bin/bash
# ADS1115 adapter: schematic -> board -> route (the breakout board's route.py) -> checks
set -e
cd "$(dirname "$0")"
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
K=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
F='fontconfig|stdpbase|assert|memory leak'
N=ads1115-adapter
python3 gen_sch.py
rm -rf out && mkdir out && cp ../kicad/$N.kicad_sch out/
$KPY gen_pcb.py out/$N.kicad_pcb 2>&1 | grep -v -i -E "$F" || true
$KPY ../../generator/route.py out/$N.kicad_pcb 2>&1 | grep --line-buffered -E "exit|completed|routed" || true
$K sch erc -o out/erc.rpt out/$N.kicad_sch 2>&1 | grep -i violation
$K pcb drc --schematic-parity --format json -o out/drc.json out/$N.kicad_pcb >/dev/null 2>&1 || true
python3 - <<'PY'
import json, collections
d = json.load(open("out/drc.json"))
print("DRC violations:", dict(collections.Counter(v["type"] for v in d["violations"])) or "none")
print("unrouted:", len(d["unconnected_items"]))
print("schematic parity:", dict(collections.Counter(v["type"] for v in d.get("schematic_parity", []))) or "none")
for v in (d["violations"] + d["unconnected_items"] + d.get("schematic_parity", []))[:12]:
    print("  ", v["type"], "|", v.get("description", ""), "|", " / ".join(i["description"] for i in v["items"]))
PY
