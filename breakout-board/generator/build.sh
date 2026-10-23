#!/bin/bash
# Full rebuild: schematic -> board -> route -> thermals -> checks
set -e
cd "$(dirname "$0")"
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
K=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
F='fontconfig|stdpbase|assert'
python3 gen_sch.py
rm -rf out && mkdir out && cp bobcat-dash-breakout.kicad_sch out/
$K sch export netlist --format kicadsexpr -o out/netlist.net out/bobcat-dash-breakout.kicad_sch 2>&1 | grep -v -i -E "$F" || true
$KPY gen_pcb.py out/bobcat-dash-breakout.kicad_pcb 2>&1 | grep -v -i -E "$F" || true
$KPY route.py out/bobcat-dash-breakout.kicad_pcb 2>&1 | grep -E "exit|completed|routed" || true
$KPY fix_thermals.py out/bobcat-dash-breakout.kicad_pcb 2>&1 | grep -v -i -E "$F" || true
$K sch erc -o out/erc.rpt out/bobcat-dash-breakout.kicad_sch 2>&1 | grep -i violation
$K pcb drc --schematic-parity --format json -o drc.json out/bobcat-dash-breakout.kicad_pcb >/dev/null 2>&1 || true
python3 - <<'PY'
import json, collections
d = json.load(open("drc.json"))
print("DRC violations:", dict(collections.Counter(v["type"] for v in d["violations"])) or "none")
print("unrouted:", len(d["unconnected_items"]))
print("schematic parity:", dict(collections.Counter(v["type"] for v in d.get("schematic_parity", []))) or "none")
for v in (d["violations"] + d["unconnected_items"] + d.get("schematic_parity", []))[:12]:
    print("  ", v["type"], "|", v.get("description", ""), "|", " / ".join(i["description"] for i in v["items"]))
PY
