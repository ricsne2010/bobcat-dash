# Diagram and BOM generators

- `wiring_schematic.py` → `../../wiring-schematic.jpg` (hand-wired sensor/horn/audio diagram)
- `lights_schematic.py` → `../../lights-wiring.jpg` (LED lights: key-controlled relay, fuses, switches, sense wires)
- `make_bom.py` → `../../bobcat-dash-BOM.xlsx` (then recalculate it in LibreOffice or Excel so the totals show)

Needs `pip install schemdraw pillow openpyxl`. Run from this folder: `python3 lights_schematic.py`.
